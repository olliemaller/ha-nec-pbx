"""Config flow for NEC PBX."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import selector
import voluptuous as vol

from .ami import DEFAULT_AMI_PORT, AmiAuthError, async_test_login
from .client import async_probe
from .const import (
    CONF_AMI_HOST,
    CONF_AMI_PORT,
    CONF_AMI_SECRET,
    CONF_AMI_USER,
    CONF_DATE_ORDER,
    CONF_DND_EXTENSIONS,
    CONF_EXTENSIONS,
    CONF_LINES,
    CONF_PHONEBOOK,
    CONF_PHONEBOOK_TODO,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DOMAIN,
)
from .smdr import DATE_AUTO, DATE_ORDERS, parse_mapping

_TEXTAREA = selector.TextSelector(selector.TextSelectorConfig(multiline=True))
_DATE_ORDER = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=list(DATE_ORDERS),
        translation_key=CONF_DATE_ORDER,
        mode=selector.SelectSelectorMode.DROPDOWN,
    )
)


def _user_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
            vol.Optional(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)): str,
        }
    )


class NecPbxConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setup of an NEC PBX."""

    VERSION = 1

    async def _test(self, user_input: dict[str, Any]) -> str | None:
        try:
            await async_probe(user_input[CONF_HOST], user_input[CONF_PORT])
        except (OSError, TimeoutError):
            return "cannot_connect"
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the PBX address."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}")
            self._abort_if_unique_id_configured()
            if (error := await self._test(user_input)) is None:
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME) or DEFAULT_NAME,
                    data={CONF_HOST: user_input[CONF_HOST], CONF_PORT: user_input[CONF_PORT]},
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="user", data_schema=_user_schema(user_input or {}), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the address or port."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            if (error := await self._test(user_input)) is None:
                return self.async_update_reload_and_abort(
                    entry,
                    data={CONF_HOST: user_input[CONF_HOST], CONF_PORT: user_input[CONF_PORT]},
                )
            errors["base"] = error
        defaults = user_input or {**entry.data, CONF_NAME: entry.title}
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=defaults[CONF_HOST]): str,
                    vol.Required(CONF_PORT, default=defaults[CONF_PORT]): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=65535)
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return NecPbxOptionsFlow()


class NecPbxOptionsFlow(OptionsFlow):
    """Room names and the phonebook."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            for key in (CONF_EXTENSIONS, CONF_PHONEBOOK, CONF_LINES):
                text = user_input.get(key, "")
                lines = [line for line in text.splitlines() if line.strip()]
                if len(parse_mapping(text)) != len(lines):
                    errors[key] = "bad_mapping"
            if not errors and (host := (user_input.get(CONF_AMI_HOST) or "").strip()):
                try:
                    await async_test_login(
                        host,
                        int(user_input.get(CONF_AMI_PORT) or DEFAULT_AMI_PORT),
                        user_input.get(CONF_AMI_USER, ""),
                        user_input.get(CONF_AMI_SECRET, ""),
                    )
                except AmiAuthError:
                    errors[CONF_AMI_USER] = "ami_auth"
                except (OSError, TimeoutError, ConnectionError):
                    errors[CONF_AMI_HOST] = "ami_cannot_connect"
            if not errors:
                return self.async_create_entry(data=user_input)
        current = user_input or self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_EXTENSIONS,
                        description={"suggested_value": current.get(CONF_EXTENSIONS, "")},
                    ): _TEXTAREA,
                    vol.Optional(
                        CONF_PHONEBOOK,
                        description={"suggested_value": current.get(CONF_PHONEBOOK, "")},
                    ): _TEXTAREA,
                    vol.Optional(
                        CONF_PHONEBOOK_TODO,
                        description={"suggested_value": current.get(CONF_PHONEBOOK_TODO)},
                    ): selector.EntitySelector(selector.EntitySelectorConfig(domain="todo")),
                    vol.Optional(
                        CONF_LINES,
                        description={"suggested_value": current.get(CONF_LINES, "")},
                    ): _TEXTAREA,
                    vol.Required(
                        CONF_DATE_ORDER, default=current.get(CONF_DATE_ORDER, DATE_AUTO)
                    ): _DATE_ORDER,
                    vol.Optional(
                        CONF_AMI_HOST,
                        description={"suggested_value": current.get(CONF_AMI_HOST, "")},
                    ): str,
                    vol.Optional(
                        CONF_AMI_PORT, default=current.get(CONF_AMI_PORT, DEFAULT_AMI_PORT)
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                    vol.Optional(
                        CONF_AMI_USER,
                        description={"suggested_value": current.get(CONF_AMI_USER, "")},
                    ): str,
                    vol.Optional(
                        CONF_AMI_SECRET,
                        description={"suggested_value": current.get(CONF_AMI_SECRET, "")},
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(
                        CONF_DND_EXTENSIONS,
                        description={"suggested_value": current.get(CONF_DND_EXTENSIONS, "")},
                    ): str,
                }
            ),
            errors=errors,
        )
