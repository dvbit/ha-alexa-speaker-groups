"""Twin media_player with Sonos-style grouping (spec §4.1, §5)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.media_player import (
    ATTR_MEDIA_ALBUM_NAME,
    ATTR_MEDIA_ARTIST,
    ATTR_MEDIA_CONTENT_TYPE,
    ATTR_MEDIA_DURATION,
    ATTR_MEDIA_POSITION,
    ATTR_MEDIA_POSITION_UPDATED_AT,
    ATTR_MEDIA_TITLE,
    MediaPlayerDeviceClass,
    MediaPlayerEnqueue,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.const import ATTR_ENTITY_PICTURE, ATTR_SUPPORTED_FEATURES
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AlexaSpeakerGroupsConfigEntry
from .const import DOMAIN, LOGGER
from .discovery import media_player_of
from .entity import TwinEntity
from .manager import GroupManager

PARALLEL_UPDATES = 0

# Always offered: the twin routes these itself (§5).
_BASE_FEATURES = (
    MediaPlayerEntityFeature.GROUPING
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
)
# Mirrored from the entity in use, as alexa_devices enables them dynamically.
_DYNAMIC_FEATURES = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlexaSpeakerGroupsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create one twin per managed speaker (§4.1)."""
    manager = entry.runtime_data
    async_add_entities(
        AlexaGroupMediaPlayer(manager, serial) for serial in manager.speakers
    )


class AlexaGroupMediaPlayer(TwinEntity, MediaPlayerEntity):
    """Twin of an Echo media_player that supports join/unjoin."""

    _attr_device_class = MediaPlayerDeviceClass.SPEAKER

    def __init__(self, manager: GroupManager, serial: str) -> None:
        """Initialise the twin."""
        super().__init__(manager, serial, "group", "Group")

    async def async_added_to_hass(self) -> None:
        """Register the twin so join/unjoin can map entity_ids to speakers."""
        await super().async_added_to_hass()
        self._manager.register_twin(self._serial, self.entity_id)
        self.async_on_remove(lambda: self._manager.unregister_twin(self._serial))

    # ---------------------------------------------------------------- state
    @property
    def _mirror(self) -> State | None:
        """State of the entity in use: Alexa group or leader (§5.5)."""
        return self._manager.state_of(self._manager.mirror_entity(self._serial))

    def _attr(self, key: str) -> Any:
        state = self._mirror
        return state.attributes.get(key) if state else None

    @property
    def available(self) -> bool:
        """Available when the speaker's own alexa media_player is."""
        own = media_player_of(self.hass, self._serial)
        return self._manager.state_of(own) is not None

    @property
    def state(self) -> MediaPlayerState | None:
        """Mirrored playback state (§5.5)."""
        if (mirror := self._mirror) is None:
            return MediaPlayerState.IDLE
        try:
            return MediaPlayerState(mirror.state)
        except ValueError:
            return MediaPlayerState.IDLE

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Base features plus playback controls of the entity in use."""
        mirrored = MediaPlayerEntityFeature(self._attr(ATTR_SUPPORTED_FEATURES) or 0)
        return _BASE_FEATURES | (mirrored & _DYNAMIC_FEATURES)

    @property
    def group_members(self) -> list[str]:
        """Twin entity_ids of the group, leader first (§4.1)."""
        group = self._manager.group_of(self._serial) or [self._serial]
        return [e for s in group if (e := self._manager.twin_entity_id(s))]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose routing to make the behaviour visible (§5.1, §5.2)."""
        route = self._manager.resolve_route(self._serial)
        return {
            "synchronized": route.synchronized,
            "alexa_group": media_player_of(self.hass, route.alexa_group)
            if route.alexa_group
            else None,
        }

    @property
    def volume_level(self) -> float | None:
        """Own volume, members' average for a leader (§5.4)."""
        return self._manager.volume_level(self._serial)

    @property
    def is_volume_muted(self) -> bool | None:
        """Mute state (§5.4)."""
        return self._manager.is_muted(self._serial)

    @property
    def media_title(self) -> str | None:
        """Mirrored title."""
        return self._attr(ATTR_MEDIA_TITLE)

    @property
    def media_artist(self) -> str | None:
        """Mirrored artist."""
        return self._attr(ATTR_MEDIA_ARTIST)

    @property
    def media_album_name(self) -> str | None:
        """Mirrored album."""
        return self._attr(ATTR_MEDIA_ALBUM_NAME)

    @property
    def media_duration(self) -> int | None:
        """Mirrored duration."""
        return self._attr(ATTR_MEDIA_DURATION)

    @property
    def media_position(self) -> int | None:
        """Mirrored position."""
        return self._attr(ATTR_MEDIA_POSITION)

    @property
    def media_position_updated_at(self) -> datetime | None:
        """Mirrored position timestamp."""
        return self._attr(ATTR_MEDIA_POSITION_UPDATED_AT)

    @property
    def media_content_type(self) -> MediaType | str | None:
        """Mirrored content type."""
        return self._attr(ATTR_MEDIA_CONTENT_TYPE)

    @property
    def entity_picture(self) -> str | None:
        """Reuse the artwork URL of the entity in use."""
        return self._attr(ATTR_ENTITY_PICTURE)

    # ------------------------------------------------------------- commands
    async def async_media_play(self) -> None:
        """Play (routed, §5)."""
        await self._manager.async_media_command(self._serial, "media_play")

    async def async_media_pause(self) -> None:
        """Pause (routed, §5)."""
        await self._manager.async_media_command(self._serial, "media_pause")

    async def async_media_stop(self) -> None:
        """Stop (routed, §5)."""
        await self._manager.async_media_command(self._serial, "media_stop")

    async def async_media_next_track(self) -> None:
        """Next track (routed, §5)."""
        await self._manager.async_media_command(self._serial, "media_next_track")

    async def async_media_previous_track(self) -> None:
        """Previous track (routed, §5)."""
        await self._manager.async_media_command(self._serial, "media_previous_track")

    async def async_play_media(
        self,
        media_type: MediaType | str,
        media_id: str,
        enqueue: MediaPlayerEnqueue | None = None,
        announce: bool | None = None,
        **kwargs: Any,
    ) -> None:
        """Play media, or announce text when announce=True (§5.3)."""
        await self._manager.async_play_media(
            self._serial, str(media_type), media_id, announce
        )

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume (§5.4)."""
        await self._manager.async_set_volume(self._serial, volume)

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute (§5.4)."""
        await self._manager.async_mute(self._serial, mute)

    async def async_join_players(self, group_members: list[str]) -> None:
        """Group the given twins with this one (§4.1)."""
        serials: list[str] = []
        for entity_id in group_members:
            if (serial := self._manager.serial_of_twin(entity_id)) is None:
                LOGGER.error(
                    "Cannot join %s: not an Alexa Speaker Groups twin", entity_id
                )
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="not_a_twin",
                    translation_placeholders={"entity_id": entity_id},
                )
            serials.append(serial)
        await self._manager.async_join(self._serial, serials)

    async def async_unjoin_player(self) -> None:
        """Leave the group (§4.1)."""
        await self._manager.async_unjoin(self._serial)
