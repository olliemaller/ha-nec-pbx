"""Edge cases: flow errors, logbook wording, diagnostics masking and DND failures."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from aionecpbx import AmiAuthError
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import Event, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_component import async_update_entity
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nec_pbx.const import (
    CONF_AMI_HOST,
    CONF_AMI_PORT,
    CONF_AMI_SECRET,
    CONF_AMI_USER,
    CONF_EXTENSIONS,
    CONF_PHONEBOOK,
    DOMAIN,
    EVENT_CALL,
)
from custom_components.nec_pbx.diagnostics import _mask
from custom_components.nec_pbx.logbook import async_describe_events, describe_call

from .test_ami import _setup as _setup_ami, ami  # noqa: F401
from .test_init import FakePbx, _setup as _setup_smdr, _wait, pbx  # noqa: F401

PROBE = "custom_components.nec_pbx.config_flow.async_probe"
LOGIN = "custom_components.nec_pbx.config_flow.async_test_login"
SETUP = "custom_components.nec_pbx.async_setup_entry"


async def test_reconfigure_cannot_connect(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "192.168.0.10", CONF_PORT: 4001},
        unique_id="192.168.0.10:4001",
    )
    entry.add_to_hass(hass)
    with patch(SETUP, AsyncMock(return_value=True)):
        result = await entry.start_reconfigure_flow(hass)
        with patch(PROBE, AsyncMock(side_effect=OSError)):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_HOST: "192.168.0.11", CONF_PORT: 4001}
            )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.data[CONF_HOST] == "192.168.0.10"


@pytest.mark.parametrize(
    ("side_effect", "errors"),
    [
        (AmiAuthError("nope"), {CONF_AMI_USER: "ami_auth"}),
        (OSError("down"), {CONF_AMI_HOST: "ami_cannot_connect"}),
        (None, None),
    ],
)
async def test_options_check_freepbx_login(
    hass: HomeAssistant, side_effect: Exception | None, errors: dict[str, str] | None
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: "192.168.0.10", CONF_PORT: 4001})
    entry.add_to_hass(hass)
    login = AsyncMock(side_effect=side_effect)
    with patch(SETUP, AsyncMock(return_value=True)), patch(LOGIN, login):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_EXTENSIONS: "",
                CONF_PHONEBOOK: "",
                CONF_AMI_HOST: " 192.168.0.20 ",
                CONF_AMI_PORT: 5038,
                CONF_AMI_USER: "homeassistant",
                CONF_AMI_SECRET: "s3cret",
            },
        )
    login.assert_awaited_once_with("192.168.0.20", 5038, "homeassistant", "s3cret")
    if errors is None:
        assert result["type"] is FlowResultType.CREATE_ENTRY
    else:
        assert result["errors"] == errors


def test_mask_keeps_short_numbers_and_none() -> None:
    assert _mask(None) is None
    assert _mask("ext 103") == "ext 103"
    assert _mask("0491570156") == "0491xxxxxx"


@pytest.mark.parametrize(
    ("data", "text"),
    [
        (
            {"missed": False, "direction": "parked", "number": "0491570156", "station": "103"},
            "call with 0491570156 on 103",
        ),
        ({"missed": False}, "call"),
        ({"missed": False, "direction": "incoming"}, "call"),
    ],
)
def test_logbook_other_directions(data: dict, text: str) -> None:
    assert describe_call(data) == text


async def test_logbook_names_the_phone_system(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="Home phones", data={})
    entry.add_to_hass(hass)
    described: dict[str, object] = {}

    def _register(domain: str, event_type: str, describe) -> None:
        described.update(domain=domain, event_type=event_type, describe=describe)

    async_describe_events(hass, _register)
    assert described["domain"] == DOMAIN
    assert described["event_type"] == EVENT_CALL
    describe = described["describe"]
    known = describe(Event(EVENT_CALL, {"entry_id": entry.entry_id, "missed": True}))
    assert known["name"] == "Home phones"
    assert known["message"] == "missed call"
    unknown = describe(Event(EVENT_CALL, {"missed": True}))
    assert unknown["name"] == "Phone system"


async def test_do_not_disturb_failures(hass: HomeAssistant, ami) -> None:  # noqa: F811
    smdr, fake = ami
    entry = await _setup_ami(hass, smdr, fake)
    async with asyncio.timeout(3):
        await fake.logged_in.wait()
    switch = "switch.home_phones_do_not_disturb_901"
    await _wait(hass, lambda: hass.states.get(switch).state != "unavailable")
    client = entry.runtime_data.ami

    with (
        patch.object(client, "set_dnd", AsyncMock(side_effect=TimeoutError("slow"))),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    before = hass.states.get(switch).state

    # A failed check keeps the last known state rather than going unknown.
    with patch.object(client, "get_dnd", AsyncMock(side_effect=ConnectionError)):
        await async_update_entity(hass, switch)
    assert hass.states.get(switch).state == before

    # While FreePBX is unreachable the switch is unavailable and skips its check.
    get_dnd = AsyncMock()
    with (
        patch.object(client, "connected", False),
        patch.object(client, "get_dnd", get_dnd),
    ):
        await async_update_entity(hass, switch)
    get_dnd.assert_not_awaited()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_save_caller_refuses_what_it_cannot_save(hass: HomeAssistant, pbx: FakePbx) -> None:  # noqa: F811
    from homeassistant.exceptions import ServiceValidationError

    entry = await _setup_smdr(hass, pbx)

    async def _save(data: dict) -> None:
        await hass.services.async_call(
            DOMAIN, "save_caller", data, blocking=True, return_response=True
        )

    with pytest.raises(ServiceValidationError) as err:
        await _save({"name": "Plumber"})
    assert err.value.translation_key == "no_caller_yet"
    with pytest.raises(ServiceValidationError) as err:
        await _save({"name": "Plumber", "number": "0491570XXX"})
    assert err.value.translation_key == "number_hidden"
    with pytest.raises(ServiceValidationError) as err:
        await _save({"name": "Plumber", "number": "0491570123", "config_entry_id": "nope"})
    assert err.value.translation_key == "not_set_up"

    # Without a to-do list the number goes into the typed phonebook.
    await _save({"name": " Plumber ", "number": "0491 570 123"})
    await hass.async_block_till_done()
    assert "0491570123: Plumber" in entry.options[CONF_PHONEBOOK]
    for e in hass.config_entries.async_entries(DOMAIN):
        await hass.config_entries.async_unload(e.entry_id)
