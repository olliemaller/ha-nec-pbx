# Automations

## Missed call blueprint

The quickest way to get a notification on your phone:

[![Import the blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Folliemaller%2Fha-nec-pbx%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fnec_pbx%2Fmissed_call_notification.yaml)

Pick the **Call** entity and your phone. The message reads like "Alex at 6:12 pm (rang Family)".

## The Call event entity

In the automation editor, add an **Event received** trigger, pick the **Call** entity and tick the call types you want. No YAML needed. As YAML (Home Assistant 2026.7 or newer):

```yaml
triggers:
  - trigger: event.received
    target:
      entity_id: event.house_phones_call
    options:
      event_type:
        - missed
```

The call's details are in `trigger.to_state.attributes`, for example `{{ trigger.to_state.attributes.caller_name }}`. On older Home Assistant, use a **State** trigger on the entity with a **State** condition on its `event_type` attribute.

## Events

| Event | When |
|---|---|
| `nec_pbx_call` | Every finished call |
| `nec_pbx_missed_call` | An incoming call nobody answered |

Both carry `start`, `direction`, `call_class`, `number`, `caller_name`, `station`, `station_name`, `duration`, `ring_time`, `trunk`, `answered`, `missed`, `cost`, `flags`, `raw` and `entry_id`. See [call attributes](Features.md#call-attributes) for what each one holds. `direction` can also be `unknown` when the line doesn't say.

## Missed call notification

```yaml
alias: Missed call on the home phone
triggers:
  - trigger: event
    event_type: nec_pbx_missed_call
actions:
  - action: notify.notify
    data:
      title: Missed call
      message: >-
        {{ trigger.event.data.caller_name
           or trigger.event.data.number
           or 'Unknown caller' }}
        at {{ as_timestamp(trigger.event.data.start) | timestamp_custom('%-I:%M %p') }}
mode: queued
```

## Only calls from someone in the phonebook

```yaml
triggers:
  - trigger: event
    event_type: nec_pbx_call
conditions:
  - condition: template
    value_template: "{{ trigger.event.data.caller_name is not none }}"
```

## A call to one room

```yaml
triggers:
  - trigger: event
    event_type: nec_pbx_call
    event_data:
      station: "103"
      direction: incoming
```

## Dashboard: recent calls

A Markdown card that lists the recent calls (replace the entity ID with yours):

```yaml
type: markdown
title: Recent calls
content: >-
  {% for c in state_attr('sensor.house_phones_recent_calls', 'calls') or [] %}
  {{ 'Missed' if c.missed else ('In' if c.direction == 'incoming' else 'Out') }}:
  **{{ c.caller_name or c.number or c.station_name or c.station }}**
  · {{ as_timestamp(c.start) | timestamp_custom('%a %-I:%M %p') }}
  {% if c.station_name %}· {{ c.station_name }}{% endif %}

  {% endfor %}
```

## Announce who's calling

[![Import the blueprint.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Folliemaller%2Fha-nec-pbx%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fnec_pbx%2Fcaller_announcement.yaml)

Says *"Phone call from Alex"* on your speakers while the phone is still ringing, with quiet hours. Needs the FreePBX connection (see [Setup](Setup.md)) and a text-to-speech engine.

Both blueprints need Home Assistant 2026.7.0 or newer, for the event entity trigger.

## Save a caller to the phonebook

The `nec_pbx.save_caller` action adds a name to the phonebook: to the to-do list if you use one, otherwise to the phonebook in the options. It takes effect straight away, without a reload.

| Field | Required | |
|---|---|---|
| `name` | Yes | Who it is, for example `Plumber` |
| `number` | No | The number to save, for example `0491 570 156`. Leave it out to save the last incoming caller. A number the phone system hid (ending in `X`) can't be saved. |
| `config_entry_id` | No | Which phone system, if you have more than one |

It returns the `name` and `number` it saved, so a notification action can confirm it.

```yaml
action: nec_pbx.save_caller
data:
  name: Plumber
```

## Pause the music when someone answers

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.house_phones_on_a_call
    to: "on"
actions:
  - action: media_player.media_pause
    target:
      entity_id: media_player.kitchen
```
