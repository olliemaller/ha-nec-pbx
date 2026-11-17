"""Call history calendar: every call as an entry, kept across restarts (last 500)."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import NecPbxConfigEntry
from .const import SIGNAL_NEW_RECORD
from .entity import NecPbxEntity
from .logbook import describe_call

PARALLEL_UPDATES = 0
_MIN_LENGTH = timedelta(minutes=1)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NecPbxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([NecPbxCallHistory(entry)])


def _event(call: dict) -> CalendarEvent | None:
    start = dt_util.parse_datetime(call.get("start") or "")
    if start is None:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=dt_util.get_default_time_zone())
    length = timedelta(seconds=(call.get("ring_time") or 0) + (call.get("duration") or 0))
    summary = describe_call(call)
    return CalendarEvent(
        start=start,
        end=start + max(length, _MIN_LENGTH),
        summary=summary[:1].upper() + summary[1:],
        description=call.get("raw"),
        location=call.get("station_name") or call.get("station"),
    )


class NecPbxCallHistory(NecPbxEntity, CalendarEntity):
    """Calls on a calendar, for a day or week view of who rang and when."""

    _attr_translation_key = "call_history"

    def __init__(self, entry: NecPbxConfigEntry) -> None:
        super().__init__(entry, "call_history")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_NEW_RECORD.format(self._entry.entry_id), self._new_call
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Connection changes don't change the calendar."""

    @callback
    def _new_call(self, _record) -> None:
        self.async_write_ha_state()

    def _events(self) -> list[CalendarEvent]:
        return [e for e in (_event(c) for c in self.data.history) if e is not None]

    @property
    def event(self) -> CalendarEvent | None:
        events = self._events()
        return events[-1] if events else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return [e for e in self._events() if e.end > start_date and e.start < end_date]
