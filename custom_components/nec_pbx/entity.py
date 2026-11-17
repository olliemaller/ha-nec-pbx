"""Base entity for NEC PBX."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from . import NecPbxConfigEntry
from .const import DOMAIN, SIGNAL_UPDATE


class NecPbxEntity(Entity):
    """Shared device info and update wiring."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry: NecPbxConfigEntry,
        key: str,
        *,
        sub_device: tuple[str, str, str] | None = None,
    ) -> None:
        """``sub_device`` = (kind, number, name) puts the entity on its own
        device under the phone system, e.g. ("extension", "103", "Oliver")."""
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        if sub_device is None:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, entry.entry_id)},
                name=entry.title,
                manufacturer="NEC",
                model="SL2100 / SV9100",
                configuration_url=f"http://{entry.data['host']}",
            )
        else:
            kind, number, name = sub_device
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{entry.entry_id}_{kind}_{number}")},
                name=name or f"{kind.capitalize()} {number}",
                manufacturer="NEC",
                model=f"{kind.capitalize()} {number}",
                via_device=(DOMAIN, entry.entry_id),
            )

    @property
    def data(self):
        """Runtime data for this PBX."""
        return self._entry.runtime_data

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_UPDATE.format(self._entry.entry_id), self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
