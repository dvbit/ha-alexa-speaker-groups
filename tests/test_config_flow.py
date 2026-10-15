"""Tests for config, options and repairs flows (spec §2, §3.3)."""

from __future__ import annotations

from custom_components.alexa_speaker_groups.const import (
    CONF_KNOWN_SPEAKERS,
    CONF_MANUAL_GROUPS,
    CONF_SPEAKERS,
    CONF_VOLUME_MODE,
    DOMAIN,
)
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component


async def test_abort_without_alexa(hass: HomeAssistant) -> None:
    """§1.1: alexa_devices must be loaded."""
    hass.config.components.add("alexa_devices")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "alexa_not_loaded"


async def test_user_flow(hass: HomeAssistant, alexa) -> None:
    """§2.2: only speakers are offered; groups excluded."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    offered = result["data_schema"].schema[CONF_SPEAKERS].config["options"]
    assert {o["value"] for o in offered} == {"S1", "S2", "S3"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SPEAKERS: [], CONF_VOLUME_MODE: "same"}
    )
    assert result["errors"] == {CONF_SPEAKERS: "no_speakers_selected"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_SPEAKERS: ["S1", "S2"], CONF_VOLUME_MODE: "proportional"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_SPEAKERS] == ["S1", "S2"]
    assert sorted(result["options"][CONF_KNOWN_SPEAKERS]) == ["S1", "S2", "S3"]


async def test_options_settings(hass: HomeAssistant, setup) -> None:
    """§2.4: change speakers; entry reloads."""
    result = await hass.config_entries.options.async_init(setup.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SPEAKERS: ["S1"], CONF_VOLUME_MODE: "same"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert setup.options[CONF_SPEAKERS] == ["S1"]
    assert hass.states.get("media_player.echo_due_group").state == "unavailable"


async def test_options_manual_mapping(hass: HomeAssistant, setup) -> None:
    """§3.3: manual mapping saved, empty removes it."""
    result = await hass.config_entries.options.async_init(setup.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "manual"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"group": "G12"}
    )
    assert result["step_id"] == "manual_members"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"members": ["S1", "S3"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert setup.options[CONF_MANUAL_GROUPS] == {"G12": ["S1", "S3"]}


async def test_new_speaker_repair(hass: HomeAssistant, alexa, setup) -> None:
    """§2.5: a new Echo raises a fixable issue; fixing adds it."""
    assert await async_setup_component(hass, "repairs", {})
    alexa.add_speaker("S4", "Echo Quattro")
    await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "new_speaker_S4")
    assert issue is not None and issue.is_fixable

    from custom_components.alexa_speaker_groups.repairs import async_create_fix_flow

    flow = await async_create_fix_flow(hass, issue.issue_id, issue.data)
    flow.hass = hass
    result = await flow.async_step_init()
    assert result["step_id"] == "confirm"
    result = await flow.async_step_confirm({"action": "add"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert "S4" in setup.options[CONF_SPEAKERS]
    assert hass.states.get("media_player.echo_quattro_group") is not None


async def test_new_speaker_ignore(hass: HomeAssistant, alexa, setup) -> None:
    """§2.5: ignoring marks it known without adding it."""
    alexa.add_speaker("S5", "Echo Cinque")
    await hass.async_block_till_done()
    from custom_components.alexa_speaker_groups.repairs import async_create_fix_flow

    issue = ir.async_get(hass).async_get_issue(DOMAIN, "new_speaker_S5")
    flow = await async_create_fix_flow(hass, issue.issue_id, issue.data)
    flow.hass = hass
    await flow.async_step_confirm({"action": "ignore"})
    await hass.async_block_till_done()
    assert "S5" not in setup.options[CONF_SPEAKERS]
    assert "S5" in setup.options[CONF_KNOWN_SPEAKERS]
