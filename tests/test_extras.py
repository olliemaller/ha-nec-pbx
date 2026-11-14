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
    await _wait(hass, lambda: hass.states.get("sensor.teak_phones_calls_today").state == "3")
    talk = hass.states.get("sensor.teak_phones_talk_time_today")
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
        patch("custom_components.nec_pbx.client.RECONNECT_MIN", 0.6),
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
        assert issue.translation_placeholders["name"] == "Teak phones"

        # The phone system comes back: the repair goes away by itself.
        await pbx.start_on(pbx.port)
        async with asyncio.timeout(5):
            await pbx.connected.wait()
        await _wait(hass, lambda: registry.async_get_issue(DOMAIN, issue_id) is None, timeout=5)
        assert await hass.config_entries.async_unload(entry.entry_id)
