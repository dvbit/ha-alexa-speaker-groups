"""Tests for routing, grouping, volume, TTS and persistence (spec §4, §5)."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.alexa_speaker_groups.const import (
    CONF_MANUAL_GROUPS,
    CONF_VOLUME_MODE,
    DOMAIN,
    ISSUE_MEMBERSHIP,
    VOLUME_MODE_PROPORTIONAL,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import issue_registry as ir

from .conftest import last

T1, T2, T3 = (
    "media_player.echo_uno_group",
    "media_player.echo_due_group",
    "media_player.echo_tre_group",
)


async def _join(hass: HomeAssistant, leader: str, members: list[str]) -> None:
    await hass.services.async_call(
        "media_player",
        "join",
        {"entity_id": leader, "group_members": members},
        blocking=True,
    )


async def test_twins_created(hass: HomeAssistant, setup, alexa) -> None:
    """§4.1/§4.2: one twin player + speak/announce per speaker, ungrouped."""
    for twin in (T1, T2, T3):
        state = hass.states.get(twin)
        assert state is not None
        assert state.attributes["group_members"] == [twin]
    assert hass.states.get("notify.echo_uno_group_speak")
    assert hass.states.get("notify.echo_uno_group_announce")
    # The group itself never gets a twin.
    assert hass.states.get("media_player.gruppo_uno_due_group") is None


async def test_matching_group_is_synchronized(hass, alexa, calls) -> None:
    """§5.1: exact match -> commands go to the Alexa group entity."""
    await _join(hass, T1, [T2])
    state = hass.states.get(T1)
    assert state.attributes["group_members"] == [T1, T2]
    assert state.attributes["synchronized"] is True
    assert hass.states.get(T2).attributes["group_members"] == [T1, T2]

    # A command on a member is routed to the whole group too.
    await hass.services.async_call(
        "media_player", "media_stop", {"entity_id": T2}, blocking=True
    )
    assert last(calls, "media_player.media_stop").targets == [alexa.mp("G12")]


async def test_non_matching_group_fans_out(hass, alexa, calls, caplog) -> None:
    """§5.2: no exact match -> each member, with a WARNING."""
    await _join(hass, T1, [T3])
    assert hass.states.get(T1).attributes["synchronized"] is False
    assert "playback will not be synchronized" in caplog.text
    await hass.services.async_call(
        "media_player",
        "play_media",
        {
            "entity_id": T1,
            "media_content_type": "AMAZON_MUSIC",
            "media_content_id": "jazz",
        },
        blocking=True,
    )
    call = last(calls, "media_player.play_media")
    assert call.targets == [alexa.mp("S1"), alexa.mp("S3")]
    assert call.data["media_content_id"] == "jazz"


async def test_unavailable_member_is_dropped(hass, alexa, calls, caplog) -> None:
    """Regression 1.2.0: an unavailable speaker must not stay stuck in a group.

    HA skips entity services for unavailable entities, so unjoin could never
    reach it and the exact match with an Alexa group (§5.1) was lost.
    """
    await _join(hass, T1, [T2, T3])
    hass.states.async_set(alexa.mp("S3"), "unavailable")
    await hass.async_block_till_done()
    assert hass.states.get(T1).attributes["group_members"] == [T1, T2]
    assert hass.states.get(T1).attributes["synchronized"] is True
    assert "Speaker S3 is unavailable" in caplog.text


async def test_superset_is_not_a_match(hass, alexa, calls) -> None:
    """§5.1: only an exact member set matches."""
    await _join(hass, T1, [T2, T3])
    await hass.services.async_call(
        "media_player", "media_stop", {"entity_id": T1}, blocking=True
    )
    assert len(last(calls, "media_player.media_stop").targets) == 3


async def test_tts_on_group_uses_announce(hass, alexa, calls) -> None:
    """§5.3: Speak on a matched group goes to the group's Announce."""
    await _join(hass, T1, [T2])
    await hass.services.async_call(
        "notify",
        "send_message",
        {"entity_id": "notify.echo_uno_group_speak", "message": "Ciao"},
        blocking=True,
    )
    call = last(calls, "notify.send_message")
    assert call.targets == [alexa.notify("G12", "announce")]
    assert call.data["message"] == "Ciao"


async def test_tts_fan_out_keeps_speak(hass, alexa, calls) -> None:
    """§4.2: unmatched group -> Speak on every member."""
    await _join(hass, T1, [T3])
    await hass.services.async_call(
        "notify",
        "send_message",
        {"entity_id": "notify.echo_tre_group_speak", "message": "Ciao"},
        blocking=True,
    )
    assert last(calls, "notify.send_message").targets == [
        alexa.notify("S1", "speak"),
        alexa.notify("S3", "speak"),
    ]


async def test_play_media_announce(hass, alexa, calls) -> None:
    """§5.3: play_media announce=True follows the TTS path; URLs refused."""
    await hass.services.async_call(
        "media_player",
        "play_media",
        {
            "entity_id": T3,
            "media_content_type": "music",
            "media_content_id": "Cena pronta",
            "announce": True,
        },
        blocking=True,
    )
    assert last(calls, "notify.send_message").targets == [
        alexa.notify("S3", "announce")
    ]
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "media_player",
            "play_media",
            {
                "entity_id": T3,
                "media_content_type": "music",
                "media_content_id": "https://x/y.mp3",
                "announce": True,
            },
            blocking=True,
        )


async def test_volume_same_mode(hass, alexa, calls) -> None:
    """§5.4: leader volume applies to all; member volume only to itself."""
    alexa.set_volume("S1", 0.2)
    alexa.set_volume("S2", 0.6)
    await _join(hass, T1, [T2])
    await hass.async_block_till_done()
    assert hass.states.get(T1).attributes["volume_level"] == 0.4  # average

    await hass.services.async_call(
        "media_player",
        "volume_set",
        {"entity_id": T1, "volume_level": 0.5},
        blocking=True,
    )
    sets = {
        c.targets[0]: c.data["volume_level"]
        for c in calls
        if c.service == "media_player.volume_set"
    }
    assert sets == {alexa.mp("S1"): 0.5, alexa.mp("S2"): 0.5}

    calls.clear()
    await hass.services.async_call(
        "media_player",
        "volume_set",
        {"entity_id": T2, "volume_level": 0.3},
        blocking=True,
    )
    assert [c.targets for c in calls] == [[alexa.mp("S2")]]


@pytest.mark.parametrize(
    "options",
    [
        {
            "speakers": ["S1", "S2", "S3"],
            "known_speakers": ["S1", "S2", "S3"],
            CONF_VOLUME_MODE: VOLUME_MODE_PROPORTIONAL,
            CONF_MANUAL_GROUPS: {},
        }
    ],
)
async def test_volume_proportional_mode(hass, alexa, calls) -> None:
    """§2.3/§5.4: proportional keeps relative levels."""
    alexa.set_volume("S1", 0.2)
    alexa.set_volume("S2", 0.6)
    await _join(hass, T1, [T2])
    await hass.services.async_call(
        "media_player",
        "volume_set",
        {"entity_id": T1, "volume_level": 0.8},
        blocking=True,
    )
    sets = {
        c.targets[0]: c.data["volume_level"]
        for c in calls
        if c.service == "media_player.volume_set"
    }
    assert sets == {alexa.mp("S1"): 0.4, alexa.mp("S2"): 1.0}  # 0.2*2, 0.6*2 clamped


async def test_unjoin_promotes_leader(hass, alexa, calls) -> None:
    """§4.1: leader leaves -> next member leads; 1 left -> dissolved."""
    await _join(hass, T1, [T2, T3])
    await hass.services.async_call(
        "media_player", "unjoin", {"entity_id": T1}, blocking=True
    )
    assert hass.states.get(T2).attributes["group_members"] == [T2, T3]
    assert hass.states.get(T1).attributes["group_members"] == [T1]
    await hass.services.async_call(
        "media_player", "unjoin", {"entity_id": T3}, blocking=True
    )
    assert hass.states.get(T2).attributes["group_members"] == [T2]


async def test_join_moves_member_between_groups(hass, alexa, calls) -> None:
    """A speaker joining a new group leaves its previous one."""
    await _join(hass, T1, [T2])
    await _join(hass, T3, [T2])
    assert hass.states.get(T3).attributes["group_members"] == [T3, T2]
    assert hass.states.get(T1).attributes["group_members"] == [T1]


async def test_join_rejects_foreign_entity(hass, alexa, calls) -> None:
    """Only twins can be joined."""
    with pytest.raises(ServiceValidationError):
        await _join(hass, T1, [alexa.mp("S2")])


async def test_state_mirrors_group(hass, alexa, calls) -> None:
    """§5.5: grouped twin shows the Alexa group's playback."""
    await _join(hass, T1, [T2])
    hass.states.async_set(
        alexa.mp("G12"),
        "playing",
        {"media_title": "Blue in Green", "supported_features": 1 | 16384},
    )
    await hass.async_block_till_done()
    state = hass.states.get(T2)
    assert state.state == "playing"
    assert state.attributes["media_title"] == "Blue in Green"


async def test_groups_restored_after_reload(hass, alexa, setup, calls) -> None:
    """§4.3: groups survive a reload."""
    await _join(hass, T1, [T2])
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(setup.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(T1).attributes["group_members"] == [T1, T2]


async def test_membership_failure_uses_manual(hass, alexa, setup, calls) -> None:
    """§3.3: unreadable runtime data -> Repairs issue + manual mapping."""
    alexa.entry.runtime_data = object()  # no .data -> AttributeError
    hass.config_entries.async_update_entry(
        setup, options={**setup.options, CONF_MANUAL_GROUPS: {"G12": ["S1", "S3"]}}
    )
    await hass.async_block_till_done()
    await _join(hass, T1, [T3])
    await hass.services.async_call(
        "media_player", "media_stop", {"entity_id": T1}, blocking=True
    )
    assert last(calls, "media_player.media_stop").targets == [alexa.mp("G12")]
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_MEMBERSHIP) is not None


async def test_unload(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    """Entry unloads cleanly."""
    assert await hass.config_entries.async_unload(setup.entry_id)
