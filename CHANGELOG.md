# Changelog

## 0.6.0

**New**

- **Phonebook from a Home Assistant to-do list.** Pick a to-do list under **Configure** and its items become phonebook entries: a name with the number in the description, or "Alex 0491 570 156" as the item. Add or change contacts from the Home Assistant app's To-do lists and calls pick up the names straight away. The phonebook in the options still works and wins for the same number.
- **New action `nec_pbx.save_caller`:** saves a name and number to the phonebook list (or the options' phonebook). Leave the number empty to save the last incoming caller, for example from a notification button.

## 0.5.0

**New**

- **A device for every extension and line.** Each extension you name (like `103: Oliver`) is now its own device under the phone system, with **Last call**, **Calls today**, **Talk time today** and its own **Call** event entity. Name your outside lines in the options too (`001: Main line`) and each gets **Last call** and **Calls today**. Existing entity IDs don't change.
- **Weekly and monthly totals:** calls, missed calls and talk time this week (from Monday) and this month, plus **Longest call today** and **Unknown callers today** (incoming numbers not in the phonebook).
- **Call history calendar:** every call on a calendar, the last 500 kept across restarts.
- **Live calls from FreePBX (optional):** with FreePBX's manager interface set up in the options, you get **Ringing**, **On a call**, **Current caller** and a **Live call** event (ringing, answered, ended) while calls happen, not just when they end. Also the `nec_pbx_ringing` and `nec_pbx_live_call` events, and **Do not disturb** switches for the FreePBX extensions you list. The options check the login before saving, and a wrong password stops retries so FreePBX doesn't block Home Assistant.
- **New blueprint: announce who's calling** on your speakers while the phone rings, with quiet hours.

## 0.4.0

**Fixed**

- **Calls were counted twice after a reconnect or restart.** The phone system prints its stored calls again whenever Home Assistant connects, and those were added to *Calls today*, *Missed calls today* and *Talk time today* a second time. They could also move *Last call* back to an older call and repeat calls in the recent list. Calls are now remembered (and the list is saved across restarts), so a call is only ever counted and announced once.
- **SV9100-style call types weren't recognised.** In the `PIN` / `POT` layout, incoming calls (`PIN`, `IVIN`) were read as outgoing, so missed-call alerts couldn't fire. `PIN`, `IVIN`, `PTRS` (transferred, marked `transferred`), `POT` and `POTA` are now read correctly.
- **Month/day dates were read as day/month.** A call on 5 November printed as `11/05` was read as 11 May, so it looked old and fired no event. Dates are now read in whichever order gives a date that isn't in the future, or in the order you pick under **Configure** (*Date order in the call log*).
- **A dead connection wasn't noticed.** If the phone system rebooted or the network dropped without closing the connection, the integration could stay "connected" and log nothing. TCP keepalive now notices within about 90 seconds and reconnects.

**New**

- The *Last call log line* diagnostic sensor lists **extensions seen in calls that have no name yet**, and how many repeated lines were skipped. Both are in the diagnostics too.

## 0.3.1

- The phonebook example in the options, the docs and the tests now use fictional numbers from the range set aside for that (0491 570 xxx) and made-up names.

## 0.3.0

- New **Talk time today** sensor: minutes spent on answered calls since midnight, with long-term statistics.
- Every call now gets a readable **logbook** line under the phone system's name, like *missed call from Sam (0491570157) to Family, rang 21 s*.
- A **Repairs** warning appears if the call log has been unreachable for 10 minutes, with the last error. It clears itself when the connection comes back.
- Less database churn: the recent-calls list and the connection counters change with every call, so they're no longer written to the recorder.
- Releases are published automatically when the version changes, and 0.1.0 and 0.1.1 now have releases too.

## 0.2.0

- New **Call** event entity. Every finished call fires one event, typed `incoming`, `missed`, `outgoing`, `internal` or `other`, so you can pick them in the automation editor instead of typing event names. Each event carries the number, caller name, room, duration, ring time and line.
- New blueprint: **missed call notification** to a phone with the Home Assistant app.
- The phone system replays calls it stored while Home Assistant was offline. Those now fill in the history and last-call sensors without firing events or notifications again, and only calls from today count towards "calls today". Found on a real SL2100.
- Releases are now built by GitHub when a version is tagged, with `nec_pbx.zip` attached.
- Issue forms for bugs, calls read wrongly and feature requests, and a pull request template.
- Setup guide lists the exact phone system settings of a tested SL2100.

## 0.1.1

- New black-and-white icon and logo, shown in Home Assistant's integration list (Home Assistant 2026.3 and later read them from the integration's `brand` folder).
- New README and full documentation in `docs/`: installation, setup on the phone system, every entity, automation examples and troubleshooting.
- Checks updated to the current GitHub actions.

## 0.1.0

First release.

- Connects to the SMDR (call log) port of an NEC SL2100 / SV9100 and reconnects by itself.
- Sensors: last call, last missed call, calls today, missed calls today, recent calls, a last-call sensor per extension, connection status and the last raw call-log line.
- Events: `nec_pbx_call` for every call and `nec_pbx_missed_call` for unanswered incoming calls.
- Names on calls from a phonebook you enter in the options.
- Diagnostics with phone numbers masked.
