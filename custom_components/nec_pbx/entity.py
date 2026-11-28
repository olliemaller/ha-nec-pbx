"""Base entity for NEC PBX."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .attendant import AttendantCoordinator, AttendantData
from .const import DOMAIN, SIGNAL_UPDATE

if TYPE_CHECKING:
    from . import NecPbxConfigEntry, NecPbxData

# Home Assistant 2026.10 added via_device_id and deprecated via_device;
# older versions only accept via_device.
SUPPORTS_VIA_DEVICE_ID = (
    "via_device_id" in inspect.signature(dr.DeviceRegistry.async_get_or_create).parameters
)


def pbx_device_info(entry: NecPbxConfigEntry) -> DeviceInfo:
    """The phone system itself."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="NEC",
        model="SL2100 / SV9100",
        configuration_url=f"http://{entry.data['host']}",
    )


def attendant_identifier(entry: NecPbxConfigEntry) -> tuple[str, str]:
    """The AI attendant device's identifier."""
    return (DOMAIN, f"{entry.entry_id}_attendant")


def attendant_device_info(entry: NecPbxConfigEntry, version: str | None) -> DeviceInfo:
    """The AI attendant engine, under the phone system."""
    parent: dict[str, Any]
    pbx_device_id = entry.runtime_data.pbx_device_id
    if SUPPORTS_VIA_DEVICE_ID and pbx_device_id:
        parent = {"via_device_id": pbx_device_id}
    else:  # pragma: no cover - Home Assistant before 2026.10
        parent = {"via_device": (DOMAIN, entry.entry_id)}
    info: DeviceInfo = DeviceInfo(
        identifiers={attendant_identifier(entry)},
        name="AI attendant",
        manufacturer="nec-ai-attendant",
        model="AI attendant",
        sw_version=version,
        **parent,  # type: ignore[typeddict-item]
    )
    return info


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
            self._attr_device_info = pbx_device_info(entry)
        else:
            kind, number, name = sub_device
            parent: dict[str, Any]
            pbx_device_id = entry.runtime_data.pbx_device_id
            if SUPPORTS_VIA_DEVICE_ID and pbx_device_id:
                parent = {"via_device_id": pbx_device_id}
            else:  # pragma: no cover - Home Assistant before 2026.10
                parent = {"via_device": (DOMAIN, entry.entry_id)}
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{entry.entry_id}_{kind}_{number}")},
                name=name or f"{kind.capitalize()} {number}",
                manufacturer="NEC",
                model=f"{kind.capitalize()} {number}",
                **parent,  # type: ignore[typeddict-item]
            )

    @property
    def data(self) -> NecPbxData:
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


class AttendantEntity(CoordinatorEntity[AttendantCoordinator]):
    """An entity on the AI attendant's device, updated by its coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self, entry: NecPbxConfigEntry, coordinator: AttendantCoordinator, key: str
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_attendant_{key}"
        self._attr_translation_key = f"attendant_{key}"
        version = coordinator.data.status.get("version") if coordinator.data else None
        self._attr_device_info = attendant_device_info(
            entry, str(version) if version is not None else None
        )

    @property
    def attendant(self) -> AttendantData:
        """The engine's last answer (empty until the first one)."""
        return self.coordinator.data or AttendantData()
