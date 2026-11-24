# Security policy

This integration reads every call on your phone system and can log in to FreePBX, so it handles callers' numbers and a manager secret. Thank you for reporting problems carefully.

## Reporting a vulnerability

**Please don't open a public issue, discussion or pull request.**

Report it privately through GitHub: go to the [Security tab](https://github.com/olliemaller/ha-nec-pbx/security) and select **Report a vulnerability**. Only the maintainer can see the report.

Include as much of this as you can:

- what someone could do (for example read the FreePBX secret, read call records, change do-not-disturb, or knock the phone system offline);
- how to reproduce it, and what access they'd need (local network, a Home Assistant user, a dashboard, an automation);
- the integration version, Home Assistant version and phone system model;
- diagnostics or logs, with your own numbers, addresses and secrets removed.

## What happens next

- You'll get a reply within **7 days**.
- Once it's confirmed, a fix is aimed for within **30 days**.
- A fixed release goes out with a GitHub security advisory. You'll be credited unless you'd rather not be.

Please give a reasonable time for a fix to be released before telling anyone else.

## Supported versions

Only the **latest release** gets security fixes. Update through the Marketplace or HACS.

## In scope

- The FreePBX manager secret being stored, logged or exposed (including in diagnostics or the options form).
- Callers' numbers being logged above debug level or left unmasked in diagnostics.
- The integration making a phone system or FreePBX unstable (for example by taking the SMDR connection or retrying a rejected login).

## Out of scope

- Weaknesses in NEC phone systems, their firmware or FreePBX. Report those to their makers.
- Home Assistant itself. See [Home Assistant's security policy](https://www.home-assistant.io/security/).
- Someone who already has administrator access to your Home Assistant.

## Keeping your own system safe

- Give the FreePBX manager user only the rights it needs, and permit only Home Assistant's address. See [Setup](docs/Setup.md).
- Keep the SMDR port and the Asterisk manager port off the internet.
