"""Config and options flows (spec §2, §3.3)."""

from __future__ import annotations

from typing import Any, override

import probatio

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    ALEXA_DOMAIN,
    CONF_GROUP,
    CONF_KNOWN_SPEAKERS,
    CONF_MANUAL_GROUPS,
    CONF_MEMBERS,
    CONF_SPEAKERS,
    CONF_VOLUME_MODE,
    DOMAIN,
    LOGGER,
    VOLUME_MODE_SAME,
    VOLUME_MODES,
)
from .discovery import (
    AlexaDevice,
    MembershipUnavailable,
    discover_devices,
    read_auto_membership,
)


def _devices(hass: HomeAssistant) -> dict[str, AlexaDevice]:
    """Discover devices, tolerating unreadable runtime data (§3.3)."""
    try:
        auto = read_auto_membership(hass)
    except MembershipUnavailable:
        auto = {}
    return discover_devices(hass, auto)


def _options(devices: list[AlexaDevice]) -> list[SelectOptionDict]:
    return [
        SelectOptionDict(value=d.serial, label=d.name)
        for d in sorted(devices, key=lambda d: d.name.casefold())
    ]


def _settings_schema(
    speakers: list[AlexaDevice], selected: list[str], volume_mode: str
) -> probatio.Schema:
    """Speaker multi-select and volume mode (§2.2, §2.3)."""
    return probatio.Schema(
        {
            probatio.Required(CONF_SPEAKERS, default=selected): SelectSelector(
                SelectSelectorConfig(
                    options=_options(speakers),
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                )
            ),
            probatio.Required(CONF_VOLUME_MODE, default=volume_mode): SelectSelector(
                SelectSelectorConfig(
                    options=VOLUME_MODES,
                    translation_key=CONF_VOLUME_MODE,
                    mode=SelectSelectorMode.LIST,
                )
            ),
        }
    )


class AlexaSpeakerGroupsConfigFlow(ConfigFlow, domain=DOMAIN):
    """UI-only setup (§2.1)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose speakers and volume mode (§2.2, §2.3)."""
        if not self.hass.config_entries.async_loaded_entries(ALEXA_DOMAIN):
            return self.async_abort(reason="alexa_not_loaded")
        speakers = [d for d in _devices(self.hass).values() if not d.is_group]
        if not speakers:
            return self.async_abort(reason="no_speakers")

        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_SPEAKERS]:
                errors[CONF_SPEAKERS] = "no_speakers_selected"
            else:
                LOGGER.info("Configured %d speakers", len(user_input[CONF_SPEAKERS]))
                return self.async_create_entry(
                    title="Alexa Speaker Groups",
                    data={},
                    options={
                        CONF_SPEAKERS: user_input[CONF_SPEAKERS],
                        CONF_VOLUME_MODE: user_input[CONF_VOLUME_MODE],
                        # Everything shown now counts as "known" (§2.5).
                        CONF_KNOWN_SPEAKERS: [d.serial for d in speakers],
                        CONF_MANUAL_GROUPS: {},
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_settings_schema(
                speakers, [d.serial for d in speakers], VOLUME_MODE_SAME
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Options flow (§2.4)."""
        return AlexaSpeakerGroupsOptionsFlow()


class AlexaSpeakerGroupsOptionsFlow(OptionsFlow):
    """Change speakers, volume mode and manual group mapping (§2.4, §3.3).

    The entry update listener reloads the integration after saving.
    """

    def __init__(self) -> None:
        """Initialise (config_entry is provided by Home Assistant)."""
        self._group: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Menu."""
        return self.async_show_menu(step_id="init", menu_options=["settings", "manual"])

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Speakers and volume mode (§2.4)."""
        options = self.config_entry.options
        speakers = [d for d in _devices(self.hass).values() if not d.is_group]
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_SPEAKERS]:
                errors[CONF_SPEAKERS] = "no_speakers_selected"
            else:
                known = set(options.get(CONF_KNOWN_SPEAKERS, []))
                known |= {d.serial for d in speakers}
                return self.async_create_entry(
                    data={
                        **options,
                        CONF_SPEAKERS: user_input[CONF_SPEAKERS],
                        CONF_VOLUME_MODE: user_input[CONF_VOLUME_MODE],
                        CONF_KNOWN_SPEAKERS: sorted(known),
                    }
                )
        available = {d.serial for d in speakers}
        selected = [s for s in options.get(CONF_SPEAKERS, []) if s in available]
        return self.async_show_form(
            step_id="settings",
            data_schema=_settings_schema(
                speakers, selected, options.get(CONF_VOLUME_MODE, VOLUME_MODE_SAME)
            ),
            errors=errors,
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the Alexa group to map manually (§3.3)."""
        groups = [d for d in _devices(self.hass).values() if d.is_group]
        if not groups:
            return self.async_abort(reason="no_groups")
        if user_input is not None:
            self._group = user_input[CONF_GROUP]
            return await self.async_step_manual_members()
        return self.async_show_form(
            step_id="manual",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_GROUP): SelectSelector(
                        SelectSelectorConfig(
                            options=_options(groups), mode=SelectSelectorMode.DROPDOWN
                        )
                    )
                }
            ),
        )

    async def async_step_manual_members(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the group's speakers; empty removes the override (§3.3)."""
        assert self._group is not None
        options = self.config_entry.options
        manual: dict[str, list[str]] = dict(options.get(CONF_MANUAL_GROUPS, {}))
        if user_input is not None and CONF_MEMBERS in user_input:
            if members := user_input[CONF_MEMBERS]:
                manual[self._group] = members
            else:
                manual.pop(self._group, None)
            return self.async_create_entry(data={**options, CONF_MANUAL_GROUPS: manual})
        devices = _devices(self.hass)
        speakers = [d for d in devices.values() if not d.is_group]
        group = devices.get(self._group)
        return self.async_show_form(
            step_id="manual_members",
            data_schema=probatio.Schema(
                {
                    probatio.Optional(
                        CONF_MEMBERS, default=manual.get(self._group, [])
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=_options(speakers),
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            description_placeholders={"group": group.name if group else self._group},
        )
