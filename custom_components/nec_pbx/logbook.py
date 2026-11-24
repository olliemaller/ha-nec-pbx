"""Logbook lines for NEC PBX calls."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback

from .const import DOMAIN, EVENT_CALL, EVENT_LIVE, EVENT_MISSED_CALL, EVENT_RINGING

# Keys the logbook reads from a description (homeassistant.components.logbook).
LOGBOOK_ENTRY_NAME = "name"
LOGBOOK_ENTRY_MESSAGE = "message"


def _length(seconds: int | None) -> str | None:
    if not seconds:
        return None
    minutes, secs = divmod(int(seconds), 60)
    if minutes and secs:
        return f"{minutes} min {secs} s"
    return f"{minutes} min" if minutes else f"{secs} s"


def _who(data: Mapping[str, Any]) -> str | None:
    if data.get("caller_name") and data.get("number"):
        return f"{data['caller_name']} ({data['number']})"
    return data.get("caller_name") or data.get("number")


def describe_live(data: Mapping[str, Any]) -> str:
    """A live call from FreePBX, e.g. 'call from Alex (0491570156) to Family, ringing'."""
    who = _who(data)
    room = data.get("station_name") or data.get("extension")
    text = "call" + (f" from {who}" if who else "") + (f" to {room}" if room else "")
    return f"{text}, {data.get('change') or 'ringing'}"


def describe_call(data: Mapping[str, Any]) -> str:
    """One readable sentence for a call, e.g. 'missed call from Alex to Family, rang 21 s'."""
    who = _who(data)
    room = data.get("station_name") or data.get("station")
    direction = data.get("direction")
    talk = _length(data.get("duration"))
    ring = _length(data.get("ring_time"))

    if data.get("missed"):
        text = "missed call" + (f" from {who}" if who else "") + (f" to {room}" if room else "")
        return text + (f", rang {ring}" if ring else "")
    if direction == "incoming":
        text = "call" + (f" from {who}" if who else "") + (f" answered on {room}" if room else "")
    elif direction == "outgoing":
        text = (f"{room} called" if room else "outgoing call to") + (f" {who}" if who else "")
        if not room and not who:
            text = "outgoing call"
    elif direction == "internal":
        text = "internal call" + (f" from {room}" if room else "")
    else:
        text = "call" + (f" with {who}" if who else "") + (f" on {room}" if room else "")
    return text + (f", {talk}" if talk else "")


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, str]]], None],
) -> None:
    """Describe calls in the logbook, under the phone system's name."""

    def _name(event: Event) -> str:
        entry = hass.config_entries.async_get_entry(event.data.get("entry_id", ""))
        return entry.title if entry else "Phone system"

    @callback
    def _describe(event: Event) -> dict[str, str]:
        return {
            LOGBOOK_ENTRY_NAME: _name(event),
            LOGBOOK_ENTRY_MESSAGE: describe_call(event.data),
        }

    @callback
    def _describe_live(event: Event) -> dict[str, str]:
        return {
            LOGBOOK_ENTRY_NAME: _name(event),
            LOGBOOK_ENTRY_MESSAGE: describe_live(event.data),
        }

    async_describe_event(DOMAIN, EVENT_CALL, _describe)
    async_describe_event(DOMAIN, EVENT_MISSED_CALL, _describe)
    async_describe_event(DOMAIN, EVENT_RINGING, _describe_live)
    async_describe_event(DOMAIN, EVENT_LIVE, _describe_live)
