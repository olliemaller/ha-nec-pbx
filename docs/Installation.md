# Installation

## Marketplace (Home Assistant 2026.11 and later) or HACS

1. Open **Settings → Marketplace** (HACS on older versions).
2. Open the menu (⋮), choose **Custom repositories**, and add `https://github.com/olliemaller/ha-nec-pbx` with the type **Integration**.
3. Find **NEC PBX**, install it, and restart Home Assistant.

Or use this button:

[![Open in the Marketplace](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=olliemaller&repository=ha-nec-pbx&category=integration)

## Manual

1. Download the latest release, or the repository as a zip.
2. Copy `custom_components/nec_pbx` into your Home Assistant `config/custom_components/` folder, so you end up with `config/custom_components/nec_pbx/manifest.json`.
3. Restart Home Assistant.

## Next

[Set it up](Setup.md).
