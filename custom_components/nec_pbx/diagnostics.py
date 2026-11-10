"""Diagnostics for NEC PBX: raw SMDR lines with phone numbers masked."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.core import HomeAssistant

from . import NecPbxConfigEntry

_DIGITS = re.compile(r"\d{6,}")


def _mask(text: str | None) -> str | None:
    if text is None:
        return None
    return _DIGITS.sub(lambda m: m.group(0)[:4] + "x" * (len(m.group(0)) - 4), text)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NecPbxConfigEntry
) -> dict[str, Any]:
    """Return diagnostics. Numbers are cut to their first 4 digits."""
    data = entry.runtime_data
    client = data.client
    return {
        "connection": {
            "port": client.port,
            "connected": client.connected,
            "lines_received": client.lines_received,
            "last_error": client.last_error,
        },
        "extensions": data.extensions,
        "phonebook_entries": len(data.phonebook),
        "unreadable_lines": data.unparsed_lines,
        "last_raw_line": _mask(data.last_raw),
        "recent": [
            {
                **{
                    k: v
                    for k, v in r.as_dict().items()
                    if k not in ("raw", "number", "caller_name")
                },
                "raw": _mask(r.raw),
                "number": _mask(r.number),
            }
            for r in data.recent
        ],
    }
