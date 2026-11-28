# AI attendant (optional add-on)

[nec-ai-attendant](https://github.com/olliemaller/nec-ai-attendant) is a separate program that answers your phone system's calls with a voice assistant: it greets the caller, puts them through to the right person or takes a message. It runs on its own machine (or container) next to Asterisk or FreePBX, not inside Home Assistant.

This integration doesn't need it. If you run it, the AI attendant add-on shows what it's doing in Home Assistant and lets you switch it on and off. It's **off by default**: nothing changes until you enter the engine's address.

| Project | What it is |
|---|---|
| [nec-ai-attendant](https://github.com/olliemaller/nec-ai-attendant) | The engine: answers calls, keeps the call log and messages, and serves the HTTP API this add-on reads |
| [nec-ai-attendant-dashboard](https://github.com/olliemaller/nec-ai-attendant-dashboard) | A web page on your network for call transcripts, recordings, messages and the allow and block lists |
| [nec-ai-attendant-writeup](https://github.com/olliemaller/nec-ai-attendant-writeup) | How it was built and how to set up your own, step by step |

## Turning it on

1. Set up the engine and give it an `api_token` in its config. See the [engine's README](https://github.com/olliemaller/nec-ai-attendant).
2. In Home Assistant, **Configure** the NEC PBX integration and fill in:
   - **AI attendant address**: the engine's address with its port, for example `http://192.0.2.20:8099`.
   - **AI attendant API token**: the engine's `api_token`.
3. Save. The options ask the engine for its status (`GET /api/status`) before saving, so a wrong address or token is caught straight away.

The saved token is never shown again: leave the field empty to keep it. To turn the add-on off, clear the address; the token is removed with it.

## What you get

Everything is on its own device, **AI attendant**, under the phone system.

| Entity | State | Notes |
|---|---|---|
| Answer outside calls (switch) | On while the attendant answers outside calls | Off: outside calls ring as normal. It only covers outside calls. |
| New messages (sensor) | Messages not yet marked done | `messages` attribute: the latest 10, newest first, each with `id`, `call_id`, `created_at`, `for_person`, `caller_name`, `callback_number` and `message` |
| Last call (sensor) | When the attendant's last call started | Attributes: `caller`, `caller_name`, `mode` (outside or internal), `outcome`, `target`, `ended_at`, `duration_s` |
| Call in progress (binary sensor) | On while the attendant is talking to someone | `active_calls` attribute |
| Average response time (sensor) | How long callers wait for the attendant's first words, in seconds | Average over the last 7 days. Attributes: the speech-to-text and language model parts, in milliseconds |

`outcome` is one of `transfer` (put through), `message`, `hangup` (the attendant ended the call), `caller_hung_up` or `fallback` (passed to a person).

The messages and the last caller aren't written to the recorder database, because they hold callers' names, numbers and words.

## Actions

| Action | Fields | What it does |
|---|---|---|
| `nec_pbx.attendant_mark_message_done` | `message_id`, and `config_entry_id` if you have more than one phone system | Marks a message done, so it leaves **New messages** |
| `nec_pbx.attendant_set_answering` | `enabled` (true or false), and `config_entry_id` | The same as the **Answer outside calls** switch |

For example, mark the newest message done from a dashboard button:

```yaml
action: nec_pbx.attendant_mark_message_done
data:
  message_id: "{{ state_attr('sensor.ai_attendant_new_messages', 'messages')[0].id }}"
```

Or let the attendant answer only in the evening:

```yaml
triggers:
  - trigger: time
    at: "18:00:00"
    id: evening
  - trigger: time
    at: "08:00:00"
    id: morning
actions:
  - action: nec_pbx.attendant_set_answering
    data:
      enabled: "{{ trigger.id == 'evening' }}"
```

## The `nec_ai_attendant_call` event

The engine fires `nec_ai_attendant_call` on the Home Assistant event bus **itself**, through Home Assistant's REST API with its own long-lived token. This integration doesn't fire it again, so you get each event once, even with the add-on off.

| Field | |
|---|---|
| `stage` | `answered`, `transfer`, `message` or `ended` |
| `call_id` | The engine's call ID, the same as in the dashboard |
| `caller`, `caller_name` | Who called |
| `mode` | `outside` or `internal` |
| `target`, `extension` | Who and which extension the call was put through to (transfers) |
| `message` | What the caller said to pass on (messages) |
| `outcome` | How the call ended (`ended`) |

```yaml
triggers:
  - trigger: event
    event_type: nec_ai_attendant_call
    event_data:
      stage: transfer
```

## Blueprints

**Announce calls the attendant puts through.** Says "Alex for Sam, on the phone now" on the speakers you pick. Make one automation per extension, each with its own speakers, or leave the extension empty for all of them.

[![Import the blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Folliemaller%2Fha-nec-pbx%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fnec_pbx%2Fattendant_transfer_announcement.yaml)

**Notify me of new messages.** Sends a phone notification like "Alex for Sam (0491 570 156): Running late, back by six". Optionally only for one person.

[![Import the blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Folliemaller%2Fha-nec-pbx%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fnec_pbx%2Fattendant_message_notification.yaml)

Both use the engine's event, so they need the engine's Home Assistant connection set up, not this add-on.

## How the data updates

Home Assistant asks the engine for its status, new messages, last call and response times every 30 seconds. It also keeps the engine's event websocket (`/api/events`) open: when a call starts or ends, or a message is taken, the entities change straight away and the details are fetched. While the websocket is connected, the regular check slows to every 5 minutes. If it drops, Home Assistant goes back to every 30 seconds and reconnects after 5 seconds, then 10, 20 and so on up to 5 minutes between tries.

The engine is optional: if it's off or unreachable, the phone system and its call log carry on as normal, and only the AI attendant entities are unavailable until it answers again.

## Troubleshooting

- **"Couldn't reach the AI attendant"** when saving: check the address and port (8099 by default), that the engine is running, and that Home Assistant can reach it, for example `curl http://192.0.2.20:8099/api/status -H "Authorization: Bearer <token>"` from the Home Assistant host.
- **"AI attendant token rejected"** in Repairs: the engine's `api_token` changed. Enter the new one under **Configure**. The repair clears itself once the engine accepts it.
- **The blueprints do nothing**: the engine fires the event, so check its Home Assistant URL and token, and look for `nec_ai_attendant_call` under **Developer tools > Events** while you make a test call.
- **Diagnostics** include the add-on's state (version, models, whether the websocket is connected, the last error) with the API token redacted and no callers or messages.
