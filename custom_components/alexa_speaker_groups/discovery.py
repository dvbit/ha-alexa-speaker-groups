"""Discovery of Alexa speakers and groups (spec §1.2, §2.2, §3).

Speakers and groups are found at runtime from the device and entity
registries populated by the core ``alexa_devices`` integration; nothing is
hard-coded, so the integration adapts to any installation (§1.2).
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import (
    ALEXA_DOMAIN,
    ALEXA_KEY_ANNOUNCE,
    ALEXA_KEY_MEDIA,
    ALEXA_KEY_SPEAK,
    SPEAKER_GROUP_FAMILY,
    SPEAKER_GROUP_MODEL,
)


class MembershipUnavailable(Exception):
    """Raised when alexa_devices internal data cannot be read (§3.3)."""


@dataclass(frozen=True, slots=True)
class AlexaDevice:
    """An alexa_devices device that exposes a media_player entity."""

    serial: str
    name: str
    device_id: str
    is_group: bool


def alexa_entity_id(
    hass: HomeAssistant, platform: Platform, serial: str, key: str
) -> str | None:
    """Return the entity_id of an alexa_devices entity (unique id "<serial>-<key>")."""
    return er.async_get(hass).async_get_entity_id(
        platform, ALEXA_DOMAIN, f"{serial}-{key}"
    )


def media_player_of(hass: HomeAssistant, serial: str) -> str | None:
    """Return the alexa_devices media_player entity of a device."""
    return alexa_entity_id(hass, Platform.MEDIA_PLAYER, serial, ALEXA_KEY_MEDIA)


def speak_notify_of(hass: HomeAssistant, serial: str) -> str | None:
    """Return the alexa_devices "Speak" notify entity (not present on groups)."""
    return alexa_entity_id(hass, Platform.NOTIFY, serial, ALEXA_KEY_SPEAK)


def announce_notify_of(hass: HomeAssistant, serial: str) -> str | None:
    """Return the alexa_devices "Announce" notify entity."""
    return alexa_entity_id(hass, Platform.NOTIFY, serial, ALEXA_KEY_ANNOUNCE)


def read_auto_membership(hass: HomeAssistant) -> dict[str, frozenset[str]]:
    """Read Alexa group membership from alexa_devices runtime data (§3.1).

    This relies on internal (non-public) data: the coordinator stored in
    ``entry.runtime_data`` and the aioamazondevices ``AmazonDevice`` fields
    ``device_family`` and ``device_cluster_members``. Any structural change
    raises ``MembershipUnavailable`` so the caller can fall back (§3.3).

    Returns {group_serial: frozenset(member_serials)}; empty if alexa_devices
    is not loaded yet.
    """
    groups: dict[str, frozenset[str]] = {}
    try:
        for entry in hass.config_entries.async_loaded_entries(ALEXA_DOMAIN):
            data = entry.runtime_data.data
            if data is None:  # first refresh not completed yet
                continue
            for serial, device in data.items():
                if device.device_family == SPEAKER_GROUP_FAMILY:
                    groups[serial] = frozenset(device.device_cluster_members)
    except (AttributeError, TypeError, KeyError) as err:
        raise MembershipUnavailable(repr(err)) from err
    return groups


def discover_devices(
    hass: HomeAssistant, auto_groups: dict[str, frozenset[str]]
) -> dict[str, AlexaDevice]:
    """Return every alexa_devices device that has a media_player (§2.2).

    A device is a group when it appears in the runtime membership (§3.1) or,
    as a registry fallback, when its model is "Speaker Group" (§3.3).
    Devices without a media_player (Fire TV, Fire tablets) are skipped.
    """
    devices: dict[str, AlexaDevice] = {}
    for device in dr.async_get(hass).devices:
        for domain, serial in device.identifiers:
            if domain != ALEXA_DOMAIN or media_player_of(hass, serial) is None:
                continue
            devices[serial] = AlexaDevice(
                serial=serial,
                name=device.name_by_user or device.name or serial,
                device_id=device.id,
                is_group=serial in auto_groups or device.model == SPEAKER_GROUP_MODEL,
            )
    return devices
