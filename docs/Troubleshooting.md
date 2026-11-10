# Troubleshooting

## "Could not connect" when adding it

- Check the IP address: Program 10-12 on the phone system.
- Check the port: Program 10-20, type 5 *SMDR Output*. A changed port needs a system reset before it works.
- Check Program 35-01-01 is **LAN**.
- Only one program can hold the SMDR port. Close any other call logger, or PC software that reads SMDR.

## Connected, but no calls appear

- Make a call and hang up: a record is only written when the call ends.
- Turn on **Print incoming calls** (Program 35-02-08).
- Check SMDR printout is on for the extensions (15-01-03) and the line (14-01-06).
- Look at the **Last call log line** sensor. If it changes when a call ends, the phone system is sending; see the next section.

## Calls are read wrongly

SMDR layouts change with the 35-01 and 35-02 settings. The parser reads the line in pieces rather than fixed columns, so most layouts work, but not every one has been seen.

Download the diagnostics (**Settings → Devices & services → NEC PBX → ⋮ → Download diagnostics**). Numbers are masked to their first four digits. Then [open an issue](https://github.com/olliemaller/ha-nec-pbx/issues/new) with the file, or with the `last_raw_line` from it.

## The connection keeps dropping

The integration reconnects by itself, waiting a little longer each time (5 seconds up to 5 minutes). The **Call log connection** sensor's `last_error` attribute says why it dropped.

## Debug logging

```yaml
logger:
  logs:
    custom_components.nec_pbx: debug
```

Every line from the phone system is then written to the Home Assistant log.
