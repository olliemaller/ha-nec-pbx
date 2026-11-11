# Automations

## Missed call blueprint

The quickest way to get a notification on your phone:

[![Import the blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Folliemaller%2Fha-nec-pbx%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fnec_pbx%2Fmissed_call_notification.yaml)

Pick the **Call** entity and your phone. The message reads like "Alex at 6:12 pm (rang Family)".

## The Call event entity

In the automation editor, add a **State** trigger on the **Call** entity, then a **State** condition on its `event_type` attribute. No YAML needed. As YAML:

```yaml
triggers:
  - trigger: state
    entity_id: event.house_phones_call
    not_from: unavailable
conditions:
  - condition: state
    entity_id: event.house_phones_call
    attribute: event_type
    state: missed
```

The call's details are attributes of the entity: `state_attr('event.house_phones_call', 'caller_name')`.

## Events

| Event | When |
|---|---|
| `nec_pbx_call` | Every finished call |
| `nec_pbx_missed_call` | An incoming call nobody answered |

Both carry `start`, `direction`, `number`, `caller_name`, `station`, `station_name`, `duration`, `ring_time`, `trunk`, `answered`, `missed`, `raw` and `entry_id`.

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
  {{ '📵' if c.missed else ('📥' if c.direction == 'incoming' else '📤') }}
  **{{ c.caller_name or c.number or c.station_name or c.station }}**
  · {{ as_timestamp(c.start) | timestamp_custom('%a %-I:%M %p') }}
  {% if c.station_name %}· {{ c.station_name }}{% endif %}

  {% endfor %}
```
