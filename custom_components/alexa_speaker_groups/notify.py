"""Twin Speak/Announce notify entities that follow the group (spec §4.2, §5.3)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.notify import NotifyEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AlexaSpeakerGroupsConfigEntry
from .discovery import media_player_of
from .entity import TwinEntity
from .manager import GroupManager

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlexaSpeakerGroupsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create Speak and Announce twins per managed speaker (§4.2)."""
    manager = entry.runtime_data
    async_add_entities(
        entity
        for serial in manager.speakers
        for entity in (
            AlexaGroupNotify(manager, serial, announce=False),
            AlexaGroupNotify(manager, serial, announce=True),
        )
    )


class AlexaGroupNotify(TwinEntity, NotifyEntity):
    """Send TTS to the speaker's current group."""

    def __init__(self, manager: GroupManager, serial: str, announce: bool) -> None:
        """Initialise a Speak (announce=False) or Announce twin."""
        if announce:
            super().__init__(manager, serial, "group_announce", "Group announce")
        else:
            super().__init__(manager, serial, "group_speak", "Group speak")
        self._announce = announce

    @property
    def available(self) -> bool:
        """Available when the speaker's own alexa media_player is."""
        return (
            self._manager.state_of(media_player_of(self.hass, self._serial)) is not None
        )

    async def async_send_message(
        self, message: str, title: str | None = None, **kwargs: Any
    ) -> None:
        """Route the message to the Alexa group or each member (§5.3)."""
        await self._manager.async_tts(self._serial, message, self._announce)
