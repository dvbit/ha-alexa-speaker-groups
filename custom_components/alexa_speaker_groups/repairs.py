"""Repairs fix flow for newly found speakers (spec §2.5)."""

from __future__ import annotations

from typing import Any

import probatio

from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    ACTION_ADD,
    ACTION_IGNORE,
    CONF_ACTION,
    CONF_KNOWN_SPEAKERS,
    CONF_SPEAKERS,
    ISSUE_NEW_SPEAKER_PREFIX,
    LOGGER,
)


class NewSpeakerRepairFlow(RepairsFlow):
    """Add or ignore a speaker found after setup."""

    def __init__(self, entry_id: str, serial: str, name: str) -> None:
        """Remember which entry and speaker the issue is about."""
        self._entry_id = entry_id
        self._serial = serial
        self._name = name

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Start at the confirm step."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add the speaker or ignore it; options update triggers a reload."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(reason="entry_not_found")
        if user_input is not None:
            options = dict(entry.options)
            known = set(options.get(CONF_KNOWN_SPEAKERS, [])) | {self._serial}
            speakers = list(options.get(CONF_SPEAKERS, []))
            if user_input[CONF_ACTION] == ACTION_ADD and self._serial not in speakers:
                speakers.append(self._serial)
            LOGGER.info("New speaker %s: %s", self._serial, user_input[CONF_ACTION])
            self.hass.config_entries.async_update_entry(
                entry,
                options={
                    **options,
                    CONF_SPEAKERS: speakers,
                    CONF_KNOWN_SPEAKERS: sorted(known),
                },
            )
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="confirm",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_ACTION, default=ACTION_ADD): SelectSelector(
                        SelectSelectorConfig(
                            options=[ACTION_ADD, ACTION_IGNORE],
                            translation_key=CONF_ACTION,
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            description_placeholders={"name": self._name},
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create the fix flow for a repairs issue."""
    if issue_id.startswith(ISSUE_NEW_SPEAKER_PREFIX) and data:
        return NewSpeakerRepairFlow(
            str(data["entry_id"]),
            str(data["serial"]),
            str(data.get("name") or data["serial"]),
        )
    return ConfirmRepairFlow()
