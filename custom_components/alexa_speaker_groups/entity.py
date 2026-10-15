"""Shared base for twin entities (spec §4)."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device import async_entity_id_to_device
from homeassistant.helpers.entity import Entity

from .discovery import media_player_of
from .manager import GroupManager


class TwinEntity(Entity):
    """Base for entities that act for one alexa_devices speaker."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: GroupManager, serial: str, key: str, name: str) -> None:
        """Attach to the Echo device of alexa_devices when present (§4.1).

        Since HA 2026.x a device belongs to a single config entry, so linking
        is done by setting ``device_entry`` (not via foreign identifiers).
        """
        self._manager = manager
        self._serial = serial
        self._attr_unique_id = f"{serial}_{key}"
        source = media_player_of(manager.hass, serial)
        self.device_entry = (
            async_entity_id_to_device(manager.hass, source) if source else None
        )
        # Without a device the name must identify the speaker on its own.
        self._attr_name = name if self.device_entry else f"Alexa {serial} {name}"

    async def async_added_to_hass(self) -> None:
        """Refresh whenever groups or mirrored alexa states change."""
        self.async_on_remove(self._manager.async_add_listener(self._async_refresh))

    @callback
    def _async_refresh(self) -> None:
        self.async_write_ha_state()
