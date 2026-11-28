"""Diagnostics for NEC PBX: raw SMDR lines with phone numbers masked."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import NecPbxConfigEntry
from .const import CONF_AMI_SECRET, CONF_ATTENDANT_TOKEN, CONF_ATTENDANT_URL

# Never in diagnostics: the FreePBX password and the AI attendant's API token.
TO_REDACT = {CONF_AMI_SECRET, CONF_ATTENDANT_TOKEN}

# Six or more digits, which may be split by single spaces or hyphens
# ("0491 570 156"). Not next to a colon, so times like "10:00" are left alone.
_NUMBER = re.compile(r"(?<![\d:])\+?\d(?:[ -]?\d){5,}(?![\d:])")


def _hide_digits(match: re.Match[str]) -> str:
    """Keep the first four digits and any spacing; hide the rest."""
    out, digits = [], 0
    for char in match.group(0):
        if char.isdigit():
            digits += 1
            char = char if digits <= 4 else "x"
        out.append(char)
    return "".join(out)


def _mask(text: str | None) -> str | None:
    if text is None:
        return None
    return _NUMBER.sub(_hide_digits, text)


def _attendant(entry: NecPbxConfigEntry) -> dict[str, Any] | None:
    """The AI attendant's state, without the token, callers or their messages."""
    coordinator = entry.runtime_data.attendant
    if coordinator is None:
        return None
    data = coordinator.data
    status = data.status if data else {}
    return {
        **async_redact_data(
            {
                CONF_ATTENDANT_URL: entry.options.get(CONF_ATTENDANT_URL),
                CONF_ATTENDANT_TOKEN: entry.options.get(CONF_ATTENDANT_TOKEN, ""),
            },
            TO_REDACT,
        ),
        "last_update_success": coordinator.last_update_success,
        "last_error": coordinator.last_error,
        "events_connected": coordinator.events_connected,
        "version": status.get("version"),
        "uptime_s": status.get("uptime_s"),
        "models": status.get("models"),
        "answering_outside": status.get("answering_outside"),
        "active_calls": status.get("active_calls"),
        "new_messages": len(data.messages) if data else None,
        "last_call_outcome": data.last_call.get("outcome") if data and data.last_call else None,
        "avg_first_words_ms": data.stats.get("avg_first_words_ms") if data else None,
    }


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
        "repeated_lines": data.replayed_lines,
        "remembered_lines": len(data.seen),
        "date_order": data.date_order,
        "unnamed_extensions": sorted(data.unnamed_stations),
        "last_raw_line": _mask(data.last_raw),
        "freepbx": (
            {
                "port": data.ami.port,
                "connected": data.ami.connected,
                "auth_failed": data.ami.auth_failed,
                "last_error": data.ami.last_error,
                "ringing": len(data.ami.ringing),
                "active": len(data.ami.active),
            }
            if data.ami
            else None
        ),
        "ai_attendant": _attendant(entry),
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
