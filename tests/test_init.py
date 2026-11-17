"""End-to-end tests against a fake SL2100 SMDR server."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import contextlib
from datetime import timedelta
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.nec_pbx.const import (
    CONF_EXTENSIONS,
    CONF_PHONEBOOK,
    DOMAIN,
    EVENT_CALL,
    EVENT_MISSED_CALL,
)


class FakePbx:
    """A TCP server that behaves like the SL2100 SMDR port."""

    def __init__(self) -> None:
        self.writers: list[asyncio.StreamWriter] = []
        self.connected = asyncio.Event()
        self.server: asyncio.Server | None = None
        self.port = 0

    async def start(self) -> None:
        await self.start_on(0)

    async def start_on(self, port: int) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", port)
        self.port = self.server.sockets[0].getsockname()[1]

    async def _handle(self, _reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.writers.append(writer)
        self.connected.set()

    async def send(self, text: str) -> None:
        for writer in self.writers:
            writer.write(text.encode("ascii"))
            await writer.drain()

    async def drop_clients(self) -> None:
        for writer in self.writers:
            writer.close()
        self.writers.clear()
        self.connected.clear()

    async def stop(self) -> None:
        await self.drop_clients()
        if self.server:
            self.server.close()
            # wait_closed() also waits for open client connections.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.server.wait_closed(), 1)


@pytest.fixture
async def pbx(hass: HomeAssistant, socket_enabled) -> AsyncIterator[FakePbx]:
    server = FakePbx()
    await server.start()
    yield server
    # Unload anything a failed test left running, so its client stops.
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)
    await server.stop()


def _hm(minutes_ago: int = 1) -> str:
    """A call time the phone system would print for a call that just finished."""
    return (dt_util.now() - timedelta(minutes=minutes_ago)).strftime("%H:%M")


async def _wait(hass: HomeAssistant, predicate, timeout: float = 3.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.02)
            await hass.async_block_till_done()


async def _setup(hass: HomeAssistant, pbx: FakePbx) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Teak phones",
        data={CONF_HOST: "127.0.0.1", CONF_PORT: pbx.port},
        options={
            CONF_EXTENSIONS: "103: Oliver\n104: Family",
            CONF_PHONEBOOK: "0491570156: Alex\n0491570157: Sam",
        },
        unique_id=f"127.0.0.1:{pbx.port}",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    async with asyncio.timeout(3):
        await pbx.connected.wait()
    await _wait(
        hass, lambda: hass.states.get("binary_sensor.teak_phones_call_log_connection").state == "on"
    )
    return entry


async def test_calls_update_sensors_and_fire_events(hass: HomeAssistant, pbx: FakePbx) -> None:
    calls = async_capture_events(hass, EVENT_CALL)
    missed = async_capture_events(hass, EVENT_MISSED_CALL)
    entry = await _setup(hass, pbx)

    # Header, an answered call split across two TCP packets, then a missed call.
    await pbx.send("CLSS  TIME   LINE   DURATION  STATION  DIALLED No./CLI\r\n")
    await pbx.send(f"IC 0001  {_hm(4)}  001   00:02:35  103   04915")
    await pbx.send("70156   0:08\r\n")
    await pbx.send(f"IC 0002  {_hm(1)}  001                 104   0491570157   0:21  NO ANSWER\r\n")
    await _wait(hass, lambda: len(calls) == 2)

    assert calls[0].data["caller_name"] == "Alex"
    assert calls[0].data["station_name"] == "Oliver"
    assert calls[0].data["duration"] == 155
    assert calls[0].data["entry_id"] == entry.entry_id
    assert len(missed) == 1
    assert missed[0].data["caller_name"] == "Sam"
    assert missed[0].data["station"] == "104"

    last = hass.states.get("sensor.teak_phones_last_call")
    assert last.attributes["number"] == "0491570157"
    assert last.attributes["missed"] is True
    assert hass.states.get("sensor.teak_phones_last_missed_call").attributes["caller_name"] == "Sam"
    assert hass.states.get("sensor.teak_phones_calls_today").state == "2"
    assert hass.states.get("sensor.teak_phones_missed_calls_today").state == "1"
    assert hass.states.get("sensor.teak_phones_recent_calls").state == "2"
    oliver = hass.states.get("sensor.oliver_last_call")
    assert oliver.attributes["caller_name"] == "Alex"
    raw = hass.states.get("sensor.teak_phones_last_call_log_line")
    assert "NO ANSWER" in raw.state

    event = hass.states.get("event.teak_phones_call")
    assert event.attributes["event_type"] == "missed"
    assert event.attributes["caller_name"] == "Sam"
    assert event.attributes["station_name"] == "Family"
    assert "missed" in event.attributes["event_types"]

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_reconnects_after_pbx_drops(hass: HomeAssistant, pbx: FakePbx) -> None:
    with patch("custom_components.nec_pbx.client.RECONNECT_MIN", 0.05):
        entry = await _setup(hass, pbx)
        await pbx.drop_clients()
        await _wait(
            hass,
            lambda: hass.states.get("binary_sensor.teak_phones_call_log_connection").state == "off",
        )
        async with asyncio.timeout(3):
            await pbx.connected.wait()
        await _wait(
            hass,
            lambda: hass.states.get("binary_sensor.teak_phones_call_log_connection").state == "on",
        )
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_unreadable_line_is_counted_not_fatal(hass: HomeAssistant, pbx: FakePbx) -> None:
    entry = await _setup(hass, pbx)
    await pbx.send("12:00 ????\r\n")
    await pbx.send(f"OG 0001  {_hm(4)}  001   00:02:35  103   0491570156\r\n")
    calls = async_capture_events(hass, EVENT_CALL)
    await _wait(hass, lambda: entry.runtime_data.last_call is not None)
    assert entry.runtime_data.unparsed_lines == 1
    assert hass.states.get("binary_sensor.teak_phones_call_log_connection").state == "on"
    del calls
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_diagnostics_mask_numbers(hass: HomeAssistant, pbx: FakePbx) -> None:
    from custom_components.nec_pbx.diagnostics import async_get_config_entry_diagnostics

    entry = await _setup(hass, pbx)
    await pbx.send(f"OG 0001  {_hm(4)}  001   00:02:35  103   0491570156\r\n")
    await _wait(hass, lambda: entry.runtime_data.last_call is not None)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = str(diag)
    assert "0491570156" not in text
    assert "0491xxxxxx" in text
    assert diag["connection"]["connected"] is True
    assert diag["recent"][0]["station"] == "103"


def _event_type(hass: HomeAssistant) -> str | None:
    return hass.states.get("event.teak_phones_call").attributes.get("event_type")


async def test_event_types(hass: HomeAssistant, pbx: FakePbx) -> None:
    entry = await _setup(hass, pbx)
    await pbx.send(f"OG 0001  {_hm(4)}  001   00:02:35  103   0491570156\r\n")
    await _wait(
        hass,
        lambda: hass.states.get("event.teak_phones_call").attributes["event_type"] == "outgoing",
    )
    await pbx.send(f"IC 0002  {_hm(2)}  001   00:01:00  104   0491570157   0:08\r\n")
    await _wait(
        hass,
        lambda: hass.states.get("event.teak_phones_call").attributes["event_type"] == "incoming",
    )
    assert hass.states.get("event.teak_phones_call").attributes["duration"] == 60
    # A dropped connection must not look like a new call.
    before = hass.states.get("event.teak_phones_call").state
    await pbx.drop_clients()
    await _wait(
        hass,
        lambda: hass.states.get("binary_sensor.teak_phones_call_log_connection").state == "off",
    )
    assert hass.states.get("event.teak_phones_call").state == before
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_replayed_calls_are_not_announced(hass: HomeAssistant, pbx: FakePbx) -> None:
    """On connect the SL2100 replays calls it stored while nobody was listening."""
    calls = async_capture_events(hass, EVENT_CALL)
    missed = async_capture_events(hass, EVENT_MISSED_CALL)
    entry = await _setup(hass, pbx)
    yesterday = (dt_util.now() - timedelta(days=1)).strftime("%d/%m")
    await pbx.send(f"IC 0001  {yesterday} 18:15  001   104   0491570157   0:21  NO ANSWER\r\n")
    await _wait(hass, lambda: entry.runtime_data.last_call is not None)

    assert calls == []
    assert missed == []
    assert hass.states.get("event.teak_phones_call").state == "unknown"
    assert hass.states.get("sensor.teak_phones_calls_today").state == "0"
    assert hass.states.get("sensor.teak_phones_missed_calls_today").state == "0"
    # The history still shows it.
    assert hass.states.get("sensor.teak_phones_last_missed_call").attributes["caller_name"] == "Sam"
    assert hass.states.get("sensor.teak_phones_recent_calls").state == "1"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_replay_after_reconnect_is_not_counted_twice(
    hass: HomeAssistant, pbx: FakePbx
) -> None:
    """The SL2100 prints today's calls again when the client reconnects."""
    with patch("custom_components.nec_pbx.client.RECONNECT_MIN", 0.05):
        calls = async_capture_events(hass, EVENT_CALL)
        entry = await _setup(hass, pbx)
        first = f"IC 0001  {_hm(6)}  001   00:02:35  103   0491570156   0:08\r\n"
        second = f"IC 0002  {_hm(2)}  001   00:01:00  104   0491570157   0:05\r\n"
        await pbx.send(first)
        await pbx.send(second)
        await _wait(hass, lambda: len(calls) == 2)
        assert hass.states.get("sensor.teak_phones_calls_today").state == "2"

        await pbx.drop_clients()
        async with asyncio.timeout(3):
            await pbx.connected.wait()
        # Replay, oldest first, with different spacing.
        await pbx.send(first.replace("   ", "  "))
        await pbx.send(second)
        await _wait(hass, lambda: entry.runtime_data.replayed_lines == 2)

        assert len(calls) == 2
        assert hass.states.get("sensor.teak_phones_calls_today").state == "2"
        assert hass.states.get("sensor.teak_phones_recent_calls").state == "2"
        # The last call is still the newest one, not the replayed older call.
        assert hass.states.get("sensor.teak_phones_last_call").attributes["station"] == "104"
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_seen_lines_survive_a_reload(hass: HomeAssistant, pbx: FakePbx) -> None:
    calls = async_capture_events(hass, EVENT_CALL)
    entry = await _setup(hass, pbx)
    line = f"OG 0001  {_hm(3)}  001   00:00:40  103   0491570156\r\n"
    await pbx.send(line)
    await _wait(hass, lambda: len(calls) == 1)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    await pbx.drop_clients()

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    async with asyncio.timeout(3):
        await pbx.connected.wait()
    await pbx.send(line)
    await _wait(hass, lambda: entry.runtime_data.replayed_lines == 1)
    assert len(calls) == 1
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_sv9100_style_incoming_is_missed_call_aware(
    hass: HomeAssistant, pbx: FakePbx
) -> None:
    calls = async_capture_events(hass, EVENT_CALL)
    entry = await _setup(hass, pbx)
    today = dt_util.now().strftime("%m/%d")  # this layout prints month/day
    await pbx.send(f"PIN  {_hm(2)} {today} 001  00:03:12 104        0491570157\r\n")
    await _wait(hass, lambda: len(calls) == 1)
    assert calls[0].data["direction"] == "incoming"
    assert calls[0].data["station_name"] == "Family"
    await pbx.send(f"POT  {_hm(1)} {today} 002  00:00:45 205        0491570156\r\n")
    await _wait(hass, lambda: len(calls) == 2)
    assert calls[1].data["direction"] == "outgoing"
    state = hass.states.get("sensor.teak_phones_last_call_log_line")
    assert state.attributes["unnamed_extensions"] == ["205"]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_extension_and_line_devices_and_totals(hass: HomeAssistant, pbx: FakePbx) -> None:
    from homeassistant.helpers import device_registry as dr

    from custom_components.nec_pbx.const import CONF_LINES

    calls = async_capture_events(hass, EVENT_CALL)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Teak phones",
        data={CONF_HOST: "127.0.0.1", CONF_PORT: pbx.port},
        options={
            CONF_EXTENSIONS: "103: Oliver\n104: Family",
            CONF_PHONEBOOK: "0491570156: Alex",
            CONF_LINES: "001: Main line",
        },
        unique_id=f"127.0.0.1:{pbx.port}",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    async with asyncio.timeout(3):
        await pbx.connected.wait()
    await pbx.send(f"IC 0001  {_hm(6)}  001   00:02:35  103   0491570156   0:08\r\n")
    await pbx.send(
        f"IC 0002  {_hm(4)}  001   00:00:40  103   0491570199   0:05\r\n"
    )  # not in the phonebook
    await pbx.send(f"OG 0003  {_hm(2)}  002   00:01:00  104   0491570156\r\n")
    await _wait(hass, lambda: len(calls) == 3)

    devices = dr.async_get(hass)
    oliver = devices.async_get_device(identifiers={(DOMAIN, f"{entry.entry_id}_extension_103")})
    assert oliver is not None and oliver.name == "Oliver"
    assert hass.states.get("sensor.oliver_calls_today").state == "2"
    # Talk time is shown in minutes.
    assert float(hass.states.get("sensor.oliver_talk_time_today").state) == pytest.approx(
        (155 + 40) / 60
    )
    assert hass.states.get("sensor.family_calls_today").state == "1"
    assert hass.states.get("sensor.main_line_calls_today").state == "2"
    assert hass.states.get("sensor.main_line_last_call").attributes["station"] == "103"
    assert hass.states.get("sensor.teak_phones_calls_this_week").state == "3"
    assert hass.states.get("sensor.teak_phones_calls_this_month").state == "3"
    assert float(hass.states.get("sensor.teak_phones_talk_time_this_week").state) == pytest.approx(
        255 / 60
    )
    assert float(hass.states.get("sensor.teak_phones_longest_call_today").state) == pytest.approx(
        155 / 60
    )
    assert hass.states.get("sensor.teak_phones_unknown_callers_today").state == "1"
    oliver_event = hass.states.get("event.oliver_call")
    assert oliver_event.attributes["event_type"] == "incoming"
    assert oliver_event.attributes["number"] == "0491570199"

    calendar = hass.data["entity_components"]["calendar"].get_entity(
        "calendar.teak_phones_call_history"
    )
    events = await calendar.async_get_events(
        hass, dt_util.now() - timedelta(hours=1), dt_util.now() + timedelta(hours=1)
    )
    assert len(events) == 3
    assert events[0].summary.startswith("Call from Alex")
    assert await hass.config_entries.async_unload(entry.entry_id)


def test_period_starts() -> None:
    from datetime import datetime

    from custom_components.nec_pbx.sensor import DAY, MONTH, WEEK, period_start

    now = dt_util.as_local(datetime(2026, 11, 19, 15, 0, tzinfo=dt_util.get_default_time_zone()))
    assert period_start(DAY, now).date().isoformat() == "2026-11-19"
    assert period_start(WEEK, now).date().isoformat() == "2026-11-16"  # Monday
    assert period_start(MONTH, now).date().isoformat() == "2026-11-01"


async def test_phonebook_from_todo_list_and_save_caller(hass: HomeAssistant, pbx: FakePbx) -> None:
    from homeassistant.core import ServiceCall, SupportsResponse

    from custom_components.nec_pbx.const import CONF_PHONEBOOK_TODO

    items = [
        {"summary": "Jordan", "description": "0491 570 199", "uid": "1", "status": "needs_action"}
    ]

    async def get_items(call: ServiceCall):
        return {"todo.phonebook": {"items": list(items)}}

    async def add_item(call: ServiceCall) -> None:
        items.append(
            {"summary": call.data["item"], "description": call.data.get("description"), "uid": "2"}
        )
        hass.states.async_set("todo.phonebook", str(len(items)))

    hass.services.async_register(
        "todo", "get_items", get_items, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register("todo", "add_item", add_item)
    hass.states.async_set("todo.phonebook", "1")
    calls = async_capture_events(hass, EVENT_CALL)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Teak phones",
        data={CONF_HOST: "127.0.0.1", CONF_PORT: pbx.port},
        options={CONF_EXTENSIONS: "103: Oliver", CONF_PHONEBOOK_TODO: "todo.phonebook"},
        unique_id=f"127.0.0.1:{pbx.port}",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    async with asyncio.timeout(3):
        await pbx.connected.wait()
    await _wait(hass, lambda: entry.runtime_data.phonebook.get("0491570199") == "Jordan")

    await pbx.send(f"IC 0001  {_hm(3)}  001   00:01:00  103   0491570199   0:05\r\n")
    await pbx.send(f"IC 0002  {_hm(2)}  001   00:00:30  103   0491570123   0:04\r\n")
    await _wait(hass, lambda: len(calls) == 2)
    assert calls[0].data["caller_name"] == "Jordan"
    assert calls[1].data["caller_name"] is None

    # Save the last caller from a notification button or the UI.
    result = await hass.services.async_call(
        DOMAIN, "save_caller", {"name": "Plumber"}, blocking=True, return_response=True
    )
    assert result == {"name": "Plumber", "number": "0491570123"}
    assert items[-1] == {"summary": "Plumber", "description": "0491570123", "uid": "2"}
    await _wait(hass, lambda: entry.runtime_data.phonebook.get("0491570123") == "Plumber")
    assert await hass.config_entries.async_unload(entry.entry_id)
