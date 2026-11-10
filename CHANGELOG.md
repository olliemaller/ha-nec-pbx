# Changelog

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
