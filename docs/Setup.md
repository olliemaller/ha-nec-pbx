# Setup

## 1. The phone system

The integration reads the **SMDR** (Station Message Detail Recording) call log, which the SL2100 and SV9100 can send over the network. Check these in PC Pro or WebPro. On an SL2100 they are the defaults.

| Program | Setting | Value |
|---|---|---|
| 10-12 | The phone system's IP address | For example `192.168.0.10` |
| 10-20, type 5 *SMDR Output* | TCP port | `4001` on Australian systems. Changing it needs a system reset. |
| 35-01-01 | Output port type | **LAN** |
| 35-01-08 | SMDR format | General Overseas |
| 35-02-08 | Print incoming calls | **On**, or you won't see incoming or missed calls |
| 35-02-09 | Extension number or name | **Number** is easiest to match to your rooms |
| 15-01-03 | SMDR printout, per extension | On |

Only **one** program can be connected to the SMDR port at a time. Close any other call-logging software first.

### A setup it's tested on

An Australian SL2100 (software 5.21) with eight analogue extensions, two Telstra lines and InMail voicemail. Nothing below had to be changed for this integration; these are the values it runs with:

| Program | Value |
|---|---|
| 10-12 | Fixed IP address on the home network (`192.168.0.10`) |
| 10-20, type 5 | Port `4001` |
| 35-01-01 | LAN |
| 35-01-08 | General Overseas |
| 35-02-08 | Incoming calls printed |
| 35-02-09 | Extension number |
| 35-01 summaries | Off |

The Home Assistant options for that system list one room per extension (`101: Rumpus` to `108: Study`) and the family's mobiles in the phonebook.

## 2. Add the integration

[![Add integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=nec_pbx)

Or go to **Settings → Devices & services → Add integration → NEC PBX**, and enter:

| Field | |
|---|---|
| Host | The phone system's IP address |
| SMDR port | The port from Program 10-20, type 5 |
| Name | What to call it, for example *House phones* |

Home Assistant checks it can connect before saving.

## 3. Rooms and phonebook

Open the integration and choose **Configure**. Enter one entry per line as `number: name`.

**Extensions:** each one gets its own *last call* sensor.

```
101: Rumpus
103: Oliver
104: Family
```

**Phonebook:** puts names on calls. Spaces and `+61` are fine.

```
0491 570 006: Mum
+61 400 000 000: Grandpa
```

**Outside lines:** each line listed gets its own device with its last call and calls today. Use the trunk number as the call log prints it.

```
001: Main line
002: Fax line
```

**Date order in the call log:** how your phone system prints dates. **Automatic** works it out from each call: a number over 12 must be the day, and otherwise it takes the reading that isn't in the future. Pick **day/month** or **month/day** if the dates on your calls look wrong, for example on an SV9100 that prints month/day.

Saving reloads the integration, so new extensions and lines get their devices. A change to the phonebook alone is applied without a reload.

### Phonebook from a to-do list

Home Assistant's people don't have phone numbers, so the phonebook can come from a **to-do list** instead, which you can edit from the Home Assistant app:

1. **Settings > Devices & services > Add integration > Local to-do**, named for example *Phonebook*.
2. Add one item per person: the name as the item and the number in the description (or `Alex 0491 570 156` as the item).
3. **Configure** the NEC PBX integration and choose the list under **Phonebook list**.

Changes to the list are picked up straight away. The action `nec_pbx.save_caller` adds a name for the last incoming caller (or a number you give).

### Missed-call list

To keep a list of people to call back, make another to-do list (for example *Call back*) and choose it under **Missed-call list**. Each missed call adds an item like `Call back 0491570156 (Alex) missed 3:42 pm at Reception`. When anyone calls that number back from the phone system, the item is ticked off by itself. Calls with a hidden number aren't added, and calls replayed after a reconnect are never added twice.

## 4. Live calls from FreePBX (optional)

1. In FreePBX: **Settings > Asterisk Manager Users > Add Manager**.
   - Manager name and secret: anything (for example `homeassistant`).
   - **Deny**: `0.0.0.0/0.0.0.0`. **Permit**: Home Assistant's address, for example `192.168.0.202/255.255.255.255`.
   - **Read**: `call` and `system`. **Write**: `system` (only needed for do-not-disturb).
   - Submit, then **Apply Config**.
2. In Home Assistant, **Configure** the NEC PBX integration and fill in the FreePBX address, port (5038), manager user and password. To get do-not-disturb switches, list the extensions, for example `901, 902`. The options check the login before saving. The saved password is never shown again: leave the field empty to keep it.

If the secret changes in FreePBX later, Home Assistant shows a **Reauthenticate** notification for NEC PBX. Open it, enter the new manager user and secret, and live calls come back without a restart.

## Changing the address later

Open the integration's menu (⋮) and choose **Reconfigure**. If you change the address or port, Home Assistant checks it can connect first. If you keep them, it doesn't, because the running integration already holds the phone system's only SMDR connection.
