"""Call event entity for NEC PBX: one event per finished call."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NecPbxConfigEntry
from .const import SIGNAL_CALL
from .entity import NecPbxEntity
from .smdr import (
    DIRECTION_INCOMING,
    DIRECTION_INTERNAL,
    DIRECTION_OUTGOING,
    SmdrRecord,
)

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
    """Add the call event entity."""
    async_add_entities([NecPbxCallEvent(entry)])


class NecPbxCallEvent(NecPbxEntity, EventEntity):
    """Fires once for every finished call, typed incoming, missed, outgoing or internal."""

    _attr_event_types = EVENT_TYPES
    _attr_translation_key = "call"

    def __init__(self, entry: NecPbxConfigEntry) -> None:
        super().__init__(entry, "call_event")

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
        details = record.as_dict()
        self._trigger_event(event_type_for(record), {k: details[k] for k in _ATTRIBUTES})
        self.async_write_ha_state()
