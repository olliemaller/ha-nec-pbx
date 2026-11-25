"""Talk time, logbook lines and the call-log outage repair."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
import pytest

from custom_components.nec_pbx.const import DOMAIN, ISSUE_UNREACHABLE
from custom_components.nec_pbx.logbook import describe_call

from .test_init import FakePbx, _hm, _setup, _wait, pbx  # noqa: F401


async def test_talk_time_counts_answered_calls_only(hass: HomeAssistant, pbx: FakePbx) -> None:  # noqa: F811
    entry = await _setup(hass, pbx)
    await pbx.send(f"IC 0001  {_hm(4)}  001   00:02:35  103   0491570156   0:08\r\n")
    await pbx.send(f"OG 0002  {_hm(3)}  001   00:01:05  104   0491570157\r\n")
    await pbx.send(f"IC 0003  {_hm(1)}  001                 104   0491570157   0:21  NO ANSWER\r\n")
    await _wait(hass, lambda: hass.states.get("sensor.home_phones_calls_today").state == "3")
    talk = hass.states.get("sensor.home_phones_talk_time_today")
    assert talk.attributes["unit_of_measurement"] == "min"
    assert float(talk.state) == pytest.approx((155 + 65) / 60, abs=0.01)
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    ("data", "text"),
    [
        (
            {
                "missed": True,
                "direction": "incoming",
                "caller_name": "Sam",
                "number": "0491570157",
                "station_name": "Family",
                "ring_time": 21,
            },
            "missed call from Sam (0491570157) to Family, rang 21 s",
        ),
        (
            {
                "missed": False,
                "direction": "incoming",
                "number": "0491570156",
                "station": "103",
                "duration": 155,
            },
            "call from 0491570156 answered on 103, 2 min 35 s",
        ),
        (
            {
                "missed": False,
                "direction": "outgoing",
                "number": "0491570157",
                "caller_name": "Sam",
                "station_name": "Oliver",
                "duration": 60,
            },
            "Oliver called Sam (0491570157), 1 min",
        ),
        (
            {"missed": False, "direction": "internal", "station_name": "Pantry"},
            "internal call from Pantry",
        ),
        ({"missed": False, "direction": "outgoing"}, "outgoing call"),
    ],
)
def test_logbook_sentences(data: dict, text: str) -> None:
    assert describe_call(data) == text


async def test_outage_raises_and_clears_a_repair(hass: HomeAssistant, pbx: FakePbx) -> None:  # noqa: F811
    with (
        patch("custom_components.nec_pbx.OUTAGE_ISSUE_AFTER", timedelta(seconds=0.2)),
        patch("aionecpbx.client.RECONNECT_MIN", 0.6),
    ):
        entry = await _setup(hass, pbx)
        issue_id = ISSUE_UNREACHABLE.format(entry.entry_id)
        registry = ir.async_get(hass)
        assert registry.async_get_issue(DOMAIN, issue_id) is None

        # Stop answering, then drop the connection: the repair appears after the outage time.
        pbx.server.close()
        await pbx.drop_clients()
        await _wait(hass, lambda: registry.async_get_issue(DOMAIN, issue_id) is not None)
        issue = registry.async_get_issue(DOMAIN, issue_id)
        assert issue.translation_key == "call_log_unreachable"
        assert issue.translation_placeholders["name"] == "Home phones"

        # The phone system comes back: the repair goes away by itself.
        await pbx.start_on(pbx.port)
        async with asyncio.timeout(5):
            await pbx.connected.wait()
        await _wait(hass, lambda: registry.async_get_issue(DOMAIN, issue_id) is None, timeout=5)
        assert await hass.config_entries.async_unload(entry.entry_id)


def test_phonebook_from_todo_items() -> None:
    from custom_components.nec_pbx import parse_todo_items

    items = [
        {"summary": "Alex", "description": "0491 570 156"},
        {"summary": "Sam 0491 570 157"},
        {"summary": "Mum: +61 491 570 006"},
        {"summary": "Buy milk"},
        {"summary": "", "description": "0491570158"},
    ]
    assert parse_todo_items(items) == {
        "0491570156": "Alex",
        "0491570157": "Sam",
        "0491570006": "Mum",
    }


async def test_missed_calls_go_on_a_to_do_list(
    hass: HomeAssistant,
    pbx: FakePbx,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    from homeassistant.const import CONF_HOST, CONF_PORT
    from homeassistant.core import ServiceCall, SupportsResponse
    from homeassistant.exceptions import HomeAssistantError
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.nec_pbx.const import CONF_EXTENSIONS, CONF_MISSED_TODO, CONF_PHONEBOOK

    items: list[dict] = []
    fail = False

    async def get_items(call: ServiceCall):
        wanted = call.data["status"]
        return {"todo.call_back": {"items": [i for i in items if i["status"] in wanted]}}

    async def add_item(call: ServiceCall) -> None:
        if fail:
            raise HomeAssistantError("list is read-only")
        uid = str(len(items) + 1)
        items.append({"summary": call.data["item"], "uid": uid, "status": "needs_action"})

    async def update_item(call: ServiceCall) -> None:
        for item in items:
            if item["uid"] == call.data["item"]:
                item["status"] = call.data["status"]

    hass.services.async_register(
        "todo", "get_items", get_items, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register("todo", "add_item", add_item)
    hass.services.async_register("todo", "update_item", update_item)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Home phones",
        data={CONF_HOST: "127.0.0.1", CONF_PORT: pbx.port},
        options={
            CONF_EXTENSIONS: "103: Oliver\n104: Family",
            CONF_PHONEBOOK: "0491570157: Sam",
            CONF_MISSED_TODO: "todo.call_back",
        },
        unique_id=f"127.0.0.1:{pbx.port}",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    async with asyncio.timeout(3):
        await pbx.connected.wait()

    await pbx.send(f"IC 0001  {_hm(5)}  001                 104   0491570157   0:21  NO ANSWER\r\n")
    await pbx.send(f"IC 0002  {_hm(5)}  001                 104   04915701XX   0:10  NO ANSWER\r\n")
    await pbx.send(f"IC 0003  {_hm(4)}  001   00:01:00  103   0491570199   0:05\r\n")
    await _wait(hass, lambda: hass.states.get("sensor.family_missed_calls_today").state == "2")
    await hass.async_block_till_done()
    assert len(items) == 1  # the hidden number and the answered call add nothing
    assert items[0]["summary"].startswith("Call back 0491570157 (Sam) missed ")
    assert items[0]["summary"].endswith("m at Family")
    assert hass.states.get("sensor.oliver_missed_calls_today").state == "0"

    # Calling Sam back ticks the item off.
    await pbx.send(f"OG 0004  {_hm(2)}  002   00:01:00  103   0491570157\r\n")
    await _wait(hass, lambda: items[0]["status"] == "completed")

    # A list that refuses the item is logged, not raised.
    fail = True
    await pbx.send(f"IC 0005  {_hm(1)}  001                 103   0491570158   0:21  NO ANSWER\r\n")
    await _wait(hass, lambda: "Couldn't update the missed-call list" in caplog.text)
    assert hass.states.get("sensor.oliver_missed_calls_today").state == "1"
    assert await hass.config_entries.async_unload(entry.entry_id)


def test_missed_todo_text() -> None:
    from datetime import datetime

    from aionecpbx.smdr import SmdrRecord
    from homeassistant.util import dt as dt_util

    from custom_components.nec_pbx import missed_todo_text

    start = datetime(2026, 11, 24, 15, 42, tzinfo=dt_util.get_default_time_zone())
    record = SmdrRecord(
        "", number="0491570156", caller_name="Alex", station="100", station_name="Reception"
    )
    record.start = start
    assert missed_todo_text(record) == "Call back 0491570156 (Alex) missed 3:42 pm at Reception"
    record.start, record.caller_name, record.station_name = start.replace(hour=0), None, None
    assert missed_todo_text(record) == "Call back 0491570156 missed 12:42 am at extension 100"
    assert missed_todo_text(SmdrRecord("", number="0491570156")) == "Call back 0491570156"
