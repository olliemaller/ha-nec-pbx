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
| Talk time today | Time spent on answered calls since midnight, in minutes | Resets at midnight; long-term statistics work |
| Recent calls | Number of calls in the list | `calls` attribute: the last 20 |
| Last call log line | The raw line from the phone system | Diagnostic, for checking the parser |

The *last call* sensors and the daily totals keep their values over a restart. The recent-calls list and the connection counters aren't written to the recorder database, because they change with every call.

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

## Logbook

Every call gets a line in the logbook under the phone system's name, for example *Teak phones: missed call from Sam (0491570157) to Family, rang 21 s* or *Teak phones: Oliver called Alex (0491570156), 2 min 35 s*. Calls the phone system replays after a reconnect don't add logbook lines.

## Repairs

If Home Assistant can't reach the call log for 10 minutes, a **Repairs** warning says so, with the last error. It clears itself when the connection comes back. No calls are lost in between: the phone system keeps them and sends them on reconnect.

## What it can't do

The phone system writes a record when a call ends, so there is no "ringing now" or "on a call now" state. That needs NEC's CTI licence.
