"""Alexa Speaker Groups: Sonos-style dynamic grouping for alexa_devices.

See docs/SPEC.md. Sections are referenced in comments as "§<n>".
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from .const import (
    ALEXA_DOMAIN,
    CONF_KNOWN_SPEAKERS,
    DOMAIN,
    ISSUE_NEW_SPEAKER_PREFIX,
    LOGGER,
)
from .manager import GroupManager

PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER, Platform.NOTIFY]

type AlexaSpeakerGroupsConfigEntry = ConfigEntry[GroupManager]


async def async_setup_entry(
    hass: HomeAssistant, entry: AlexaSpeakerGroupsConfigEntry
) -> bool:
    """Set up the manager, the twin platforms and new-speaker detection."""
    manager = GroupManager(hass, entry)
    await manager.async_setup()
    entry.runtime_data = manager

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # §2.5 - offer speakers that appear after the setup through Repairs.
    _async_check_new_speakers(hass, entry)

    @callback
    def _registry_filter(event_data: er.EventEntityRegistryUpdatedData) -> bool:
        return event_data["action"] == "create" and event_data["entity_id"].startswith(
            "media_player."
        )

    @callback
    def _registry_updated(event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        entity = er.async_get(hass).async_get(event.data["entity_id"])
        if entity is not None and entity.platform == ALEXA_DOMAIN:
            _async_check_new_speakers(hass, entry)

    entry.async_on_unload(
        hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED,
            _registry_updated,
            event_filter=_registry_filter,
        )
    )
    # §2.4 - options changed (options flow or Repairs fix): reload.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


@callback
def _async_check_new_speakers(
    hass: HomeAssistant, entry: AlexaSpeakerGroupsConfigEntry
) -> None:
    """Raise a fixable issue for every speaker never offered before (§2.5)."""
    known = set(entry.options.get(CONF_KNOWN_SPEAKERS, []))
    for device in entry.runtime_data.devices().values():
        if device.is_group or device.serial in known:
            continue
        issue_id = f"{ISSUE_NEW_SPEAKER_PREFIX}{device.serial}"
        LOGGER.info("New Alexa speaker found: %s (%s)", device.name, device.serial)
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="new_speaker",
            translation_placeholders={"name": device.name},
            data={
                "entry_id": entry.entry_id,
                "serial": device.serial,
                "name": device.name,
            },
        )


async def _async_update_listener(
    hass: HomeAssistant, entry: AlexaSpeakerGroupsConfigEntry
) -> None:
    """Reload after the options changed (§2.4)."""
    LOGGER.debug("Options changed, reloading")
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: AlexaSpeakerGroupsConfigEntry
) -> bool:
    """Persist pending group changes (§4.3) and unload the twin platforms."""
    await entry.runtime_data.async_flush()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(
    hass: HomeAssistant, entry: AlexaSpeakerGroupsConfigEntry
) -> None:
    """Remove persisted groups and our issues."""
    await GroupManager(hass, entry).async_remove_storage()
    for issue_id in list(ir.async_get(hass).issues):
        if issue_id[0] == DOMAIN:
            ir.async_delete_issue(hass, DOMAIN, issue_id[1])
