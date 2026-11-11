"""NEC PBX: call records from an NEC SL2100 / SV9100 phone system."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .client import SmdrClient
from .const import (
    CONF_EXTENSIONS,
    CONF_PHONEBOOK,
    DOMAIN,
    EVENT_CALL,
    EVENT_MISSED_CALL,
    RECENT_CALLS,
    SIGNAL_CALL,
    SIGNAL_UPDATE,
)
from .smdr import SmdrRecord, parse_line, parse_mapping

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.EVENT, Platform.SENSOR]


@dataclass
class NecPbxData:
    """Runtime state for one PBX."""

    client: SmdrClient
    extensions: dict[str, str]
    phonebook: dict[str, str]
    recent: deque[SmdrRecord] = field(default_factory=lambda: deque(maxlen=RECENT_CALLS))
    last_call: SmdrRecord | None = None
    last_missed: SmdrRecord | None = None
    last_by_station: dict[str, SmdrRecord] = field(default_factory=dict)
    last_raw: str | None = None
    unparsed_lines: int = 0


type NecPbxConfigEntry = ConfigEntry[NecPbxData]


def _options(entry: ConfigEntry) -> tuple[dict[str, str], dict[str, str]]:
    extensions = parse_mapping(entry.options.get(CONF_EXTENSIONS, ""))
    phonebook = parse_mapping(entry.options.get(CONF_PHONEBOOK, ""))
    return extensions, phonebook


async def async_setup_entry(hass: HomeAssistant, entry: NecPbxConfigEntry) -> bool:
    """Set up the PBX from a config entry."""
    extensions, phonebook = _options(entry)
    signal = SIGNAL_UPDATE.format(entry.entry_id)

    @callback
    def _on_state(_connected: bool) -> None:
        async_dispatcher_send(hass, signal)

    @callback
    def _on_line(line: str) -> None:
        data = entry.runtime_data
        data.last_raw = line
        record = parse_line(
            line,
            extensions=data.extensions,
            phonebook=data.phonebook,
            now=dt_util.now(),
        )
        if record is None:
            _LOGGER.debug("Ignored SMDR line (header or summary): %r", line)
            async_dispatcher_send(hass, signal)
            return
        if record.number is None and record.station is None and record.duration is None:
            data.unparsed_lines += 1
            _LOGGER.warning(
                "Could not read SMDR line %r; please report it with your diagnostics", line
            )
            async_dispatcher_send(hass, signal)
            return
        if record.start is None:
            record.start = dt_util.now()
        data.recent.appendleft(record)
        data.last_call = record
        if record.station:
            data.last_by_station[record.station] = record
        event_data = {"entry_id": entry.entry_id, **record.as_dict()}
        hass.bus.async_fire(EVENT_CALL, event_data)
        if record.missed:
            data.last_missed = record
            hass.bus.async_fire(EVENT_MISSED_CALL, event_data)
        async_dispatcher_send(hass, SIGNAL_CALL.format(entry.entry_id), record)
        async_dispatcher_send(hass, signal)

    client = SmdrClient(entry.data[CONF_HOST], entry.data[CONF_PORT], _on_line, _on_state)
    entry.runtime_data = NecPbxData(client=client, extensions=extensions, phonebook=phonebook)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    client.start()
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: NecPbxConfigEntry) -> None:
    """Reload so new extensions get their own sensors."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: NecPbxConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.client.stop()
    return unloaded


__all__ = ["DOMAIN", "NecPbxConfigEntry", "NecPbxData"]
