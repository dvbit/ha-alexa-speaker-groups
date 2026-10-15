# Alexa Speaker Groups

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
![Version](https://img.shields.io/badge/version-1.1.0-blue)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.10%2B-03a9f4)

🇮🇹 [Leggi in italiano](README.it.md)

Sonos-style **dynamic speaker grouping** (join / unjoin) for the Echo devices of the
core [Alexa Devices](https://www.home-assistant.io/integrations/alexa_devices/)
integration.

Amazon has no public API to create multi-room groups on the fly, so this integration
uses a **hybrid** approach:

| Speakers you join… | What happens | Sync |
|---|---|---|
| exactly match a multi-room group created in the Alexa app | commands go to that Alexa group | ✅ synchronized |
| any other combination | commands go to each speaker in turn | ⚠️ not synchronized |

> 💡 Create in the Alexa app the multi-room groups you use most (e.g. *Kitchen +
> Living room*): whenever you join exactly those speakers in Home Assistant, playback
> is synchronized automatically.

## Features
- One **twin media player** per Echo (`media_player.<echo>_group`) with standard
  **join/unjoin**, shown on the Echo's own device page.
- **Speak** and **Announce** notify entities per twin that follow the current group.
- `play_media` with `announce: true` speaks the text on the whole group.
- Group volume: **same** level on every member or **proportional** (keeps the relative
  levels).
- Alexa group membership read automatically; **manual mapping** fallback.
- New Echo devices are offered through **Repairs** (add or ignore).
- Groups survive restarts. Localized in EN, IT, FR, ES, DE.

## Requirements
- Home Assistant **2026.10.0** or later.
- The core **Alexa Devices** integration set up and working.

## Installation (HACS)
1. HACS → ⋮ → *Custom repositories* → add `https://github.com/dvbit/ha-alexa-speaker-groups`,
   category **Integration**.
2. Install **Alexa Speaker Groups** and restart Home Assistant.
3. *Settings → Devices & services → Add integration → Alexa Speaker Groups*.
4. Select the speakers to manage and the group volume mode.

## Entities
For each selected Echo (e.g. *Alexa Kitchen*):

| Entity | Purpose |
|---|---|
| `media_player.alexa_kitchen_group` | groupable twin player |
| `notify.alexa_kitchen_group_speak` | speak on the current group |
| `notify.alexa_kitchen_group_announce` | announce (chime + text) on the current group |

Extra attributes of the twin player: `synchronized` (true/false) and `alexa_group`
(the Alexa group entity in use, if any).

## Usage examples

### Group speakers
```yaml
action: media_player.join
target:
  entity_id: media_player.alexa_kitchen_group
data:
  group_members:
    - media_player.alexa_living_room_group
```
`media_player.alexa_kitchen_group` becomes the **leader**. Leave the group with:
```yaml
action: media_player.unjoin
target:
  entity_id: media_player.alexa_living_room_group
```

### Play music on the group
`media_content_type` is the Alexa music provider, as in Alexa Devices.
```yaml
action: media_player.play_media
target:
  entity_id: media_player.alexa_kitchen_group
data:
  media_content_type: AMAZON_MUSIC
  media_content_id: relaxing jazz
```

### Speak or announce on the group
```yaml
action: notify.send_message
target:
  entity_id: notify.alexa_kitchen_group_announce
data:
  message: Dinner is ready!
```
or with the media player:
```yaml
action: media_player.play_media
target:
  entity_id: media_player.alexa_kitchen_group
data:
  media_content_type: music
  media_content_id: Dinner is ready!
  announce: true
```

### Automation: morning music in the day zone
```yaml
automation:
  - alias: Morning music
    triggers:
      - trigger: time
        at: "07:30:00"
    actions:
      - action: media_player.join
        target:
          entity_id: media_player.alexa_kitchen_group
        data:
          group_members:
            - media_player.alexa_living_room_group
      - action: media_player.volume_set
        target:
          entity_id: media_player.alexa_kitchen_group
        data:
          volume_level: 0.3
      - action: media_player.play_media
        target:
          entity_id: media_player.alexa_kitchen_group
        data:
          media_content_type: AMAZON_MUSIC
          media_content_id: morning playlist
```

### Dashboard
Any media card works; the grouping dialog appears in the more-info of the twin:
```yaml
type: media-control
entity: media_player.alexa_kitchen_group
```

## Behaviour details
- **Volume**: on the **leader** it sets the whole group (the leader shows the
  average); on any other member it sets only that speaker.
- **Playback commands** sent to any member act on the whole group.
- **TTS on a synchronized group** always uses *Announce* (with the chime): Alexa
  groups have no *Speak*.
- Announcements need **text**: URLs and `media-source://` ids are rejected.
- Play/Pause/Next/Previous appear only when Alexa reports them as available.

## Options
*Settings → Devices & services → Alexa Speaker Groups → Configure*:
- **Speakers and volume** – change managed speakers and volume mode.
- **Manual Alexa group mapping** – set the members of an Alexa group by hand. Needed
  only if automatic detection fails (a Repairs entry tells you so); a manual mapping
  overrides automatic data for that group, an empty selection removes it.

## Limitations
- Group membership is read from **internal data** of Alexa Devices: a future core
  change may break it. You will get a Repairs entry and can use the manual mapping.
- Fan-out playback is **not synchronized** and is subject to Amazon rate limiting.
- Fire TV and Fire tablets have no media player and are not offered.

## Logging
```yaml
logger:
  logs:
    custom_components.alexa_speaker_groups: debug
```

## Specification
See [docs/SPEC.md](docs/SPEC.md).

## License
MIT
