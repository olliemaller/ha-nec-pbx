"""Call sensors for NEC PBX."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from . import NecPbxConfigEntry
from .entity import NecPbxEntity
from .smdr import SmdrRecord

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


def _attrs(record: SmdrRecord | None) -> dict[str, Any]:
    if record is None:
        return {}
    data = record.as_dict()
    return {key: data[key] for key in _RECORD_ATTRS}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NecPbxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add call sensors, plus one 'last call' sensor per named extension."""
    entities: list[SensorEntity] = [
        LastCallSensor(entry, "last_call"),
        LastCallSensor(entry, "last_missed_call"),
        CallCountSensor(entry, "calls_today", missed_only=False),
        CallCountSensor(entry, "missed_calls_today", missed_only=True),
        RecentCallsSensor(entry),
        LastLineSensor(entry),
    ]
    entities.extend(
        StationLastCallSensor(entry, ext, name)
        for ext, name in entry.runtime_data.extensions.items()
    )
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
        self._attr_icon = "mdi:phone-missed" if key == "last_missed_call" else "mdi:phone-log"

    def _record(self) -> SmdrRecord | None:
        return self.data.last_missed if self._key == "last_missed_call" else self.data.last_call


class StationLastCallSensor(_RestoringTimestamp):
    """Last call on one extension (room)."""

    _attr_icon = "mdi:phone-classic"

    def __init__(self, entry: NecPbxConfigEntry, ext: str, name: str) -> None:
        super().__init__(entry, f"station_{ext}_last_call")
        self._ext = ext
        self._attr_translation_key = "station_last_call"
        self._attr_translation_placeholders = {"station": name or ext}

    def _record(self) -> SmdrRecord | None:
        return self.data.last_by_station.get(self._ext)


class CallCountSensor(NecPbxEntity, RestoreSensor):
    """Calls (or missed calls) since midnight."""

    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "calls"

    def __init__(self, entry: NecPbxConfigEntry, key: str, *, missed_only: bool) -> None:
        super().__init__(entry, key)
        self._attr_translation_key = key
        self._attr_icon = "mdi:phone-missed" if missed_only else "mdi:phone"
        self._missed_only = missed_only
        self._count = 0
        self._seen: SmdrRecord | None = None
        self._attr_last_reset = dt_util.start_of_local_day()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            restored = await self.async_get_last_state()
            last_reset = (
                dt_util.parse_datetime(restored.attributes.get("last_reset", ""))
                if restored
                else None
            )
            if last_reset and last_reset >= dt_util.start_of_local_day():
                self._count = int(last.native_value or 0)
        self.async_on_remove(async_track_time_change(self.hass, self._midnight, 0, 0, 0))

    @callback
    def _midnight(self, _now: datetime) -> None:
        self._count = 0
        self._attr_last_reset = dt_util.start_of_local_day()
        self.async_write_ha_state()

    @callback
    def _handle_update(self) -> None:
        record = self.data.last_call
        if record is not None and record is not self._seen:
            self._seen = record
            if not self._missed_only or record.missed:
                self._count += 1
        super()._handle_update()

    @property
    def native_value(self) -> int:
        return self._count


class RecentCallsSensor(NecPbxEntity, SensorEntity):
    """How many calls are in the recent list; the list itself is an attribute."""

    _attr_translation_key = "recent_calls"
    _attr_icon = "mdi:format-list-bulleted"

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
    _attr_icon = "mdi:text-long"

    def __init__(self, entry: NecPbxConfigEntry) -> None:
        super().__init__(entry, "last_smdr_line")

    @property
    def native_value(self) -> str | None:
        raw = self.data.last_raw
        return raw[:255] if raw else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"unreadable_lines": self.data.unparsed_lines}
