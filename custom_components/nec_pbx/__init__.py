"""NEC PBX: call records from an NEC SL2100 / SV9100 phone system."""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, field
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .client import SmdrClient
from .const import (
    CONF_DATE_ORDER,
    CONF_EXTENSIONS,
    CONF_PHONEBOOK,
    DOMAIN,
    EVENT_CALL,
    EVENT_MISSED_CALL,
    ISSUE_UNREACHABLE,
    LIVE_WINDOW,
    OUTAGE_ISSUE_AFTER,
    RECENT_CALLS,
    SEEN_LINES,
    SIGNAL_CALL,
    SIGNAL_NEW_RECORD,
    SIGNAL_UPDATE,
    STORAGE_VERSION,
)
from .smdr import DATE_AUTO, SmdrRecord, parse_line, parse_mapping

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
    date_order: str = DATE_AUTO
    # Lines already counted (normalised), oldest first; saved across restarts.
    seen: OrderedDict[str, None] = field(default_factory=OrderedDict)
    replayed_lines: int = 0
    # Extensions that made or took calls but have no name in the options.
    unnamed_stations: set[str] = field(default_factory=set)


type NecPbxConfigEntry = ConfigEntry[NecPbxData]


def line_key(line: str) -> str:
    """The same call printed twice (live, then replayed) gives the same key."""
    return " ".join(line.split()).upper()


def _newer(record: SmdrRecord, current: SmdrRecord | None) -> bool:
    if current is None or current.start is None or record.start is None:
        return True
    return record.start >= current.start


def _options(entry: ConfigEntry) -> tuple[dict[str, str], dict[str, str]]:
    extensions = parse_mapping(entry.options.get(CONF_EXTENSIONS, ""))
    phonebook = parse_mapping(entry.options.get(CONF_PHONEBOOK, ""))
    return extensions, phonebook


async def async_setup_entry(hass: HomeAssistant, entry: NecPbxConfigEntry) -> bool:
    """Set up the PBX from a config entry."""
    extensions, phonebook = _options(entry)
    signal = SIGNAL_UPDATE.format(entry.entry_id)
    issue_id = ISSUE_UNREACHABLE.format(entry.entry_id)
    outage_timer: CALLBACK_TYPE | None = None
    store: Store[dict[str, list[str]]] = Store(
        hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.seen"
    )
    stored = await store.async_load() or {}
    seen: OrderedDict[str, None] = OrderedDict.fromkeys(stored.get("lines", [])[-SEEN_LINES:])

    @callback
    def _seen_data() -> dict[str, list[str]]:
        return {"lines": list(entry.runtime_data.seen)}

    @callback
    def _raise_outage_issue(_now: object) -> None:
        nonlocal outage_timer
        outage_timer = None
        client = entry.runtime_data.client
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="call_log_unreachable",
            translation_placeholders={
                "name": entry.title,
                "address": f"{client.host}:{client.port}",
                "error": client.last_error or "no answer",
            },
        )

    @callback
    def _watch_outage(connected: bool) -> None:
        """Repairs issue after a long outage; cleared as soon as the call log is back."""
        nonlocal outage_timer
        if connected:
            if outage_timer:
                outage_timer()
                outage_timer = None
            ir.async_delete_issue(hass, DOMAIN, issue_id)
        elif outage_timer is None:
            outage_timer = async_call_later(
                hass, OUTAGE_ISSUE_AFTER.total_seconds(), _raise_outage_issue
            )

    @callback
    def _stop_watching() -> None:
        nonlocal outage_timer
        if outage_timer:
            outage_timer()
            outage_timer = None
        ir.async_delete_issue(hass, DOMAIN, issue_id)

    @callback
    def _on_state(connected: bool) -> None:
        _watch_outage(connected)
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
            date_order=data.date_order,
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
        key = line_key(line)
        first_time = key not in data.seen
        if first_time:
            data.seen[key] = None
            while len(data.seen) > SEEN_LINES:
                data.seen.popitem(last=False)
            store.async_delay_save(_seen_data, 10)
        else:
            data.replayed_lines += 1
        if not any(line_key(r.raw) == key for r in data.recent):
            data.recent.appendleft(record)
            data.recent = deque(
                sorted(data.recent, key=lambda r: r.start or dt_util.now(), reverse=True),
                maxlen=RECENT_CALLS,
            )
        if _newer(record, data.last_call):
            data.last_call = record
        if record.station:
            if _newer(record, data.last_by_station.get(record.station)):
                data.last_by_station[record.station] = record
            if record.station not in data.extensions:
                data.unnamed_stations.add(record.station)
        if record.missed and _newer(record, data.last_missed):
            data.last_missed = record
        if first_time:
            async_dispatcher_send(hass, SIGNAL_NEW_RECORD.format(entry.entry_id), record)
        if first_time and record.is_live(dt_util.now(), LIVE_WINDOW):
            event_data = {"entry_id": entry.entry_id, **record.as_dict()}
            hass.bus.async_fire(EVENT_CALL, event_data)
            if record.missed:
                hass.bus.async_fire(EVENT_MISSED_CALL, event_data)
            async_dispatcher_send(hass, SIGNAL_CALL.format(entry.entry_id), record)
        else:
            _LOGGER.debug("Stored or repeated call, no event: %r", line)
        async_dispatcher_send(hass, signal)

    client = SmdrClient(entry.data[CONF_HOST], entry.data[CONF_PORT], _on_line, _on_state)
    entry.runtime_data = NecPbxData(
        client=client,
        extensions=extensions,
        phonebook=phonebook,
        date_order=entry.options.get(CONF_DATE_ORDER, DATE_AUTO),
        seen=seen,
    )

    @callback
    def _save_now() -> None:
        hass.async_create_task(store.async_save(_seen_data()))

    entry.async_on_unload(_save_now)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    client.start()
    _watch_outage(False)  # starts the clock until the first connection
    entry.async_on_unload(_stop_watching)
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
