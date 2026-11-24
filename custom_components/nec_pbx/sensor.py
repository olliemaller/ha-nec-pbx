"""Call sensors for NEC PBX."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from aionecpbx.ami import LiveCall
from aionecpbx.smdr import DIRECTION_INCOMING, SmdrRecord
from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from . import NecPbxConfigEntry
from .const import SIGNAL_NEW_RECORD
from .entity import NecPbxEntity

# Entities are pushed updates; nothing is polled or sent per entity.
PARALLEL_UPDATES = 0

_RECORD_ATTRS = (
    "direction",
    "number",
    "caller_name",
    "station",
    "station_name",
    "duration",
    "ring_time",
    "trunk",
    "answered",
    "missed",
)

DAY = "day"
WEEK = "week"
MONTH = "month"

Filter = Callable[[SmdrRecord], bool]


def _attrs(record: SmdrRecord | None) -> dict[str, Any]:
    if record is None:
        return {}
    data = record.as_dict()
    return {key: data[key] for key in _RECORD_ATTRS}


def period_start(period: str, now: datetime | None = None) -> datetime:
    """Start of the current day, week (Monday) or month, local time."""
    start = dt_util.start_of_local_day(now)
    if period == WEEK:
        start -= timedelta(days=start.weekday())
        start = dt_util.start_of_local_day(start)
    elif period == MONTH:
        start = dt_util.start_of_local_day(start.replace(day=1))
    return start


def _any(_record: SmdrRecord) -> bool:
    return True


def _missed(record: SmdrRecord) -> bool:
    return record.missed


def _unknown_caller(record: SmdrRecord) -> bool:
    return record.direction == DIRECTION_INCOMING and bool(record.number) and not record.caller_name


def _count(_record: SmdrRecord) -> int:
    return 1


def _talk(record: SmdrRecord) -> int:
    return (record.duration or 0) if record.answered else 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NecPbxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add call sensors, a device per named extension and per named line."""
    data = entry.runtime_data
    entities: list[SensorEntity] = [
        LastCallSensor(entry, "last_call"),
        LastCallSensor(entry, "last_missed_call"),
        CallCountSensor(entry, "calls_today", DAY, _any),
        CallCountSensor(entry, "missed_calls_today", DAY, _missed),
        TalkTimeSensor(entry, "talk_time_today", DAY, _any),
        CallCountSensor(entry, "calls_this_week", WEEK, _any),
        CallCountSensor(entry, "missed_calls_this_week", WEEK, _missed),
        TalkTimeSensor(entry, "talk_time_this_week", WEEK, _any),
        CallCountSensor(entry, "calls_this_month", MONTH, _any),
        CallCountSensor(entry, "missed_calls_this_month", MONTH, _missed),
        TalkTimeSensor(entry, "talk_time_this_month", MONTH, _any),
        LongestCallSensor(entry),
        CallCountSensor(entry, "unknown_callers_today", DAY, _unknown_caller),
        RecentCallsSensor(entry),
        LastLineSensor(entry),
    ]
    for ext, name in data.extensions.items():
        device = ("extension", ext, name)

        def on_ext(record: SmdrRecord, ext: str = ext) -> bool:
            return record.station == ext

        entities += [
            StationLastCallSensor(entry, ext, name),
            CallCountSensor(
                entry, f"station_{ext}_calls_today", DAY, on_ext, device, "extension_calls_today"
            ),
            TalkTimeSensor(
                entry,
                f"station_{ext}_talk_time_today",
                DAY,
                on_ext,
                device,
                "extension_talk_time_today",
            ),
        ]
    for trunk, name in data.lines.items():
        device = ("line", trunk, name)

        def on_line(record: SmdrRecord, trunk: str = trunk) -> bool:
            return record.trunk == trunk

        entities += [
            LineLastCallSensor(entry, trunk, name),
            CallCountSensor(
                entry, f"line_{trunk}_calls_today", DAY, on_line, device, "line_calls_today"
            ),
        ]
    if data.ami is not None:
        entities.append(CurrentCallerSensor(entry))
    async_add_entities(entities)


class _RestoringTimestamp(NecPbxEntity, RestoreSensor):
    """Timestamp sensor that keeps its value and attributes over a restart."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _restored_attrs: dict[str, Any]

    def _record(self) -> SmdrRecord | None:
        raise NotImplementedError

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._restored_attrs = {}
        self._restored_value: datetime | None = None
        if (state := await self.async_get_last_state()) is not None:
            self._restored_value = dt_util.parse_datetime(state.state)
            self._restored_attrs = {k: v for k, v in state.attributes.items() if k in _RECORD_ATTRS}

    @property
    def native_value(self) -> datetime | None:
        record = self._record()
        if record is not None:
            return record.start
        return getattr(self, "_restored_value", None)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        record = self._record()
        if record is not None:
            return _attrs(record)
        return getattr(self, "_restored_attrs", {})


class LastCallSensor(_RestoringTimestamp):
    """Time of the last call (or last missed call), with its details."""

    def __init__(self, entry: NecPbxConfigEntry, key: str) -> None:
        super().__init__(entry, key)
        self._key = key
        self._attr_translation_key = key

    def _record(self) -> SmdrRecord | None:
        return self.data.last_missed if self._key == "last_missed_call" else self.data.last_call


class StationLastCallSensor(_RestoringTimestamp):
    """Last call on one extension (room), on that extension's own device."""

    _attr_translation_key = "extension_last_call"

    def __init__(self, entry: NecPbxConfigEntry, ext: str, name: str) -> None:
        super().__init__(entry, f"station_{ext}_last_call", sub_device=("extension", ext, name))
        self._ext = ext

    def _record(self) -> SmdrRecord | None:
        return self.data.last_by_station.get(self._ext)


class LineLastCallSensor(_RestoringTimestamp):
    """Last call on one outside line (trunk), on that line's own device."""

    _attr_translation_key = "line_last_call"

    def __init__(self, entry: NecPbxConfigEntry, trunk: str, name: str) -> None:
        super().__init__(entry, f"line_{trunk}_last_call", sub_device=("line", trunk, name))
        self._trunk = trunk
        self._last: SmdrRecord | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_NEW_RECORD.format(self._entry.entry_id), self._new_record
            )
        )

    @callback
    def _new_record(self, record: SmdrRecord) -> None:
        if record.trunk == self._trunk:
            self._last = record
            self.async_write_ha_state()

    def _record(self) -> SmdrRecord | None:
        return self._last


class _PeriodTotal(NecPbxEntity, RestoreSensor):
    """A total for the current day, week or month that survives restarts.

    Only calls seen for the first time arrive here (never the phone system's
    replays), filtered by ``matches`` (an extension, a line, missed...)."""

    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        entry: NecPbxConfigEntry,
        key: str,
        period: str,
        matches: Filter,
        sub_device: tuple[str, str, str] | None = None,
        translation_key: str | None = None,
    ) -> None:
        super().__init__(entry, key, sub_device=sub_device)
        self._attr_translation_key = translation_key or key
        self._period = period
        self._matches = matches
        self._total = 0
        self._attr_last_reset = period_start(period)

    def _amount(self, record: SmdrRecord) -> int:
        raise NotImplementedError

    def _combine(self, total: int, amount: int) -> int:
        return total + amount

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            restored = await self.async_get_last_state()
            last_reset = (
                dt_util.parse_datetime(restored.attributes.get("last_reset", ""))
                if restored
                else None
            )
            if last_reset and last_reset >= period_start(self._period):
                self._total = int(float(str(last.native_value or 0)))
        self.async_on_remove(async_track_time_change(self.hass, self._midnight, 0, 0, 0))
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_NEW_RECORD.format(self._entry.entry_id), self._new_record
            )
        )

    @callback
    def _midnight(self, _now: datetime) -> None:
        start = period_start(self._period)
        if start != self._attr_last_reset:
            self._total = 0
            self._attr_last_reset = start
            self.async_write_ha_state()

    @callback
    def _new_record(self, record: SmdrRecord) -> None:
        """Count a call the first time it is seen; replays never arrive here."""
        if record.start is not None and record.start < period_start(self._period):
            return
        if not self._matches(record):
            return
        amount = self._amount(record)
        if amount:
            self._total = self._combine(self._total, amount)
            self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        return self._total


class CallCountSensor(_PeriodTotal):
    """Calls (missed, unknown, on one extension or line...) this day, week or month."""

    _attr_native_unit_of_measurement = "calls"

    def _amount(self, record: SmdrRecord) -> int:
        return _count(record)


class TalkTimeSensor(_PeriodTotal):
    """Time spent on answered calls this day, week or month."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_suggested_unit_of_measurement = UnitOfTime.MINUTES
    _attr_suggested_display_precision = 0

    def _amount(self, record: SmdrRecord) -> int:
        return _talk(record)


class LongestCallSensor(TalkTimeSensor):
    """The longest answered call today."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry: NecPbxConfigEntry) -> None:
        super().__init__(entry, "longest_call_today", DAY, _any)

    def _combine(self, total: int, amount: int) -> int:
        return max(total, amount)

    @property
    def last_reset(self) -> None:  # measurements have no last_reset
        return None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # No last_reset on a measurement: keep the value if it was set today.
        restored = await self.async_get_last_state()
        last = await self.async_get_last_sensor_data()
        if (
            restored is not None
            and last is not None
            and last.native_value is not None
            and dt_util.as_local(restored.last_changed) >= period_start(DAY)
        ):
            self._total = int(float(str(last.native_value)))


class RecentCallsSensor(NecPbxEntity, SensorEntity):
    """How many calls are in the recent list; the list itself is an attribute."""

    _attr_translation_key = "recent_calls"
    # The list changes with every call; keep it out of the recorder database.
    _unrecorded_attributes = frozenset({"calls"})

    def __init__(self, entry: NecPbxConfigEntry) -> None:
        super().__init__(entry, "recent_calls")

    @property
    def native_value(self) -> int:
        return len(self.data.recent)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "calls": [
                {"start": r.start.isoformat() if r.start else None, **_attrs(r)}
                for r in self.data.recent
            ]
        }


class LastLineSensor(NecPbxEntity, SensorEntity):
    """The last raw SMDR line, for checking the parser against your system."""

    _attr_translation_key = "last_smdr_line"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    # The raw line holds callers' numbers; turn it on only to check the parser.
    _attr_entity_registry_enabled_default = False
    _unrecorded_attributes = frozenset({"unreadable_lines", "repeated_lines", "unnamed_extensions"})

    def __init__(self, entry: NecPbxConfigEntry) -> None:
        super().__init__(entry, "last_smdr_line")

    @property
    def native_value(self) -> str | None:
        raw = self.data.last_raw
        return raw[:255] if raw else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "unreadable_lines": self.data.unparsed_lines,
            # Calls the phone system printed again (replayed on reconnect); not counted twice.
            "repeated_lines": self.data.replayed_lines,
            # Extensions seen in calls with no name in the options yet.
            "unnamed_extensions": sorted(self.data.unnamed_stations),
        }


class CurrentCallerSensor(NecPbxEntity, SensorEntity):
    """Who is ringing right now (from FreePBX), or "none"."""

    _attr_translation_key = "current_caller"

    def __init__(self, entry: NecPbxConfigEntry) -> None:
        super().__init__(entry, "current_caller")

    @property
    def available(self) -> bool:
        return self.data.ami is not None and self.data.ami.connected

    def _call(self) -> LiveCall | None:
        ami = self.data.ami
        calls = (ami.ringing or ami.active) if ami else []
        return calls[-1] if calls else None

    @property
    def native_value(self) -> str:
        from aionecpbx.smdr import lookup_name

        call = self._call()
        if call is None:
            return "none"
        return (
            lookup_name(call.caller_number or "", self.data.phonebook)
            or call.caller_name
            or call.caller_number
            or "unknown"
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        call = self._call()
        if call is None:
            return {}
        return {
            "number": call.caller_number,
            "extension": call.extension,
            "station_name": self.data.extensions.get(call.extension or ""),
            "state": call.state,
        }
