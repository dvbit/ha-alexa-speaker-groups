"""Fixtures: a fake, already-loaded alexa_devices with three Echos and one group."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
)

from custom_components.alexa_speaker_groups.const import (
    CONF_KNOWN_SPEAKERS,
    CONF_MANUAL_GROUPS,
    CONF_SPEAKERS,
    CONF_VOLUME_MODE,
    DOMAIN,
    VOLUME_MODE_SAME,
)
from custom_components.alexa_speaker_groups.manager import GroupManager
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er

ALEXA = "alexa_devices"
# serial -> (name, is_group)
SPEAKERS = {"S1": "Echo Uno", "S2": "Echo Due", "S3": "Echo Tre"}
GROUP = ("G12", "Gruppo Uno Due", frozenset({"S1", "S2"}))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> None:
    """Enable custom integrations."""


@dataclass
class FakeAlexa:
    """Handles to the fake alexa_devices world."""

    hass: HomeAssistant
    entry: MockConfigEntry
    devices: dict[str, Any] = field(default_factory=dict)

    def mp(self, serial: str) -> str:
        """alexa media_player entity_id."""
        return er.async_get(self.hass).async_get_entity_id(
            "media_player", ALEXA, f"{serial}-media"
        )

    def notify(self, serial: str, key: str) -> str | None:
        """alexa notify entity_id."""
        return er.async_get(self.hass).async_get_entity_id(
            "notify", ALEXA, f"{serial}-{key}"
        )

    def set_volume(self, serial: str, volume: float, state: str = "idle") -> None:
        """Set a fake media_player state."""
        self.hass.states.async_set(
            self.mp(serial),
            state,
            {"volume_level": volume, "is_volume_muted": False, "supported_features": 0},
        )

    def add_speaker(self, serial: str, name: str) -> None:
        """Register an Echo device with media_player and notify entities."""
        device = dr.async_get(self.hass).async_get_or_create(
            config_entry_id=self.entry.entry_id,
            identifiers={(ALEXA, serial)},
            name=name,
            model="Echo Dot",
        )
        ent = er.async_get(self.hass)
        ent.async_get_or_create(
            "media_player",
            ALEXA,
            f"{serial}-media",
            config_entry=self.entry,
            device_id=device.id,
            suggested_object_id=f"alexa_{serial.lower()}",
        )
        for key in ("speak", "announce"):
            ent.async_get_or_create(
                "notify",
                ALEXA,
                f"{serial}-{key}",
                config_entry=self.entry,
                device_id=device.id,
                suggested_object_id=f"alexa_{serial.lower()}_{key}",
            )
        self.devices[serial] = SimpleNamespace(
            device_family="ECHO", device_cluster_members={serial: "T"}
        )
        self.set_volume(serial, 0.4)

    def add_group(self, serial: str, name: str, members: frozenset[str]) -> None:
        """Register an Alexa speaker group (only Announce, no Speak)."""
        device = dr.async_get(self.hass).async_get_or_create(
            config_entry_id=self.entry.entry_id,
            identifiers={(ALEXA, serial)},
            name=name,
            model="Speaker Group",
        )
        ent = er.async_get(self.hass)
        ent.async_get_or_create(
            "media_player",
            ALEXA,
            f"{serial}-media",
            config_entry=self.entry,
            device_id=device.id,
            suggested_object_id=f"alexa_{serial.lower()}",
        )
        ent.async_get_or_create(
            "notify",
            ALEXA,
            f"{serial}-announce",
            config_entry=self.entry,
            device_id=device.id,
            suggested_object_id=f"alexa_{serial.lower()}_announce",
        )
        self.devices[serial] = SimpleNamespace(
            device_family="WHA", device_cluster_members={m: "T" for m in members}
        )
        self.hass.states.async_set(
            self.mp(serial), "idle", {"volume_level": 0.5, "supported_features": 0}
        )


@pytest.fixture
async def alexa(hass: HomeAssistant) -> FakeAlexa:
    """Fake loaded alexa_devices entry with 3 speakers and 1 group."""
    hass.config.components.add(ALEXA)  # satisfy the manifest dependency
    entry = MockConfigEntry(domain=ALEXA, state=ConfigEntryState.LOADED)
    entry.add_to_hass(hass)
    fake = FakeAlexa(hass, entry)
    entry.runtime_data = SimpleNamespace(data=fake.devices)
    for serial, name in SPEAKERS.items():
        fake.add_speaker(serial, name)
    fake.add_group(*GROUP)
    return fake


@pytest.fixture
def options() -> dict[str, Any]:
    """Default options: all three speakers managed."""
    return {
        CONF_SPEAKERS: list(SPEAKERS),
        CONF_KNOWN_SPEAKERS: list(SPEAKERS),
        CONF_VOLUME_MODE: VOLUME_MODE_SAME,
        CONF_MANUAL_GROUPS: {},
    }


@pytest.fixture
async def setup(
    hass: HomeAssistant, alexa: FakeAlexa, options: dict[str, Any]
) -> MockConfigEntry:
    """Set up alexa_speaker_groups."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@dataclass
class Call:
    """A forwarded call to alexa_devices."""

    service: str  # "<domain>.<service>"
    targets: list[str]
    data: dict[str, Any]


@pytest.fixture
def calls(setup: MockConfigEntry) -> list[Call]:
    """Record what the manager forwards to alexa_devices (no real calls)."""
    recorded: list[Call] = []

    async def _fake(self, domain, service, targets, data=None):
        if not targets:
            raise HomeAssistantError("no target")
        recorded.append(Call(f"{domain}.{service}", list(targets), dict(data or {})))

    with patch.object(GroupManager, "_async_call", _fake):
        yield recorded


def last(calls: list[Call], service: str) -> Call:
    """Return the last recorded call of a service."""
    return [c for c in calls if c.service == service][-1]
