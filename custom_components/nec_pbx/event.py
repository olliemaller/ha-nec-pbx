"""Call event entity for NEC PBX: one event per finished call."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NecPbxConfigEntry
from .const import SIGNAL_CALL, SIGNAL_LIVE
from .entity import NecPbxEntity
from .smdr import (
    DIRECTION_INCOMING,
    DIRECTION_INTERNAL,
    DIRECTION_OUTGOING,
    SmdrRecord,
)

# Entities are pushed updates; nothing is polled or sent per entity.
PARALLEL_UPDATES = 0

EVENT_INCOMING = "incoming"
EVENT_MISSED = "missed"
EVENT_OUTGOING = "outgoing"
EVENT_INTERNAL = "internal"
EVENT_OTHER = "other"

EVENT_TYPES = [EVENT_INCOMING, EVENT_MISSED, EVENT_OUTGOING, EVENT_INTERNAL, EVENT_OTHER]

_BY_DIRECTION = {
    DIRECTION_INCOMING: EVENT_INCOMING,
    DIRECTION_OUTGOING: EVENT_OUTGOING,
    DIRECTION_INTERNAL: EVENT_INTERNAL,
}

# Call details passed with each event; the raw line stays in the diagnostics and events.
_ATTRIBUTES = (
    "start",
    "number",
    "caller_name",
    "station",
    "station_name",
    "duration",
    "ring_time",
    "trunk",
    "answered",
)


def event_type_for(record: SmdrRecord) -> str:
    """Pick the event type for a call: missed wins over incoming."""
    if record.missed:
        return EVENT_MISSED
    return _BY_DIRECTION.get(record.direction, EVENT_OTHER)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NecPbxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the call event entity, one per named extension, and the live one."""
    entities: list[EventEntity] = [NecPbxCallEvent(entry)]
    entities += [
        NecPbxCallEvent(entry, ext, name) for ext, name in entry.runtime_data.extensions.items()
    ]
    if entry.runtime_data.ami is not None:
        entities.append(NecPbxLiveCallEvent(entry))
    async_add_entities(entities)


class NecPbxCallEvent(NecPbxEntity, EventEntity):
    """Fires once for every finished call, typed incoming, missed, outgoing or internal."""

    _attr_event_types = EVENT_TYPES
    _attr_translation_key = "call"

    def __init__(self, entry: NecPbxConfigEntry, ext: str | None = None, name: str = "") -> None:
        if ext is None:
            super().__init__(entry, "call_event")
        else:
            super().__init__(
                entry, f"station_{ext}_call_event", sub_device=("extension", ext, name)
            )
        self._ext = ext

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_CALL.format(self._entry.entry_id), self._handle_call
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Connection changes don't create events; only calls do."""

    @callback
    def _handle_call(self, record: SmdrRecord) -> None:
        if self._ext is not None and record.station != self._ext:
            return
        details = record.as_dict()
        self._trigger_event(event_type_for(record), {k: details[k] for k in _ATTRIBUTES})
        self.async_write_ha_state()


LIVE_TYPES = ["ringing", "answered", "ended"]


class NecPbxLiveCallEvent(NecPbxEntity, EventEntity):
    """Live calls from FreePBX: ringing (with caller ID), answered and ended."""

    _attr_event_types = LIVE_TYPES
    _attr_translation_key = "live_call"

    def __init__(self, entry: NecPbxConfigEntry) -> None:
        super().__init__(entry, "live_call_event")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_LIVE.format(self._entry.entry_id), self._handle_live
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Only live call changes create events."""

    @callback
    def _handle_live(self, data: dict) -> None:
        self._trigger_event(
            data["change"],
            {k: data.get(k) for k in ("number", "caller_name", "extension", "station_name")},
        )
        self.async_write_ha_state()
