"""The optional AI attendant add-on, against a fake nec-ai-attendant engine."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
import json
from typing import Any
from unittest.mock import AsyncMock, patch

from aiohttp import web
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.nec_pbx import async_remove_config_entry_device
from custom_components.nec_pbx.attendant import (
    AttendantApi,
    AttendantAuthError,
    AttendantError,
    normalise_url,
    valid_url,
)
from custom_components.nec_pbx.const import (
    ATTENDANT_POLL,
    ATTENDANT_POLL_WITH_EVENTS,
    CONF_ATTENDANT_TOKEN,
    CONF_ATTENDANT_URL,
    CONF_EXTENSIONS,
    CONF_PHONEBOOK,
    DOMAIN,
    ISSUE_ATTENDANT_AUTH,
)
from custom_components.nec_pbx.diagnostics import async_get_config_entry_diagnostics

from .test_init import FakePbx, _wait, pbx  # noqa: F401

TOKEN = "test-token-0491"
SETUP = "custom_components.nec_pbx.async_setup_entry"

SWITCH = "switch.ai_attendant_answer_outside_calls"
NEW_MESSAGES = "sensor.ai_attendant_new_messages"
LAST_CALL = "sensor.ai_attendant_last_call"
RESPONSE_TIME = "sensor.ai_attendant_average_response_time"
IN_PROGRESS = "binary_sensor.ai_attendant_call_in_progress"


class FakeEngine:
    """Just enough of the nec-ai-attendant HTTP API, with made-up callers."""

    def __init__(self) -> None:
        self.token = TOKEN
        self.fail = False  # answer every request with HTTP 500
        self.status: dict[str, Any] = {
            "version": "1.0.0",
            "uptime_s": 3600,
            "answering_outside": True,
            "active_calls": 0,
            "models": {"stt": "whisper-small", "tts": "piper", "llm": "llama3.2"},
            "last_call_at": "2026-11-28T10:15:00+11:00",
        }
        self.messages: list[dict[str, Any]] = [
            {
                "id": "m1",
                "call_id": "c1",
                "created_at": "2026-11-28T09:00:00+11:00",
                "for_person": "Sam",
                "caller_name": "Alex",
                "callback_number": "0491570156",
                "message": "Running late, back by six.",
                "status": "new",
            },
            {
                "id": "m2",
                "call_id": "c2",
                "created_at": "2026-11-28T10:00:00+11:00",
                "for_person": "Jordan",
                "caller_name": "Taylor",
                "callback_number": "0491570157",
                "message": "Please call back about Saturday.",
                "status": "new",
            },
        ]
        self.calls: list[dict[str, Any]] = [
            {
                "id": "c2",
                "started_at": "2026-11-28T10:15:00+11:00",
                "ended_at": "2026-11-28T10:16:05+11:00",
                "caller": "0491570157",
                "caller_name": "Taylor",
                "mode": "outside",
                "outcome": "message",
                "target": "Jordan",
                "duration_s": 65,
                "first_words_ms_avg": 1100,
                "recording": False,
            }
        ]
        self.stats: dict[str, Any] = {
            "per_day": [],
            "avg_first_words_ms": 1234,
            "avg_stt_ms": 310,
            "avg_llm_ms": 650,
        }
        self.requests: list[tuple[str, str, Any]] = []
        self.sockets: list[web.WebSocketResponse] = []
        self.ws_connected = asyncio.Event()
        self.ws_refuse = False
        self.port = 0
        self._runner: web.AppRunner | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _check(self, request: web.Request) -> None:
        if request.headers.get("Authorization") != f"Bearer {self.token}":
            raise web.HTTPUnauthorized
        if self.fail:
            raise web.HTTPInternalServerError

    async def _status(self, request: web.Request) -> web.Response:
        self._check(request)
        return web.json_response(self.status)

    async def _messages(self, request: web.Request) -> web.Response:
        self._check(request)
        status = request.query.get("status", "all")
        return web.json_response(
            [m for m in self.messages if status == "all" or m["status"] == status]
        )

    async def _message(self, request: web.Request) -> web.Response:
        self._check(request)
        body = await request.json()
        self.requests.append(("POST", request.path, body))
        for message in self.messages:
            if message["id"] == request.match_info["id"]:
                message["status"] = body["status"]
                return web.json_response(message)
        raise web.HTTPNotFound

    async def _calls(self, request: web.Request) -> web.Response:
        self._check(request)
        return web.json_response(self.calls[: int(request.query.get("limit", "50"))])

    async def _stats(self, request: web.Request) -> web.Response:
        self._check(request)
        self.requests.append(("GET", request.path, request.query.get("days")))
        return web.json_response(self.stats)

    async def _settings(self, request: web.Request) -> web.Response:
        self._check(request)
        body = await request.json()
        self.requests.append(("PUT", request.path, body))
        if "answering_outside" in body:
            self.status["answering_outside"] = body["answering_outside"]
        return web.Response(status=204)

    async def _events(self, request: web.Request) -> web.WebSocketResponse:
        if self.ws_refuse:
            raise web.HTTPUnauthorized
        self._check(request)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.sockets.append(ws)
        self.ws_connected.set()
        async for _msg in ws:
            pass
        return ws

    async def push(self, event: dict[str, Any] | str) -> None:
        for ws in self.sockets:
            await ws.send_str(event if isinstance(event, str) else json.dumps(event))

    async def drop_sockets(self) -> None:
        self.ws_connected.clear()
        for ws in list(self.sockets):
            await ws.close()
        self.sockets.clear()

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/api/status", self._status)
        app.router.add_get("/api/messages", self._messages)
        app.router.add_post("/api/messages/{id}", self._message)
        app.router.add_get("/api/calls", self._calls)
        app.router.add_get("/api/stats", self._stats)
        app.router.add_put("/api/settings", self._settings)
        app.router.add_get("/api/events", self._events)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]

    async def stop(self) -> None:
        await self.drop_sockets()
        if self._runner:
            await self._runner.cleanup()


@pytest.fixture
async def engine(hass: HomeAssistant, socket_enabled) -> AsyncIterator[FakeEngine]:
    fake = FakeEngine()
    await fake.start()
    yield fake
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)
    await fake.stop()


@pytest.fixture(autouse=True)
def fast_retry() -> AsyncIterator[None]:
    """Reconnect the websocket quickly in tests."""
    with (
        patch("custom_components.nec_pbx.attendant.ATTENDANT_RETRY_MIN", 0.05),
        patch("custom_components.nec_pbx.attendant.ATTENDANT_RETRY_MAX", 0.1),
    ):
        yield


async def _setup(
    hass: HomeAssistant,
    pbx: FakePbx,  # noqa: F811
    engine: FakeEngine,
    *,
    url: str | None = None,
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Home phones",
        data={CONF_HOST: "127.0.0.1", CONF_PORT: pbx.port},
        options={
            CONF_EXTENSIONS: "103: Alex",
            CONF_PHONEBOOK: "0491570156: Alex",
            CONF_ATTENDANT_URL: url or engine.url,
            CONF_ATTENDANT_TOKEN: TOKEN,
        },
        unique_id=f"127.0.0.1:{pbx.port}",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _device(hass: HomeAssistant, entry: MockConfigEntry, identifier: str) -> dr.DeviceEntry:
    """Works before and after Home Assistant deprecated async_get_device."""
    return next(
        device
        for device in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
        if (DOMAIN, identifier) in device.identifiers
    )


async def _refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.attendant.async_refresh()
    await hass.async_block_till_done()


async def test_entities_from_the_engine(
    hass: HomeAssistant,
    pbx: FakePbx,  # noqa: F811
    engine: FakeEngine,
) -> None:
    entry = await _setup(hass, pbx, engine)

    assert hass.states.get(SWITCH).state == "on"
    assert hass.states.get(IN_PROGRESS).state == "off"
    assert hass.states.get(IN_PROGRESS).attributes["active_calls"] == 0

    new = hass.states.get(NEW_MESSAGES)
    assert new.state == "2"
    messages = new.attributes["messages"]
    assert [m["id"] for m in messages] == ["m2", "m1"]  # newest first
    assert messages[0]["caller_name"] == "Taylor"
    assert messages[0]["callback_number"] == "0491570157"
    assert "status" not in messages[0]

    last = hass.states.get(LAST_CALL)
    assert dt_util.parse_datetime(last.state) == dt_util.parse_datetime("2026-11-28T10:15:00+11:00")
    assert last.attributes["caller_name"] == "Taylor"
    assert last.attributes["outcome"] == "message"
    assert last.attributes["duration_s"] == 65

    response = hass.states.get(RESPONSE_TIME)
    assert float(response.state) == pytest.approx(1.234)
    assert response.attributes["unit_of_measurement"] == "s"
    assert response.attributes["speech_to_text_ms"] == 310
    assert ("GET", "/api/stats", "7") in engine.requests

    device = _device(hass, entry, f"{entry.entry_id}_attendant")
    assert device.name == "AI attendant"
    assert device.sw_version == "1.0.0"
    pbx_device = _device(hass, entry, entry.entry_id)
    assert device.via_device_id == pbx_device.id
    # While it's set up, its device can't be deleted.
    assert not await async_remove_config_entry_device(hass, entry, device)

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_no_attendant_by_default(hass: HomeAssistant, pbx: FakePbx) -> None:  # noqa: F811
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Home phones",
        data={CONF_HOST: "127.0.0.1", CONF_PORT: pbx.port},
        unique_id=f"127.0.0.1:{pbx.port}",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.attendant is None
    assert hass.states.get(SWITCH) is None
    assert hass.states.get(NEW_MESSAGES) is None
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["ai_attendant"] is None
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "attendant_set_answering", {"enabled": False}, blocking=True
        )
    assert err.value.translation_key == "attendant_not_set_up"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_switch_turns_answering_off_and_on(
    hass: HomeAssistant,
    pbx: FakePbx,  # noqa: F811
    engine: FakeEngine,
) -> None:
    entry = await _setup(hass, pbx, engine)
    await hass.services.async_call("switch", "turn_off", {"entity_id": SWITCH}, blocking=True)
    assert ("PUT", "/api/settings", {"answering_outside": False}) in engine.requests
    assert hass.states.get(SWITCH).state == "off"
    await hass.services.async_call("switch", "turn_on", {"entity_id": SWITCH}, blocking=True)
    assert engine.status["answering_outside"] is True
    assert hass.states.get(SWITCH).state == "on"

    engine.fail = True
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call("switch", "turn_off", {"entity_id": SWITCH}, blocking=True)
    assert err.value.translation_key == "attendant_failed"
    assert hass.states.get(SWITCH).state == "on"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_services(
    hass: HomeAssistant,
    pbx: FakePbx,  # noqa: F811
    engine: FakeEngine,
) -> None:
    entry = await _setup(hass, pbx, engine)
    await hass.services.async_call(
        DOMAIN, "attendant_mark_message_done", {"message_id": "m2"}, blocking=True
    )
    await hass.async_block_till_done()
    assert ("POST", "/api/messages/m2", {"status": "done"}) in engine.requests
    assert hass.states.get(NEW_MESSAGES).state == "1"
    assert hass.states.get(NEW_MESSAGES).attributes["messages"][0]["id"] == "m1"

    await hass.services.async_call(
        DOMAIN,
        "attendant_set_answering",
        {"enabled": False, "config_entry_id": entry.entry_id},
        blocking=True,
    )
    assert engine.status["answering_outside"] is False
    assert hass.states.get(SWITCH).state == "off"

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            DOMAIN, "attendant_mark_message_done", {"message_id": "nope"}, blocking=True
        )
    assert err.value.translation_key == "attendant_failed"

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "attendant_set_answering",
            {"enabled": True, "config_entry_id": "not-an-entry"},
            blocking=True,
        )
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_live_events_over_the_websocket(
    hass: HomeAssistant,
    pbx: FakePbx,  # noqa: F811
    engine: FakeEngine,
) -> None:
    entry = await _setup(hass, pbx, engine)
    coordinator = entry.runtime_data.attendant
    async with asyncio.timeout(3):
        await engine.ws_connected.wait()
    await _wait(hass, lambda: coordinator.events_connected)
    assert coordinator.update_interval == ATTENDANT_POLL_WITH_EVENTS

    # A call starts: shown straight away, then the engine is asked for the details.
    engine.status["active_calls"] = 1
    await engine.push({"type": "call_started", "data": {"call_id": "c3"}})
    await _wait(hass, lambda: hass.states.get(IN_PROGRESS).state == "on")

    # Turns, other types and junk are ignored.
    await engine.push({"type": "turn", "data": {"role": "caller", "text": "Hello"}})
    await engine.push({"type": "something_new"})
    await engine.push("not json")
    await engine.push("[1, 2]")

    # A message arrives and is shown at once.
    message = {
        "id": "m3",
        "call_id": "c3",
        "created_at": "2026-11-28T11:00:00+11:00",
        "for_person": "Sam",
        "caller_name": "Jordan",
        "callback_number": "0491570158",
        "message": "See you at the park.",
        "status": "new",
    }
    engine.messages.append(message)
    await engine.push({"type": "message", "data": message})
    await _wait(hass, lambda: hass.states.get(NEW_MESSAGES).state == "3")
    assert hass.states.get(NEW_MESSAGES).attributes["messages"][0]["id"] == "m3"

    # The call ends.
    engine.status["active_calls"] = 0
    await engine.push({"type": "call_ended", "data": {"call_id": "c3"}})
    await _wait(hass, lambda: hass.states.get(IN_PROGRESS).state == "off")

    # The websocket drops: back to polling every 30 seconds, then it reconnects.
    await engine.drop_sockets()
    await _wait(hass, lambda: not coordinator.events_connected)
    assert coordinator.update_interval == ATTENDANT_POLL
    async with asyncio.timeout(3):
        await engine.ws_connected.wait()
    await _wait(hass, lambda: coordinator.events_connected)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_websocket_refused_keeps_polling(
    hass: HomeAssistant,
    pbx: FakePbx,  # noqa: F811
    engine: FakeEngine,
) -> None:
    engine.ws_refuse = True
    entry = await _setup(hass, pbx, engine)
    await asyncio.sleep(0.3)  # a few refused attempts
    coordinator = entry.runtime_data.attendant
    assert not coordinator.events_connected
    assert coordinator.update_interval == ATTENDANT_POLL
    assert hass.states.get(NEW_MESSAGES).state == "2"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_engine_down_leaves_the_phone_system_working(
    hass: HomeAssistant,
    pbx: FakePbx,  # noqa: F811
    engine: FakeEngine,
) -> None:
    url = engine.url
    await engine.stop()
    entry = await _setup(hass, pbx, engine, url=url)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(NEW_MESSAGES).state == "unavailable"
    assert hass.states.get(SWITCH).state == "unavailable"
    assert hass.states.get("binary_sensor.home_phones_call_log_connection") is not None
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["ai_attendant"]["last_update_success"] is False
    assert diag["ai_attendant"]["last_error"]
    assert diag["ai_attendant"]["new_messages"] is None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_rejected_token_raises_a_repair(
    hass: HomeAssistant,
    pbx: FakePbx,  # noqa: F811
    engine: FakeEngine,
) -> None:
    engine.token = "changed"
    entry = await _setup(hass, pbx, engine)
    issue_id = ISSUE_ATTENDANT_AUTH.format(entry.entry_id)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    assert hass.states.get(NEW_MESSAGES).state == "unavailable"
    assert entry.runtime_data.attendant.last_error == "token rejected"

    engine.token = TOKEN
    async_fire_time_changed(hass, dt_util.utcnow() + ATTENDANT_POLL + timedelta(seconds=1))
    await _wait(hass, lambda: hass.states.get(NEW_MESSAGES).state == "2")
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None

    engine.token = "changed"
    await _refresh(hass, entry)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
    # Unloading clears it; a reload would raise it again if it still fails.
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_diagnostics_redact_the_token(
    hass: HomeAssistant,
    pbx: FakePbx,  # noqa: F811
    engine: FakeEngine,
) -> None:
    entry = await _setup(hass, pbx, engine)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(diag)
    assert TOKEN not in text
    assert "0491570157" not in text  # no callers or messages
    attendant = diag["ai_attendant"]
    assert attendant[CONF_ATTENDANT_TOKEN] == "**REDACTED**"
    assert attendant[CONF_ATTENDANT_URL] == engine.url
    assert attendant["version"] == "1.0.0"
    assert attendant["new_messages"] == 2
    assert attendant["last_call_outcome"] == "message"
    assert attendant["answering_outside"] is True
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_attendant_device_removable_once_turned_off(
    hass: HomeAssistant,
    pbx: FakePbx,  # noqa: F811
    engine: FakeEngine,
) -> None:
    entry = await _setup(hass, pbx, engine)
    device = _device(hass, entry, f"{entry.entry_id}_attendant")
    entry.runtime_data.attendant = None
    assert await async_remove_config_entry_device(hass, entry, device)
    assert await hass.config_entries.async_unload(entry.entry_id)


# Options flow


def _options_entry(hass: HomeAssistant, **options: Any) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: "192.0.2.10", CONF_PORT: 4001}, options=options
    )
    entry.add_to_hass(hass)
    return entry


async def _submit(hass: HomeAssistant, entry: MockConfigEntry, data: dict[str, Any]) -> Any:
    with patch(SETUP, AsyncMock(return_value=True)):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        return await hass.config_entries.options.async_configure(result["flow_id"], data)


async def test_options_enable_the_attendant(hass: HomeAssistant, engine: FakeEngine) -> None:
    entry = _options_entry(hass)
    result = await _submit(
        hass, entry, {CONF_ATTENDANT_URL: f" {engine.url}/ ", CONF_ATTENDANT_TOKEN: TOKEN}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ATTENDANT_URL] == engine.url
    assert entry.options[CONF_ATTENDANT_TOKEN] == TOKEN


@pytest.mark.parametrize(
    ("url", "token", "errors"),
    [
        ("192.0.2.20:8099", TOKEN, {CONF_ATTENDANT_URL: "attendant_bad_url"}),
        ("http://", TOKEN, {CONF_ATTENDANT_URL: "attendant_bad_url"}),
        (None, "wrong", {CONF_ATTENDANT_TOKEN: "attendant_auth"}),
        ("http://127.0.0.1:9", TOKEN, {CONF_ATTENDANT_URL: "attendant_cannot_connect"}),
    ],
)
async def test_options_attendant_errors(
    hass: HomeAssistant, engine: FakeEngine, url: str | None, token: str, errors: dict[str, str]
) -> None:
    entry = _options_entry(hass)
    result = await _submit(
        hass, entry, {CONF_ATTENDANT_URL: url or engine.url, CONF_ATTENDANT_TOKEN: token}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == errors
    assert CONF_ATTENDANT_URL not in entry.options


async def test_options_keep_the_saved_token(hass: HomeAssistant) -> None:
    entry = _options_entry(
        hass, **{CONF_ATTENDANT_URL: "http://192.0.2.20:8099", CONF_ATTENDANT_TOKEN: TOKEN}
    )
    status = AsyncMock()
    with patch("custom_components.nec_pbx.config_flow.AttendantApi.status", status):
        result = await _submit(hass, entry, {CONF_ATTENDANT_URL: "http://192.0.2.20:8099"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ATTENDANT_TOKEN] == TOKEN
    status.assert_not_awaited()  # nothing changed: the running entry already talks to it


async def test_options_clearing_the_address_turns_it_off(hass: HomeAssistant) -> None:
    entry = _options_entry(
        hass, **{CONF_ATTENDANT_URL: "http://192.0.2.20:8099", CONF_ATTENDANT_TOKEN: TOKEN}
    )
    result = await _submit(hass, entry, {CONF_ATTENDANT_URL: "  ", CONF_ATTENDANT_TOKEN: "x"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_ATTENDANT_URL not in entry.options
    assert CONF_ATTENDANT_TOKEN not in entry.options


# The API client on its own


async def test_api_edge_cases(hass: HomeAssistant, engine: FakeEngine) -> None:
    session = async_get_clientsession(hass)
    api = AttendantApi(session, engine.url + "/", TOKEN)
    assert api.url == engine.url
    assert api.events_url == f"ws://127.0.0.1:{engine.port}/api/events"
    assert AttendantApi(session, "https://pbx.example:8099", "").events_url == (
        "wss://pbx.example:8099/api/events"
    )
    assert AttendantApi(session, "http://192.0.2.20", "").headers == {}

    with pytest.raises(AttendantAuthError):
        await AttendantApi(session, engine.url, "wrong").status()
    with pytest.raises(AttendantError):
        await api.set_message_status("nope", "done")  # 404

    engine.status = ["not", "a", "status"]  # type: ignore[assignment]
    with pytest.raises(AttendantError):
        await api.status()
    engine.messages = {"not": "a list"}  # type: ignore[assignment]
    assert await api.messages("all") == []
    engine.stats = []  # type: ignore[assignment]
    assert await api.stats(7) == {}

    assert normalise_url(" http://192.0.2.20:8099/ ") == "http://192.0.2.20:8099"
    assert valid_url("https://192.0.2.20")
    assert not valid_url("ftp://192.0.2.20")


async def test_api_non_json_reply(hass: HomeAssistant, socket_enabled) -> None:
    async def html(_request: web.Request) -> web.Response:
        return web.Response(text="<html>a router login page</html>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/api/status", html)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    try:
        api = AttendantApi(async_get_clientsession(hass), f"http://127.0.0.1:{port}", "")
        with pytest.raises(AttendantError, match="JSON"):
            await api.status()
    finally:
        await runner.cleanup()


async def test_events_update_before_the_engine_is_asked(
    hass: HomeAssistant,
    pbx: FakePbx,  # noqa: F811
    engine: FakeEngine,
) -> None:
    entry = await _setup(hass, pbx, engine)
    coordinator = entry.runtime_data.attendant
    with patch.object(coordinator, "async_request_refresh", AsyncMock()) as refresh:
        coordinator.handle_event({"type": "call_started", "data": {}})
        await hass.async_block_till_done()
        assert hass.states.get(IN_PROGRESS).state == "on"
        coordinator.handle_event({"type": "call_ended", "data": {}})
        coordinator.handle_event({"type": "call_ended", "data": {}})  # never below 0
        await hass.async_block_till_done()
        assert hass.states.get(IN_PROGRESS).attributes["active_calls"] == 0
        coordinator.handle_event({"type": "message", "data": {"id": "m1", "status": "done"}})
        coordinator.handle_event({"type": "message", "data": {"id": "m9", "message": "Hi"}})
        await hass.async_block_till_done()
        assert hass.states.get(NEW_MESSAGES).state == "3"
        coordinator.handle_event({"type": "turn", "data": {}})
        assert refresh.await_count == 5
    assert await hass.config_entries.async_unload(entry.entry_id)
