"""NEC PBX: call records from an NEC SL2100 / SV9100 phone system."""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, field
import logging
import re
from typing import Any

from aionecpbx.ami import DEFAULT_AMI_PORT, AmiClient, LiveCall
from aionecpbx.client import SmdrClient
from aionecpbx.smdr import (
    DATE_AUTO,
    DIRECTION_INCOMING,
    SmdrRecord,
    lookup_name,
    normalise_number,
    parse_line,
    parse_mapping,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    issue_registry as ir,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

try:  # Home Assistant 2026.10 moved its schemas to probatio.
    import probatio as vol
except ImportError:  # pragma: no cover - older Home Assistant
    import voluptuous as vol  # type: ignore[no-redef]

from .const import (
    CONF_AMI_HOST,
    CONF_AMI_PORT,
    CONF_AMI_SECRET,
    CONF_AMI_USER,
    CONF_DATE_ORDER,
    CONF_EXTENSIONS,
    CONF_LINES,
    CONF_PHONEBOOK,
    CONF_PHONEBOOK_TODO,
    DOMAIN,
    EVENT_CALL,
    EVENT_LIVE,
    EVENT_MISSED_CALL,
    EVENT_RINGING,
    HISTORY_CALLS,
    ISSUE_UNREACHABLE,
    LIVE_WINDOW,
    OUTAGE_ISSUE_AFTER,
    RECENT_CALLS,
    SEEN_LINES,
    SERVICE_SAVE_CALLER,
    SIGNAL_CALL,
    SIGNAL_LIVE,
    SIGNAL_NEW_RECORD,
    SIGNAL_UPDATE,
    STORAGE_VERSION,
)
from .entity import pbx_device_info

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CALENDAR,
    Platform.EVENT,
    Platform.SENSOR,
    Platform.SWITCH,
]


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
    lines: dict[str, str] = field(default_factory=dict)  # trunk number -> name
    # Every new call (not replays), oldest first, for the call history calendar.
    history: list[dict[str, Any]] = field(default_factory=list)
    ami: AmiClient | None = None
    last_live: LiveCall | None = None
    manual_phonebook: dict[str, str] = field(default_factory=dict)
    todo_phonebook: dict[str, str] = field(default_factory=dict)
    # Device registry id of the phone system, the parent of extensions and lines.
    pbx_device_id: str | None = None
    # The options this setup was loaded with, to tell what a later change touched.
    options: dict[str, Any] = field(default_factory=dict)


type NecPbxConfigEntry = ConfigEntry[NecPbxData]


def line_key(line: str) -> str:
    """The same call printed twice (live, then replayed) gives the same key."""
    return " ".join(line.split()).upper()


def _newer(record: SmdrRecord, current: SmdrRecord | None) -> bool:
    if current is None or current.start is None or record.start is None:
        return True
    return record.start >= current.start


_RE_PHONE = re.compile(r"\+?\d[\d ()-]{5,}\d")

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def parse_todo_items(items: list[dict[str, Any]]) -> dict[str, str]:
    """Phonebook entries from to-do items: "Alex" with "0491 570 156" in the
    description, or "Alex 0491 570 156" / "Alex: 0491 570 156" as the item itself."""
    book: dict[str, str] = {}
    for item in items:
        summary = str(item.get("summary") or "").strip()
        description = str(item.get("description") or "").strip()
        name = summary
        match = _RE_PHONE.search(description)
        if match is None:
            match = _RE_PHONE.search(summary)
            if match is None:
                continue
            name = summary.replace(match.group(0), "")
        name = name.strip(" :-,\t")
        if name:
            book[normalise_number(match.group(0))] = name
    return book


def _merge_phonebook(data: NecPbxData) -> None:
    """The options' phonebook wins over the to-do list for the same number."""
    data.phonebook = {**data.todo_phonebook, **data.manual_phonebook}


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the save-caller action."""

    async def save_caller(call: ServiceCall) -> ServiceResponse:
        entries = list(hass.config_entries.async_loaded_entries(DOMAIN))
        if entry_id := call.data.get("config_entry_id"):
            entries = [e for e in entries if e.entry_id == entry_id]
        if not entries:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_set_up")
        entry: NecPbxConfigEntry = entries[0]
        data = entry.runtime_data
        number: str | None = call.data.get("number")
        if not number:
            last = next(
                (r for r in data.recent if r.direction == DIRECTION_INCOMING and r.number), None
            )
            if last is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="no_caller_yet"
                )
            number = str(last.number)
        if number.upper().endswith("X"):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="number_hidden",
                translation_placeholders={"number": number},
            )
        name = call.data["name"].strip()
        todo = entry.options.get(CONF_PHONEBOOK_TODO)
        if todo:
            await hass.services.async_call(
                "todo",
                "add_item",
                {"entity_id": todo, "item": name, "description": number},
                blocking=True,
            )
        else:
            text = entry.options.get(CONF_PHONEBOOK, "")
            line = f"{normalise_number(number)}: {name}"
            hass.config_entries.async_update_entry(
                entry, options={**entry.options, CONF_PHONEBOOK: f"{text}\n{line}".strip()}
            )
        key = normalise_number(number)
        if todo:
            data.todo_phonebook[key] = name  # the list's own update refreshes it too
        else:
            data.manual_phonebook[key] = name  # saved in the options too; no reload needed
        _merge_phonebook(data)
        return {"name": name, "number": number}

    hass.services.async_register(
        DOMAIN,
        SERVICE_SAVE_CALLER,
        save_caller,
        schema=vol.Schema(
            {
                vol.Required("name"): cv.string,
                vol.Optional("number"): cv.string,
                vol.Optional("config_entry_id"): cv.string,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


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
    store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.seen")
    stored = await store.async_load() or {}
    seen: OrderedDict[str, None] = OrderedDict.fromkeys(stored.get("lines", [])[-SEEN_LINES:])
    history: list[dict[str, Any]] = list(stored.get("history", []))[-HISTORY_CALLS:]

    @callback
    def _seen_data() -> dict[str, Any]:
        data = entry.runtime_data
        return {"lines": list(data.seen), "history": data.history[-HISTORY_CALLS:]}

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
            # The raw line can hold phone numbers: only at debug level, and masked in diagnostics.
            _LOGGER.warning(
                "Could not read an SMDR line; please report it with your diagnostics, which "
                "include it with the numbers masked"
            )
            _LOGGER.debug("Unreadable SMDR line: %r", line)
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
            data.history.append(record.as_dict())
            del data.history[:-HISTORY_CALLS]
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
        lines=parse_mapping(entry.options.get(CONF_LINES, "")),
        history=history,
        manual_phonebook=dict(phonebook),
        options=dict(entry.options),
    )
    # Register the phone system first, so extensions and lines can name it
    # as their parent by device id (Home Assistant 2026.10 and later).
    entry.runtime_data.pbx_device_id = (
        dr.async_get(hass)
        .async_get_or_create(config_entry_id=entry.entry_id, **pbx_device_info(entry))
        .id
    )

    if todo_entity := entry.options.get(CONF_PHONEBOOK_TODO):

        async def _load_todo(_event: Event[EventStateChangedData] | None = None) -> None:
            if hass.states.get(todo_entity) is None:
                return  # the list isn't loaded yet; its first state change brings us back
            try:
                response = await hass.services.async_call(
                    "todo",
                    "get_items",
                    {"entity_id": todo_entity, "status": ["needs_action", "completed"]},
                    blocking=True,
                    return_response=True,
                )
            except (HomeAssistantError, vol.Invalid) as err:
                _LOGGER.warning("Couldn't read the phonebook list %s: %s", todo_entity, err)
                return
            result = (response or {}).get(todo_entity)
            raw = result.get("items") if isinstance(result, dict) else None
            items = [i for i in raw if isinstance(i, dict)] if isinstance(raw, list) else []
            data = entry.runtime_data
            data.todo_phonebook = parse_todo_items(items)
            _merge_phonebook(data)
            _LOGGER.debug("Phonebook: %d entries from %s", len(data.todo_phonebook), todo_entity)
            async_dispatcher_send(hass, signal)

        entry.async_on_unload(async_track_state_change_event(hass, [todo_entity], _load_todo))
        entry.async_create_background_task(hass, _load_todo(), "nec_pbx phonebook")

    if entry.options.get(CONF_AMI_HOST):

        @callback
        def _on_live(call: LiveCall, change: str) -> None:
            data = entry.runtime_data
            data.last_live = call
            name = call.caller_name or lookup_name(call.caller_number or "", data.phonebook)
            book_name = lookup_name(call.caller_number or "", data.phonebook)
            event_data = {
                "entry_id": entry.entry_id,
                "change": change,
                "number": call.caller_number,
                "caller_name": book_name or name,
                "extension": call.extension,
                "station_name": data.extensions.get(call.extension or ""),
            }
            hass.bus.async_fire(EVENT_LIVE, event_data)
            if change == "ringing":
                hass.bus.async_fire(EVENT_RINGING, event_data)
            async_dispatcher_send(hass, SIGNAL_LIVE.format(entry.entry_id), event_data)
            async_dispatcher_send(hass, signal)

        @callback
        def _on_ami_state(_connected: bool) -> None:
            async_dispatcher_send(hass, signal)

        @callback
        def _on_ami_auth_failed(_message: str) -> None:
            # Ask for the FreePBX login again; the call log carries on meanwhile.
            entry.async_start_reauth(hass)
            async_dispatcher_send(hass, signal)

        ami = AmiClient(
            entry.options[CONF_AMI_HOST],
            int(entry.options.get(CONF_AMI_PORT) or DEFAULT_AMI_PORT),
            entry.options.get(CONF_AMI_USER, ""),
            entry.options.get(CONF_AMI_SECRET, ""),
            _on_live,
            _on_ami_state,
            _on_ami_auth_failed,
        )
        entry.runtime_data.ami = ami

    @callback
    def _save_now() -> None:
        hass.async_create_task(store.async_save(_seen_data()))

    entry.async_on_unload(_save_now)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    client.start()
    if entry.runtime_data.ami:
        entry.runtime_data.ami.start()
    _watch_outage(False)  # starts the clock until the first connection
    entry.async_on_unload(_stop_watching)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: NecPbxConfigEntry) -> None:
    """Reload so new extensions get their own sensors. A phonebook change on its
    own (such as the save_caller action) is applied in place, without a reload."""
    data = entry.runtime_data
    changed = {
        key
        for key in entry.options.keys() | data.options.keys()
        if entry.options.get(key) != data.options.get(key)
    }
    if changed == {CONF_PHONEBOOK}:
        data.options = dict(entry.options)
        data.manual_phonebook = parse_mapping(entry.options.get(CONF_PHONEBOOK, ""))
        _merge_phonebook(data)
        async_dispatcher_send(hass, SIGNAL_UPDATE.format(entry.entry_id))
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: NecPbxConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.client.stop()
        if entry.runtime_data.ami:
            await entry.runtime_data.ami.stop()
    return unloaded


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: NecPbxConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Let an extension or line that's no longer in the options be deleted."""
    data = entry.runtime_data
    current = {(DOMAIN, entry.entry_id)}
    current |= {(DOMAIN, f"{entry.entry_id}_extension_{ext}") for ext in data.extensions}
    current |= {(DOMAIN, f"{entry.entry_id}_line_{trunk}") for trunk in data.lines}
    return not device.identifiers & current


__all__ = ["DOMAIN", "NecPbxConfigEntry", "NecPbxData"]
