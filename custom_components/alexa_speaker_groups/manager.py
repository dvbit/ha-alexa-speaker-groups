"""Group manager: dynamic groups, routing and volume (spec §3, §4.3, §5).

One manager exists per config entry (``entry.runtime_data``). It owns the
dynamic group composition, decides where every command is sent and keeps the
twin entities informed when something relevant changes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.media_player import (
    ATTR_MEDIA_VOLUME_LEVEL,
    ATTR_MEDIA_VOLUME_MUTED,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    EVENT_STATE_CHANGED,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store

from .const import (
    CONF_MANUAL_GROUPS,
    CONF_SPEAKERS,
    CONF_VOLUME_MODE,
    DOMAIN,
    ISSUE_MEMBERSHIP,
    LOGGER,
    STORAGE_KEY_TEMPLATE,
    STORAGE_VERSION,
    VOLUME_MODE_PROPORTIONAL,
    VOLUME_MODE_SAME,
)
from .discovery import (
    AlexaDevice,
    MembershipUnavailable,
    announce_notify_of,
    discover_devices,
    media_player_of,
    read_auto_membership,
    speak_notify_of,
)

# media_ids that are URLs cannot be spoken by Alexa (§5.3).
_URL_PREFIXES = ("http://", "https://", "media-source://")


@dataclass(frozen=True, slots=True)
class Route:
    """Where a command for a speaker goes (§5.1, §5.2)."""

    members: tuple[str, ...]  # speaker serials, leader first
    alexa_group: str | None  # serial of the exactly matching Alexa group

    @property
    def synchronized(self) -> bool:
        """True when playback is handled by an Alexa group (§5.1)."""
        return self.alexa_group is not None


class GroupManager:
    """Hold dynamic groups and route commands to alexa_devices entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise from the config entry options (§2)."""
        self.hass = hass
        self.entry = entry
        self.speakers: list[str] = list(entry.options.get(CONF_SPEAKERS, []))
        self.volume_mode: str = entry.options.get(CONF_VOLUME_MODE, VOLUME_MODE_SAME)
        self.manual_groups: dict[str, list[str]] = dict(
            entry.options.get(CONF_MANUAL_GROUPS, {})
        )
        # leader serial -> [leader, member, ...]; only groups with 2+ speakers.
        self._groups: dict[str, list[str]] = {}
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_TEMPLATE.format(entry_id=entry.entry_id)
        )
        self._listeners: list[CALLBACK_TYPE] = []
        self._twins: dict[str, str] = {}  # serial -> twin media_player entity_id
        self._tracked: set[str] = set()  # alexa entities whose state we mirror
        self._last_membership: dict[str, frozenset[str]] | None = None
        self._membership_failed = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def async_setup(self) -> None:
        """Restore groups (§4.3) and start listening to alexa_devices states."""
        stored = await self._store.async_load() or {}
        for members in stored.get("groups", []):
            valid = [s for s in members if s in self.speakers]
            if len(valid) > 1:
                self._groups[valid[0]] = valid
        LOGGER.info(
            "Set up with %d speakers, volume mode '%s', %d restored groups",
            len(self.speakers),
            self.volume_mode,
            len(self._groups),
        )
        self._refresh_tracked()
        self.entry.async_on_unload(
            self.hass.bus.async_listen(
                EVENT_STATE_CHANGED,
                self._async_alexa_state_changed,
                event_filter=self._state_event_filter,
            )
        )

    def _store_data(self) -> dict[str, Any]:
        return {"groups": list(self._groups.values())}

    async def async_flush(self) -> None:
        """Write pending group changes now (unload/reload, §4.3)."""
        await self._store.async_save(self._store_data())

    async def async_remove_storage(self) -> None:
        """Delete persisted groups when the entry is removed."""
        await self._store.async_remove()

    @callback
    def _state_event_filter(self, event_data: EventStateChangedData) -> bool:
        """Only state changes of mirrored alexa_devices entities matter."""
        return event_data["entity_id"] in self._tracked

    @callback
    def _async_alexa_state_changed(self, event: Event[EventStateChangedData]) -> None:
        """Mirror alexa_devices state changes on the twins (§5.5)."""
        self._prune_unavailable()
        self._notify_listeners()

    @callback
    def _prune_unavailable(self) -> None:
        """Drop unavailable speakers from their groups (§4.1, §5.1).

        HA skips entity services (join/unjoin) for unavailable entities, so an
        unavailable twin could never leave a group and would block an exact
        match with an Alexa group.
        """
        for group in list(self._groups.values()):
            for serial in group:
                own = media_player_of(self.hass, serial)
                if own is None or self.state_of(own) is not None:
                    continue
                LOGGER.warning(
                    "Speaker %s is unavailable: removed from its group", serial
                )
                self._detach(serial)
                self._changed()

    @callback
    def async_add_listener(self, update: CALLBACK_TYPE) -> Callable[[], None]:
        """Register a twin update callback; returns the remover."""
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    @callback
    def _notify_listeners(self) -> None:
        for update in list(self._listeners):
            update()

    @callback
    def register_twin(self, serial: str, entity_id: str) -> None:
        """Remember the twin media_player of a speaker (for join/unjoin).

        Other twins are refreshed so restored groups (§4.3) list every member
        regardless of the order in which twins are added.
        """
        self._twins[serial] = entity_id
        self._prune_unavailable()
        self._notify_listeners()

    @callback
    def unregister_twin(self, serial: str) -> None:
        """Forget a twin when it is removed."""
        self._twins.pop(serial, None)

    def twin_entity_id(self, serial: str) -> str | None:
        """Return the twin media_player entity_id of a speaker."""
        return self._twins.get(serial)

    def serial_of_twin(self, entity_id: str) -> str | None:
        """Return the speaker serial of a twin media_player entity_id."""
        return next((s for s, e in self._twins.items() if e == entity_id), None)

    # ------------------------------------------------------------------
    # Membership (§3)
    # ------------------------------------------------------------------
    def membership(self) -> dict[str, frozenset[str]]:
        """Return {alexa_group_serial: member serials}.

        Automatic data (§3.1) is read live at every call, so it always
        reflects the latest alexa_devices refresh (§3.2). Manual mappings from
        the options (§3.3) override automatic entries for the same group.
        """
        try:
            auto = read_auto_membership(self.hass)
        except MembershipUnavailable as err:
            if not self._membership_failed:
                LOGGER.error(
                    "Cannot read Alexa group membership from alexa_devices (%s); "
                    "using manual mapping from options",
                    err,
                )
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    ISSUE_MEMBERSHIP,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=ISSUE_MEMBERSHIP,
                )
                self._membership_failed = True
            auto = {}
        else:
            if self._membership_failed:
                LOGGER.info("Alexa group membership readable again")
                ir.async_delete_issue(self.hass, DOMAIN, ISSUE_MEMBERSHIP)
                self._membership_failed = False

        merged = dict(auto)
        merged.update({g: frozenset(m) for g, m in self.manual_groups.items()})
        if merged != self._last_membership:
            LOGGER.debug(
                "Alexa group membership: %s",
                {g: sorted(m) for g, m in merged.items()},
            )
            self._last_membership = merged
            self._refresh_tracked(merged)
        return merged

    def devices(self) -> dict[str, AlexaDevice]:
        """Return discovered alexa_devices devices (§2.2)."""
        try:
            auto = read_auto_membership(self.hass)
        except MembershipUnavailable:
            auto = {}
        return discover_devices(self.hass, auto)

    @callback
    def _refresh_tracked(
        self, membership: dict[str, frozenset[str]] | None = None
    ) -> None:
        """Track the speakers' and Alexa groups' media players (§5.5)."""
        if membership is None:
            membership = self._last_membership or {}
        serials = set(self.speakers) | set(membership)
        self._tracked = {e for s in serials if (e := media_player_of(self.hass, s))}

    # ------------------------------------------------------------------
    # Dynamic groups (§4.1)
    # ------------------------------------------------------------------
    def group_of(self, serial: str) -> list[str] | None:
        """Return the group (leader first) containing a speaker, if any."""
        return next((g for g in self._groups.values() if serial in g), None)

    def is_leader(self, serial: str) -> bool:
        """Return True when the speaker leads a group."""
        return serial in self._groups

    @callback
    def _detach(self, serial: str) -> None:
        """Remove a speaker from its group, promoting a new leader if needed."""
        group = self.group_of(serial)
        if group is None:
            return
        del self._groups[group[0]]
        remaining = [s for s in group if s != serial]
        if len(remaining) > 1:
            self._groups[remaining[0]] = remaining

    async def async_join(self, leader: str, members: list[str]) -> None:
        """Join speakers to the leader's group (media_player.join)."""
        unknown = [s for s in [leader, *members] if s not in self.speakers]
        if unknown:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_speaker",
                translation_placeholders={"speakers": ", ".join(unknown)},
            )
        self._prune_unavailable()
        # Keep the existing group when the leader already leads one.
        group = list(self._groups.get(leader, [])) or [leader]
        if not self.is_leader(leader):
            self._detach(leader)
        for serial in members:
            if serial in group:
                continue
            self._detach(serial)
            group.append(serial)
        self._groups.pop(leader, None)
        if len(group) > 1:
            self._groups[leader] = group
        LOGGER.info("Joined group led by %s: %s", leader, group)
        self._log_route(leader)
        self._changed()

    async def async_unjoin(self, serial: str) -> None:
        """Remove a speaker from its group (media_player.unjoin)."""
        if (group := self.group_of(serial)) is None:
            LOGGER.debug("Unjoin ignored: %s is not grouped", serial)
            return
        self._detach(serial)
        LOGGER.info("Speaker %s left its group", serial)
        remaining = [s for s in group if s != serial]
        if len(remaining) > 1:
            self._log_route(remaining[0])
        self._changed()

    @callback
    def _changed(self) -> None:
        """Persist (§4.3) and refresh twins."""
        self._store.async_delay_save(self._store_data, 1)
        self._notify_listeners()

    def _log_route(self, leader: str) -> None:
        """INFO when a group is synchronized, WARNING when it is not (§6)."""
        route = self.resolve_route(leader)
        if len(route.members) < 2:
            return
        if route.synchronized:
            LOGGER.info(
                "Group %s matches Alexa group %s: playback synchronized",
                list(route.members),
                route.alexa_group,
            )
        else:
            LOGGER.warning(
                "No Alexa group matches %s: commands are sent to each speaker, "
                "playback will not be synchronized",
                list(route.members),
            )

    # ------------------------------------------------------------------
    # Routing (§5)
    # ------------------------------------------------------------------
    def resolve_route(self, serial: str) -> Route:
        """Find the exact Alexa group for the speaker's group (§5.1, §5.2)."""
        members = tuple(self.group_of(serial) or [serial])
        if len(members) == 1:
            return Route(members, None)
        wanted = frozenset(members)
        for group_serial, group_members in self.membership().items():
            if group_members == wanted:
                return Route(members, group_serial)
        return Route(members, None)

    def mirror_entity(self, serial: str) -> str | None:
        """Entity whose state the twin shows (§5.5)."""
        route = self.resolve_route(serial)
        if route.alexa_group and (
            group_mp := media_player_of(self.hass, route.alexa_group)
        ):
            return group_mp
        return media_player_of(self.hass, route.members[0])

    def state_of(self, entity_id: str | None) -> State | None:
        """Return a usable state object, None when unavailable."""
        if entity_id is None:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        return state

    async def async_media_command(
        self, serial: str, service: str, data: dict[str, Any] | None = None
    ) -> None:
        """Send a playback command to the group or each member (§5.1, §5.2)."""
        route = self.resolve_route(serial)
        targets: list[str] = []
        if route.alexa_group:
            if group_mp := media_player_of(self.hass, route.alexa_group):
                targets = [group_mp]
        if not targets:
            targets = [e for s in route.members if (e := media_player_of(self.hass, s))]
        await self._async_call("media_player", service, targets, data)

    async def async_tts(self, serial: str, message: str, announce: bool) -> None:
        """Speak or announce on the group or each member (§4.2, §5.3)."""
        route = self.resolve_route(serial)
        targets: list[str] = []
        if route.alexa_group:
            if group_announce := announce_notify_of(self.hass, route.alexa_group):
                if not announce:
                    LOGGER.debug(
                        "Speak is not available on Alexa group %s, using Announce",
                        route.alexa_group,
                    )
                targets = [group_announce]
        if not targets:
            lookup = announce_notify_of if announce else speak_notify_of
            targets = [e for s in route.members if (e := lookup(self.hass, s))]
        await self._async_call("notify", "send_message", targets, {"message": message})

    async def async_play_media(
        self, serial: str, media_type: str, media_id: str, announce: bool | None
    ) -> None:
        """play_media; announce=True follows the TTS path (§5.3)."""
        if announce:
            if media_id.startswith(_URL_PREFIXES):
                LOGGER.error("Announce needs text, got URL %s", media_id)
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="announce_needs_text"
                )
            await self.async_tts(serial, media_id, announce=True)
            return
        await self.async_media_command(
            serial,
            "play_media",
            {"media_content_type": media_type, "media_content_id": media_id},
        )

    # ------------------------------------------------------------------
    # Volume (§5.4)
    # ------------------------------------------------------------------
    def _volume_members(self, serial: str) -> list[str]:
        """Return the speakers a volume command acts on (leader: whole group)."""
        group = self.group_of(serial)
        return group if group and group[0] == serial else [serial]

    def _volume(self, serial: str) -> float | None:
        state = self.state_of(media_player_of(self.hass, serial))
        return state.attributes.get(ATTR_MEDIA_VOLUME_LEVEL) if state else None

    def volume_level(self, serial: str) -> float | None:
        """Own volume, or the members' average for a leader (§5.4)."""
        levels = [
            v
            for s in self._volume_members(serial)
            if (v := self._volume(s)) is not None
        ]
        return round(sum(levels) / len(levels), 2) if levels else None

    def is_muted(self, serial: str) -> bool | None:
        """Own mute state, or True only if every member is muted (leader)."""
        values = []
        for member in self._volume_members(serial):
            state = self.state_of(media_player_of(self.hass, member))
            if state is not None:
                values.append(bool(state.attributes.get(ATTR_MEDIA_VOLUME_MUTED)))
        return all(values) if values else None

    async def async_set_volume(self, serial: str, volume: float) -> None:
        """Apply volume to each member using the configured mode (§2.3, §5.4)."""
        members = self._volume_members(serial)
        current = {s: self._volume(s) for s in members}
        known = [v for v in current.values() if v is not None]
        average = sum(known) / len(known) if known else 0
        for member in members:
            level = volume
            if (
                self.volume_mode == VOLUME_MODE_PROPORTIONAL
                and len(members) > 1
                and average > 0
                and current[member] is not None
            ):
                level = min(1.0, max(0.0, current[member] * volume / average))
            if (target := media_player_of(self.hass, member)) is None:
                LOGGER.warning("Speaker %s has no media player, volume skipped", member)
                continue
            await self._async_call(
                "media_player",
                "volume_set",
                [target],
                {ATTR_MEDIA_VOLUME_LEVEL: round(level, 2)},
            )

    async def async_mute(self, serial: str, mute: bool) -> None:
        """Mute the speaker, or every member for a leader (§5.4)."""
        targets = [
            e
            for s in self._volume_members(serial)
            if (e := media_player_of(self.hass, s))
        ]
        await self._async_call(
            "media_player", "volume_mute", targets, {ATTR_MEDIA_VOLUME_MUTED: mute}
        )

    # ------------------------------------------------------------------
    async def _async_call(
        self,
        domain: str,
        service: str,
        targets: list[str],
        data: dict[str, Any] | None = None,
    ) -> None:
        """Call an alexa_devices entity service, logging per §6."""
        if not targets:
            LOGGER.warning(
                "No alexa_devices entity available for %s.%s", domain, service
            )
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="no_target"
            )
        LOGGER.debug("Calling %s.%s on %s with %s", domain, service, targets, data)
        try:
            await self.hass.services.async_call(
                domain,
                service,
                {**(data or {}), ATTR_ENTITY_ID: targets},
                blocking=True,
            )
        except HomeAssistantError as err:
            LOGGER.error("%s.%s on %s failed: %s", domain, service, targets, err)
            raise
