# Changelog

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
