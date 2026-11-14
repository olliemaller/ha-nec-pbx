"""Connection status for NEC PBX."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NecPbxConfigEntry
from .entity import NecPbxEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NecPbxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the connection sensor."""
    async_add_entities([NecPbxConnection(entry)])


class NecPbxConnection(NecPbxEntity, BinarySensorEntity):
    """On while Home Assistant holds the SMDR connection."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "call_log"
    # These change with every line; keep them out of the recorder database.
    _unrecorded_attributes = frozenset({"lines_received", "last_error"})

    def __init__(self, entry: NecPbxConfigEntry) -> None:
        super().__init__(entry, "connection")

    @property
    def is_on(self) -> bool:
        return self.data.client.connected

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        client = self.data.client
        return {"lines_received": client.lines_received, "last_error": client.last_error}
