# Features

The phone system is one device, named after the integration (for example *House phones*). Each extension you name gets its own device under it (for example *Oliver*), and so does each outside line you name.

## Sensors

| Entity | State | Notes |
|---|---|---|
| Last call | Time the call started | Attributes below |
| Last missed call | Time of the last unanswered incoming call | Attributes below |
| Calls today / this week / this month | Number of calls | Reset at midnight, on Monday and on the 1st |
| Missed calls today / this week / this month | Number of missed calls | Same |
| Talk time today / this week / this month | Time on answered calls, in minutes | Same; long-term statistics work |
| Longest call today | The longest answered call, in minutes | Resets at midnight |
| Unknown callers today | Incoming calls from numbers not in the phonebook | Resets at midnight |
| Recent calls | Number of calls in the list | `calls` attribute: the last 20 |
| Last call log line | The raw line from the phone system | Diagnostic, for checking the parser. Disabled by default because it holds callers' numbers; turn it on from the entity's settings |

The *last call* sensors and the daily totals keep their values over a restart. The recent-calls list and the connection counters aren't written to the recorder database, because they change with every call.

### On each extension's device

| Entity | |
|---|---|
| Last call | Time of the last call on that extension, with the call attributes |
| Calls today | Calls on that extension since midnight |
| Missed calls today | Unanswered calls to that extension since midnight |
| Talk time today | Answered call time on that extension since midnight |
| Call | Event entity: fires for every call on that extension |

### On each outside line's device

Name your lines in the options, like `001: Main line`.

| Entity | |
|---|---|
| Last call | Time of the last call on that line |
| Calls today | Calls on that line since midnight |

### Call history calendar

**Call history** shows every call on a calendar (the last 500, kept across restarts), so the calendar's week view shows who rang when.

## Live calls from FreePBX (optional)

The NEC's call log only reports a call once it has ended. If your calls also go through FreePBX (for example lines bridged in with an ATA), fill in the FreePBX fields in the options to get live call state from FreePBX's manager interface (AMI):

| Entity | |
|---|---|
| Ringing | On while a call is ringing, with `number`, `caller_name` and `extension` |
| On a call | On while a call is answered |
| Current caller | Who's ringing (phonebook name, caller ID name or number), or `none` |
| Live call | Event entity: `ringing`, `answered`, `ended` |
| Do not disturb *extension* | A switch per extension you list: FreePBX's do-not-disturb, the same as dialling \*76. FreePBX says straight away when it changes from a phone. An extension you've also named gets the switch on its own device, named "Do not disturb" |
| FreePBX connection | Diagnostic |

Bus events: `nec_pbx_ringing` when a phone starts ringing, and `nec_pbx_live_call` for every change (`change` is `ringing`, `answered` or `ended`).

## Call attributes

| Attribute | Example | |
|---|---|---|
| `direction` | `incoming`, `outgoing`, `internal`, `unknown` | `unknown` when the line has no class code and nothing else gives it away |
| `call_class` | `IC`, `OG`, `PIN` | The class code as the phone system printed it, or empty |
| `number` | `0491570006` | Outside number. Ends in `X` if the phone system hides digits. |
| `caller_name` | `Mum` | From the phonebook |
| `station` | `103` | The extension |
| `station_name` | `Oliver` | From the extensions list |
| `duration` | `155` | Seconds talking |
| `ring_time` | `12` | Seconds ringing, when the phone system reports it |
| `trunk` | `001` | The outside line |
| `answered` | `true` | |
| `missed` | `false` | Incoming and not answered |
| `cost` | `$0.25` | The call charge, if your phone system prints one |
| `flags` | `["no_answer"]` | Extra words found on the line: `no_answer`, `noanswer`, `abandon`, `unanswered`, `lost` or `transferred` |

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

Every call gets a line in the logbook under the phone system's name, for example *House phones: missed call from Sam (0491570157) to Family, rang 21 s* or *House phones: Oliver called Alex (0491570156), 2 min 35 s*. Calls the phone system replays after a reconnect don't add logbook lines.

## Repairs

If Home Assistant can't reach the call log for 10 minutes, a **Repairs** warning says so, with the last error. It clears itself when the connection comes back. No calls are lost in between: the phone system keeps them and sends them on reconnect.

## How the data updates

Nothing is polled. The phone system pushes each call record over the SMDR connection the moment a call ends, and the entities update straight away. FreePBX pushes ringing, answered and ended as they happen. FreePBX also pushes do-not-disturb changes through its `Custom:DND<extension>` hint. The switches still read the state on a timer as a fallback: every 30 seconds until FreePBX has pushed a change, then every 5 minutes. If FreePBX's do-not-disturb hints are off (Settings > Advanced Settings), they simply keep checking every 30 seconds.

## What it can't do

From the NEC call log alone, the phone system writes a record when a call ends, so there is no "ringing now" or "on a call now" state; that needs NEC's CTI licence. With FreePBX connected, the **Ringing**, **On a call** and **Current caller** entities above give you those states for calls that go through FreePBX.
