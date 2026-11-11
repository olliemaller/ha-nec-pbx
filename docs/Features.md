# Features

Everything belongs to one device, named after the integration (for example *House phones*).

## Sensors

| Entity | State | Notes |
|---|---|---|
| Last call | Time the call started | Attributes below |
| Last missed call | Time of the last unanswered incoming call | Attributes below |
| *Room* last call | Time of the last call on that extension | One per extension in the options |
| Calls today | Number of calls since midnight | Resets at midnight |
| Missed calls today | Number of missed calls since midnight | Resets at midnight |
| Recent calls | Number of calls in the list | `calls` attribute: the last 20 |
| Last call log line | The raw line from the phone system | Diagnostic, for checking the parser |

The *last call* sensors keep their value and attributes over a restart.

## Call attributes

| Attribute | Example | |
|---|---|---|
| `direction` | `incoming`, `outgoing`, `internal` | |
| `number` | `0412345678` | Outside number. Ends in `X` if the phone system hides digits. |
| `caller_name` | `Mum` | From the phonebook |
| `station` | `103` | The extension |
| `station_name` | `Oliver` | From the extensions list |
| `duration` | `155` | Seconds talking |
| `ring_time` | `12` | Seconds ringing, when the phone system reports it |
| `trunk` | `001` | The outside line |
| `answered` | `true` | |
| `missed` | `false` | Incoming and not answered |

## Binary sensor

| Entity | |
|---|---|
| Call log connection | On while Home Assistant is connected to the SMDR port. Attributes: `lines_received`, `last_error`. |

## Event entity

| Entity | Fires | Event types |
|---|---|---|
| Call | Once for every finished call | `incoming`, `missed`, `outgoing`, `internal`, `other` |

Each event carries `start`, `number`, `caller_name`, `station`, `station_name`, `duration`, `ring_time`, `trunk` and `answered`. A missed call is typed `missed`, not `incoming`. The state is the time of the last call.

## Events on the event bus

`nec_pbx_call` for every call, and `nec_pbx_missed_call` for missed ones, with every attribute above plus the raw line. See [Automations](Automations.md).

## What it can't do

The phone system writes a record when a call ends, so there is no "ringing now" or "on a call now" state. That needs NEC's CTI licence.
