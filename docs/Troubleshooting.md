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

## Known limitations

- Calls appear when they **end**. SMDR only writes a record then, so ringing and answered-but-ongoing calls are only seen live with FreePBX (Setup, step 4).
- Only one program can hold the SMDR port, so this can't run alongside other call-logging software.
- Calls made while Home Assistant was offline are only read if the phone system buffered them. SL2100s do, for a while; older lines may be lost.
- The phone system can't be controlled through SMDR. Do-not-disturb switches need FreePBX.
- Tested on an SL2100 (Australian, software 5.21) with the General Overseas SMDR format. The SV9100's `PIN` / `POT` layout is read from sample lines but hasn't been tested on a real SV9100. Other NEC systems and formats may parse differently.
- With FreePBX, a call whose hang-up FreePBX never reported stops showing as ringing after 10 minutes.

## FreePBX: live calls don't work

- **"FreePBX rejected that manager user or password"**: check the manager name and secret under **Settings > Asterisk Manager Users** in FreePBX, and that you pressed **Apply Config** after saving. After a rejected login the integration stops trying, so it can't get the user locked out, and shows a **Reauthenticate** notification. Enter the right details there.
- **"Couldn't reach the FreePBX manager"**: the manager user's **Permit** must include Home Assistant's address, for example `192.168.0.202/255.255.255.255`, and **Deny** must not cover it. Also check port 5038 isn't blocked by the FreePBX firewall (**Connectivity > Firewall**: add Home Assistant as a trusted host).
- **Logged in, but nothing rings**: the manager user needs **Read** access to `call` and `system`. Do-not-disturb switches also need **Write** access to `system`.
- The **FreePBX connection** sensor's `last_error` attribute says why it last failed.

## AI attendant

See [AI attendant: troubleshooting](AI-attendant.md#troubleshooting).

## Debug logging

The quickest way: **Settings > Devices & services > NEC PBX > ⋮ > Enable debug logging**. Reproduce the problem, then choose **Disable debug logging**, and your browser downloads the log.

Or in `configuration.yaml`, which also covers the library that talks to the phone system and FreePBX:

```yaml
logger:
  logs:
    custom_components.nec_pbx: debug
    aionecpbx: debug
```

Every line from the phone system is then written to the Home Assistant log. These lines include callers' numbers, so check the log before you share it.
