# Alexa Speaker Groups v1.2.0 — Specification

Original consolidated requirement agreed before implementation. Section numbers
(§) are referenced from the code comments. Clarifications added during
implementation are marked **[impl]**.

**Repository:** `dvbit/ha-alexa-speaker-groups` · **Domain:** `alexa_speaker_groups` ·
**Minimum Home Assistant:** 2026.10.0 · **Instance:** generic (tested against a real
installation's data)

## Approach

Hybrid dynamic grouping (Sonos-style join/unjoin) for the Echo speakers of the core
`alexa_devices` integration:

- **synchronized** playback when the joined speakers exactly match a multi-room group
  created in the Alexa app;
- otherwise **fan-out** (each speaker receives the command, not synchronized).

Amazon offers no public API to create or change multi-room groups; this integration
never tries to.

## 1. Context
- 1.1 Builds on the core `alexa_devices` integration. No separate Amazon login.
- 1.2 Nothing hard-coded: speakers and groups are discovered on every installation.

## 2. Configuration (UI only)
- 2.1 A single config entry (`single_config_entry`).
- 2.2 Setup step: choose the speakers to manage. Only single devices that have a
  `media_player` are offered; groups and devices without one (Fire TV, Fire tablets)
  are excluded.
- 2.3 Group volume mode: `same` or `proportional`.
- 2.4 Options flow changes speakers and volume mode, then reloads automatically.
- 2.5 A speaker found later raises a **Repairs** entry with a fix flow: add or ignore.
  Until confirmed it gets no twin.

## 3. Alexa group membership
- 3.1 Read automatically from `alexa_devices` internal data (coordinator
  `runtime_data`, aioamazondevices `device_family == "WHA"` and
  `device_cluster_members`). Serials map to devices through the registries.
- 3.2 Refreshed whenever `alexa_devices` updates its data. **[impl]** Read live at
  every routing decision, so it always reflects the latest refresh.
- 3.3 If reading fails: Repairs entry + manual mapping in the options.
  **[impl]** A manual mapping for a group always overrides automatic data for that
  group; an empty selection removes the override.

## 4. Entities
- 4.1 Per speaker: a twin `media_player` with `GROUPING` and `group_members`, plus
  join/unjoin from the standard UI. **[impl]** Twins are attached to the Echo device
  through `entity.device_entry` (HA 2026.x: one config entry per device). Only twins
  can be joined.
- 4.2 Per twin: `notify` entities **Speak** and **Announce** that follow the group.
- 4.3 The current group is restored after a restart (stored in `.storage`).

## 5. Routing
- 5.1 The members, leader included, **exactly match** an Alexa group: commands go to
  that group's entities → **synchronized**.
- 5.2 No match: commands go to each member in turn → **not synchronized**, WARNING
  logged.
- 5.3 TTS on a matched group always uses **Announce** (Speak does not exist on
  groups; DEBUG log). `play_media` with `announce: true` follows the TTS path
  (`media_content_id` is the text). **[impl]** URLs / `media-source://` ids are
  rejected: Alexa cannot play arbitrary audio this way.
- 5.4 Volume is applied to each member using the chosen mode; the group shows the
  average. **[impl]** Volume/mute on the **leader** twin acts on the whole group (and
  the leader shows the average); on any other member it acts only on that speaker,
  so the per-member sliders of the grouping UI keep working.
- 5.5 The twin's state mirrors the entity actually in use: the Alexa group (5.1) or
  the leader's speaker (5.2). **[impl]** Play/Pause/Next/Previous are offered only when
  the entity in use offers them (alexa_devices enables them dynamically). Playback
  commands sent to any member of a group act on the whole group.

- 5.6 **[impl 1.2.0]** A member whose Alexa `media_player` is unavailable is removed
  from its group (WARNING log): HA skips entity services for unavailable entities, so
  it could otherwise never leave and would block the exact match of §5.1.

## 6. Logging
- DEBUG: membership read (on change), routing decisions, commands sent.
- INFO: setup, join/unjoin, matched group, new speaker found.
- WARNING: playback not synchronized, missing entity.
- ERROR: membership unreadable, command rejected.

## 7. Packaging
HACS, localization en/it/fr/es/de, README in English and Italian with examples, icon,
this specification, CI workflows (hassfest, HACS, lint, tests).
