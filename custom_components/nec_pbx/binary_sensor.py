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

# Entities are pushed updates; nothing is polled or sent per entity.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NecPbxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the connection sensor, and live call sensors when FreePBX is set up."""
    entities: list[BinarySensorEntity] = [NecPbxConnection(entry)]
    if entry.runtime_data.ami is not None:
        entities += [
            NecPbxRinging(entry),
            NecPbxRinging(entry, answered=True),
            NecPbxAmiConnection(entry),
        ]
    async_add_entities(entities)


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


class NecPbxRinging(NecPbxEntity, BinarySensorEntity):
    """On while a call is ringing (from FreePBX), with who's calling."""

    _attr_translation_key = "ringing"

    def __init__(self, entry: NecPbxConfigEntry, *, answered: bool = False) -> None:
        super().__init__(entry, "on_a_call" if answered else "ringing")
        self._answered = answered
        if answered:
            self._attr_translation_key = "on_a_call"

    @property
    def available(self) -> bool:
        return self.data.ami is not None and self.data.ami.connected

    def _calls(self):
        ami = self.data.ami
        if ami is None:
            return []
        return ami.active if self._answered else ami.ringing

    @property
    def is_on(self) -> bool:
        return bool(self._calls())

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        from aionecpbx.smdr import lookup_name

        calls = self._calls()
        if not calls:
            return {}
        call = calls[-1]
        return {
            "number": call.caller_number,
            "caller_name": lookup_name(call.caller_number or "", self.data.phonebook)
            or call.caller_name,
            "extension": call.extension,
            "calls": len(calls),
        }


class NecPbxAmiConnection(NecPbxEntity, BinarySensorEntity):
    """On while Home Assistant is logged in to FreePBX's manager interface."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "freepbx"

    def __init__(self, entry: NecPbxConfigEntry) -> None:
        super().__init__(entry, "freepbx_connection")

    @property
    def is_on(self) -> bool:
        return bool(self.data.ami and self.data.ami.connected)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return {"last_error": self.data.ami.last_error if self.data.ami else None}
