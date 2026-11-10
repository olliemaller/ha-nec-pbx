# NEC PBX for Home Assistant

Call history from an **NEC SL2100** (and SV9100) phone system in Home Assistant: who called, which room answered, what was missed. It reads the phone system's built-in call log (SMDR) over the network, with no extra licence, cloud or software.

## What you get

| Entity | What it shows |
|---|---|
| Last call | Time of the last call, with direction, number, caller name, room, duration and whether it was answered |
| Last missed call | Same, for the last incoming call nobody answered |
| Calls today / Missed calls today | Counts since midnight |
| Recent calls | The last 20 calls as an attribute list |
| *Room* last call | One per extension you name in the options |
| Call log connection | Whether Home Assistant is connected to the phone system |
| Last call log line | The raw line from the phone system (diagnostic) |

Events, for automations:

- `nec_pbx_call`: every finished call
- `nec_pbx_missed_call`: an incoming call nobody answered

Both carry `direction`, `number`, `caller_name`, `station`, `station_name`, `duration`, `ring_time`, `trunk`, `answered`, `missed` and `start`.

**Limit:** the phone system only writes the record when a call ends, so this can tell you about missed and finished calls, not "the phone is ringing now". Live ringing needs NEC's paid CTI licence.

## Phone system settings

These are the SL2100 defaults; check them in PC Pro or WebPro.

| Program | Setting |
|---|---|
| 10-20, type 5 (SMDR Output) | TCP port, **4001** on Australian systems. Changing it needs a system reset. |
| 35-01-01 | Output port type: **LAN** |
| 35-02-08 | Print incoming calls: **on** |
| 35-02-09 | Extension number (not name) is easiest to match |
| 15-01-03 / 14-01-06 | SMDR printout on for each extension and trunk |

Only one program can be connected to the SMDR port at a time, so close any other call logger.

## Install

1. In Home Assistant go to **Settings → Marketplace** (HACS on older versions), open the menu, choose **Custom repositories**, and add `https://github.com/olliemaller/ha-nec-pbx` as an integration.
2. Install **NEC PBX** and restart Home Assistant.
3. **Settings → Devices & services → Add integration → NEC PBX**. Enter the phone system's IP address and the SMDR port.
4. Open **Configure** on the integration to add room names and a phonebook, one per line:

   ```
   103: Oliver
   104: Family
   ```

   ```
   0491570156: Alex
   ```

## Example: missed call notification

```yaml
triggers:
  - trigger: event
    event_type: nec_pbx_missed_call
actions:
  - action: notify.notify
    data:
      title: Missed call
      message: >-
        {{ trigger.event.data.caller_name or trigger.event.data.number or 'Unknown caller' }}
        at {{ as_timestamp(trigger.event.data.start) | timestamp_custom('%-I:%M %p') }}
```

## If calls look wrong

SMDR layouts change with the 35-01 and 35-02 settings. The parser reads tokens rather than fixed columns and keeps the raw line. If a call is read wrongly, download the diagnostics from the integration (numbers are masked) and open an issue with the `last_raw_line`.

## Development

```bash
pip install -r requirements_test.txt ruff
pytest
ruff check . && ruff format --check .
```

MIT licence.
