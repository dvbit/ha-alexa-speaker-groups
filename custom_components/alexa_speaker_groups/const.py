"""Constants for Alexa Speaker Groups.

Spec references (docs/SPEC.md) are given as "§<section>".
"""

from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "alexa_speaker_groups"
LOGGER = logging.getLogger(__package__)

# §1.1 - the integration builds on top of the core "alexa_devices" integration.
ALEXA_DOMAIN: Final = "alexa_devices"

# §3.1 - aioamazondevices device family used for Alexa multi-room (WHA) groups.
SPEAKER_GROUP_FAMILY: Final = "WHA"
# §3.3 - registry fallback: model shown by alexa_devices for speaker groups.
SPEAKER_GROUP_MODEL: Final = "Speaker Group"

# Unique-id suffixes used by alexa_devices entities: "<serial>-<key>".
ALEXA_KEY_MEDIA: Final = "media"
ALEXA_KEY_SPEAK: Final = "speak"
ALEXA_KEY_ANNOUNCE: Final = "announce"

# Config entry options (§2).
CONF_SPEAKERS: Final = "speakers"  # managed speaker serials (§2.2)
CONF_KNOWN_SPEAKERS: Final = "known_speakers"  # serials already offered (§2.5)
CONF_VOLUME_MODE: Final = "volume_mode"  # §2.3
CONF_MANUAL_GROUPS: Final = "manual_groups"  # {group_serial: [serials]} (§3.3)
CONF_GROUP: Final = "group"
CONF_MEMBERS: Final = "members"
CONF_ACTION: Final = "action"

VOLUME_MODE_SAME: Final = "same"
VOLUME_MODE_PROPORTIONAL: Final = "proportional"
VOLUME_MODES: Final = [VOLUME_MODE_SAME, VOLUME_MODE_PROPORTIONAL]

ACTION_ADD: Final = "add"
ACTION_IGNORE: Final = "ignore"

# Repairs (§2.5, §3.3).
ISSUE_MEMBERSHIP: Final = "membership_unavailable"
ISSUE_NEW_SPEAKER_PREFIX: Final = "new_speaker_"

# §4.3 - persisted group composition.
STORAGE_VERSION: Final = 1
STORAGE_KEY_TEMPLATE: Final = DOMAIN + ".{entry_id}"
