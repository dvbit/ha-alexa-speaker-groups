# Alexa Speaker Groups

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
![Versione](https://img.shields.io/badge/versione-1.0.0-blue)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.10%2B-03a9f4)

🇬🇧 [Read in English](README.md)

**Raggruppamento dinamico** stile Sonos (join / unjoin) per gli Echo dell'integrazione
core [Alexa Devices](https://www.home-assistant.io/integrations/alexa_devices/).

Amazon non offre API pubbliche per creare gruppi multi-room al volo, quindi
l'integrazione usa un approccio **ibrido**:

| Gli speaker uniti… | Cosa succede | Sincrono |
|---|---|---|
| coincidono esattamente con un gruppo multi-room creato nell'app Alexa | i comandi vanno a quel gruppo Alexa | ✅ sincronizzato |
| qualsiasi altra combinazione | i comandi vanno a ogni speaker in sequenza | ⚠️ non sincronizzato |

> 💡 Crea nell'app Alexa i gruppi multi-room che usi più spesso (es. *Cucina +
> Soggiorno*): ogni volta che in Home Assistant unisci esattamente quegli speaker,
> la riproduzione è sincronizzata automaticamente.

## Funzionalità
- Un **media player gemello** per ogni Echo (`media_player.<echo>_group`) con
  **join/unjoin** standard, visibile nella pagina del dispositivo Echo.
- Entità notify **Parla** e **Annuncio** per ogni gemello, che seguono il gruppo.
- `play_media` con `announce: true` pronuncia il testo su tutto il gruppo.
- Volume di gruppo: **uguale** su tutti i membri o **proporzionale** (mantiene i livelli
  relativi).
- Membri dei gruppi Alexa letti automaticamente; **mappatura manuale** di riserva.
- I nuovi Echo vengono proposti tramite **Riparazioni** (aggiungi o ignora).
- I gruppi sopravvivono ai riavvii. Tradotta in EN, IT, FR, ES, DE.

## Requisiti
- Home Assistant **2026.10.0** o successivo.
- Integrazione core **Alexa Devices** configurata e funzionante.

## Installazione (HACS)
1. HACS → ⋮ → *Repository personalizzati* → aggiungi
   `https://github.com/dvbit/ha-alexa-speaker-groups`, categoria **Integrazione**.
2. Installa **Alexa Speaker Groups** e riavvia Home Assistant.
3. *Impostazioni → Dispositivi e servizi → Aggiungi integrazione → Alexa Speaker Groups*.
4. Scegli gli speaker da gestire e la modalità del volume di gruppo.

## Entità
Per ogni Echo scelto (es. *Alexa Cucina*):

| Entità | Scopo |
|---|---|
| `media_player.alexa_cucina_group` | player gemello raggruppabile |
| `notify.alexa_cucina_group_speak` | parla sul gruppo corrente |
| `notify.alexa_cucina_group_announce` | annuncio (suono + testo) sul gruppo corrente |

Attributi extra del player gemello: `synchronized` (true/false) e `alexa_group`
(l'entità del gruppo Alexa in uso, se presente).

## Esempi d'uso

### Raggruppare gli speaker
```yaml
action: media_player.join
target:
  entity_id: media_player.alexa_cucina_group
data:
  group_members:
    - media_player.alexa_soggiorno_group
```
`media_player.alexa_cucina_group` diventa il **leader**. Per uscire dal gruppo:
```yaml
action: media_player.unjoin
target:
  entity_id: media_player.alexa_soggiorno_group
```

### Musica sul gruppo
`media_content_type` è il provider musicale Alexa, come in Alexa Devices.
```yaml
action: media_player.play_media
target:
  entity_id: media_player.alexa_cucina_group
data:
  media_content_type: AMAZON_MUSIC
  media_content_id: jazz rilassante
```

### Parlare o annunciare sul gruppo
```yaml
action: notify.send_message
target:
  entity_id: notify.alexa_cucina_group_announce
data:
  message: La cena è pronta!
```
oppure con il media player:
```yaml
action: media_player.play_media
target:
  entity_id: media_player.alexa_cucina_group
data:
  media_content_type: music
  media_content_id: La cena è pronta!
  announce: true
```

### Automazione: musica del mattino in zona giorno
```yaml
automation:
  - alias: Musica del mattino
    triggers:
      - trigger: time
        at: "07:30:00"
    actions:
      - action: media_player.join
        target:
          entity_id: media_player.alexa_cucina_group
        data:
          group_members:
            - media_player.alexa_soggiorno_group
      - action: media_player.volume_set
        target:
          entity_id: media_player.alexa_cucina_group
        data:
          volume_level: 0.3
      - action: media_player.play_media
        target:
          entity_id: media_player.alexa_cucina_group
        data:
          media_content_type: AMAZON_MUSIC
          media_content_id: playlist del mattino
```

### Dashboard
Qualsiasi card media funziona; la finestra di raggruppamento è nel more-info del
gemello:
```yaml
type: media-control
entity: media_player.alexa_cucina_group
```

## Dettagli di comportamento
- **Volume**: sul **leader** regola tutto il gruppo (il leader mostra la media); su
  ogni altro membro regola solo quello speaker.
- I **comandi di riproduzione** inviati a un membro agiscono su tutto il gruppo.
- **TTS su un gruppo sincronizzato**: usa sempre *Annuncio* (con il suono): i gruppi
  Alexa non hanno *Parla*.
- Gli annunci richiedono **testo**: URL e id `media-source://` vengono rifiutati.
- Play/Pausa/Successivo/Precedente compaiono solo quando Alexa li segnala disponibili.

## Opzioni
*Impostazioni → Dispositivi e servizi → Alexa Speaker Groups → Configura*:
- **Speaker e volume** – modifica gli speaker gestiti e la modalità del volume.
- **Mappatura manuale gruppi Alexa** – imposta a mano i membri di un gruppo Alexa.
  Serve solo se il rilevamento automatico fallisce (lo segnala una voce in
  Riparazioni); la mappatura manuale prevale sui dati automatici per quel gruppo, una
  selezione vuota la rimuove.

## Limiti
- I membri dei gruppi sono letti da **dati interni** di Alexa Devices: una modifica
  futura del core potrebbe romperne la lettura. Riceverai una voce in Riparazioni e
  potrai usare la mappatura manuale.
- La riproduzione a ventaglio **non è sincronizzata** ed è soggetta ai limiti di
  richieste di Amazon.
- Fire TV e tablet Fire non hanno media player e non vengono proposti.

## Log
```yaml
logger:
  logs:
    custom_components.alexa_speaker_groups: debug
```

## Specifica
Vedi [docs/SPEC.md](docs/SPEC.md).

## Licenza
MIT
