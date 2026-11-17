"""Do-not-disturb switches for FreePBX extensions (needs the FreePBX connection)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NecPbxConfigEntry
from .const import CONF_DND_EXTENSIONS
from .entity import NecPbxEntity

PARALLEL_UPDATES = 1


def dnd_extensions(text: str) -> list[str]:
    """'901, 902' or one per line -> ['901', '902']."""
    return [part.strip() for part in text.replace("\n", ",").split(",") if part.strip()]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NecPbxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    if entry.runtime_data.ami is None:
        return
    async_add_entities(
        NecPbxDndSwitch(entry, ext)
        for ext in dnd_extensions(entry.options.get(CONF_DND_EXTENSIONS, ""))
    )


class NecPbxDndSwitch(NecPbxEntity, SwitchEntity):
    """FreePBX do-not-disturb for one extension: on = calls to it are not rung."""

    _attr_translation_key = "do_not_disturb"
    _attr_should_poll = True  # DND can also be set from a phone (*76), so check now and then

    def __init__(self, entry: NecPbxConfigEntry, ext: str) -> None:
        super().__init__(entry, f"dnd_{ext}")
        self._ext = ext
        self._attr_translation_placeholders = {"extension": ext}
        self._attr_is_on: bool | None = None

    @property
    def available(self) -> bool:
        return self.data.ami is not None and self.data.ami.connected

    async def async_update(self) -> None:
        if not self.available:
            return
        try:
            self._attr_is_on = await self.data.ami.get_dnd(self._ext)
        except (ConnectionError, TimeoutError):
            return

    async def _set(self, on: bool) -> None:
        try:
            await self.data.ami.set_dnd(self._ext, on)
        except (ConnectionError, TimeoutError) as err:
            raise HomeAssistantError(f"FreePBX didn't change do-not-disturb: {err}") from err
        self._attr_is_on = on
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
