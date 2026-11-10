"""Config and options flow tests."""

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nec_pbx.const import CONF_EXTENSIONS, CONF_PHONEBOOK, DOMAIN

PROBE = "custom_components.nec_pbx.config_flow.async_probe"
SETUP = "custom_components.nec_pbx.async_setup_entry"


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    with patch(PROBE, AsyncMock()), patch(SETUP, AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "192.168.0.10", CONF_PORT: 4001, CONF_NAME: "Teak phones"},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Teak phones"
    assert result["data"] == {CONF_HOST: "192.168.0.10", CONF_PORT: 4001}


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with patch(PROBE, AsyncMock(side_effect=OSError("refused"))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.0.10", CONF_PORT: 4001}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_duplicate_is_aborted(hass: HomeAssistant) -> None:
    MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "192.168.0.10", CONF_PORT: 4001},
        unique_id="192.168.0.10:4001",
    ).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.0.10", CONF_PORT: 4001}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: "192.168.0.10", CONF_PORT: 4001})
    entry.add_to_hass(hass)
    with patch(SETUP, AsyncMock(return_value=True)):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        bad = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_EXTENSIONS: "103 Oliver", CONF_PHONEBOOK: ""}
        )
        assert bad["errors"] == {CONF_EXTENSIONS: "bad_mapping"}
        good = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_EXTENSIONS: "103: Oliver", CONF_PHONEBOOK: "0491570156: Alex"},
        )
    assert good["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_EXTENSIONS] == "103: Oliver"


async def test_reconfigure(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "192.168.0.10", CONF_PORT: 4001},
        unique_id="192.168.0.10:4001",
    )
    entry.add_to_hass(hass)
    with patch(SETUP, AsyncMock(return_value=True)):
        result = await entry.start_reconfigure_flow(hass)
        assert result["type"] is FlowResultType.FORM
        with patch(PROBE, AsyncMock()):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_HOST: "192.168.0.11", CONF_PORT: 4001}
            )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == "192.168.0.11"
