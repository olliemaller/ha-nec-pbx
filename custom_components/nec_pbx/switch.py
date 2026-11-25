"""Do-not-disturb switches for FreePBX extensions (needs the FreePBX connection)."""

from __future__ import annotations

import time
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NecPbxConfigEntry
from .const import CONF_DND_EXTENSIONS, DND_FALLBACK_POLL, DOMAIN, SIGNAL_DND
from .entity import NecPbxEntity

PARALLEL_UPDATES = 1


def dnd_extensions(text: str) -> list[str]:
    """'901, 902' or one per line -> ['901', '902']."""
    return [part.strip() for part in text.replace("\n", ",").split(",") if part.strip()]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NecPbxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    if entry.runtime_data.ami is None:
        return
    async_add_entities(
        NecPbxDndSwitch(entry, ext)
        for ext in dnd_extensions(entry.options.get(CONF_DND_EXTENSIONS, ""))
    )


class NecPbxDndSwitch(NecPbxEntity, SwitchEntity):
    """FreePBX do-not-disturb for one extension: on = calls to it are not rung."""

    _attr_translation_key = "do_not_disturb"
    # DND can also be set from a phone (*76). FreePBX usually says so straight away
    # (SIGNAL_DND); until it has, check every 30 seconds, then every DND_FALLBACK_POLL.
    _attr_should_poll = True

    def __init__(self, entry: NecPbxConfigEntry, ext: str) -> None:
        name = entry.runtime_data.extensions.get(ext)
        if name is None:
            super().__init__(entry, f"dnd_{ext}")
            self._attr_translation_placeholders = {"extension": ext}
        else:  # a named extension: on its own device
            super().__init__(entry, f"dnd_{ext}", sub_device=("extension", ext, name))
            self._attr_translation_key = "extension_do_not_disturb"
        self._ext = ext
        self._attr_is_on: bool | None = None
        self._checked = 0.0

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_DND.format(self._entry.entry_id), self._pushed
            )
        )

    @callback
    def _pushed(self, ext: str, on: bool) -> None:
        if ext == self._ext:
            self._attr_is_on = on
            self._checked = time.monotonic()
            self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self.data.ami is not None and self.data.ami.connected

    async def async_update(self) -> None:
        if (ami := self.data.ami) is None or not ami.connected:
            return
        if (
            self.data.dnd_pushed
            and time.monotonic() - self._checked < DND_FALLBACK_POLL.total_seconds()
        ):
            return
        try:
            self._attr_is_on = await ami.get_dnd(self._ext)
        except (ConnectionError, TimeoutError):
            return
        self._checked = time.monotonic()

    async def _set(self, on: bool) -> None:
        try:
            if (ami := self.data.ami) is None:
                raise ConnectionError("FreePBX is not set up")
            await ami.set_dnd(self._ext, on)
        except (ConnectionError, TimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="dnd_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        self._attr_is_on = on
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
