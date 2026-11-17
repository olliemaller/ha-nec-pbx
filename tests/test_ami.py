"""Live calls from FreePBX over the Asterisk manager interface (a fake AMI server)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import contextlib

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.nec_pbx.ami import parse_message
from custom_components.nec_pbx.const import (
    CONF_AMI_HOST,
    CONF_AMI_PORT,
    CONF_AMI_SECRET,
    CONF_AMI_USER,
    CONF_DND_EXTENSIONS,
    CONF_EXTENSIONS,
    CONF_PHONEBOOK,
    DOMAIN,
    EVENT_RINGING,
)

from .test_init import FakePbx, _wait


class FakeAmi:
    """Enough of Asterisk's manager to log in, send call events and keep DND."""

    def __init__(self, secret: str = "s3cret") -> None:
        self.secret = secret
        self.writers: list[asyncio.StreamWriter] = []
        self.logged_in = asyncio.Event()
        self.db: dict[str, str] = {}
        self.server: asyncio.Server | None = None
        self.port = 0

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(b"Asterisk Call Manager/9.0.0\r\n")
        await writer.drain()
        buffer: list[str] = []
        try:
            while raw := await reader.readline():
                line = raw.decode().rstrip("\r\n")
                if line:
                    buffer.append(line)
                    continue
                if buffer:
                    await self._action(parse_message("\n".join(buffer)), writer)
                    buffer = []
        except (ConnectionError, asyncio.CancelledError):
            pass

    async def _action(self, msg: dict[str, str], writer: asyncio.StreamWriter) -> None:
        aid = msg.get("ActionID", "")
        action = msg.get("Action", "").lower()
        if action == "login":
            ok = msg.get("Secret") == self.secret
            reply = "Success" if ok else "Error"
            text = "Authentication accepted" if ok else "Authentication failed"
            writer.write(
                f"Response: {reply}\r\nActionID: {aid}\r\nMessage: {text}\r\n\r\n".encode()
            )
            if ok:
                self.writers.append(writer)
                self.logged_in.set()
        elif action == "dbput":
            self.db[f"{msg['Family']}/{msg['Key']}"] = msg["Val"]
            writer.write(
                f"Response: Success\r\nActionID: {aid}\r\nMessage: Updated database successfully\r\n\r\n".encode()
            )
        elif action == "dbdel":
            self.db.pop(f"{msg['Family']}/{msg['Key']}", None)
            writer.write(
                f"Response: Success\r\nActionID: {aid}\r\nMessage: Key deleted successfully\r\n\r\n".encode()
            )
        elif action == "dbget":
            key = f"{msg['Family']}/{msg['Key']}"
            if key in self.db:
                writer.write(
                    f"Response: Success\r\nActionID: {aid}\r\nEventList: start\r\nMessage: Result will follow\r\n\r\n".encode()
                )
                writer.write(
                    f"Event: DBGetResponse\r\nFamily: {msg['Family']}\r\nKey: {msg['Key']}\r\nVal: {self.db[key]}\r\nActionID: {aid}\r\n\r\n".encode()
                )
            else:
                writer.write(
                    f"Response: Error\r\nActionID: {aid}\r\nMessage: Database entry not found\r\n\r\n".encode()
                )
        else:
            writer.write(f"Response: Success\r\nActionID: {aid}\r\n\r\n".encode())
        await writer.drain()

    async def event(self, **fields: str) -> None:
        text = "".join(f"{k}: {v}\r\n" for k, v in fields.items()) + "\r\n"
        for writer in self.writers:
            writer.write(text.encode())
            await writer.drain()

    async def stop(self) -> None:
        for writer in self.writers:
            writer.close()
        if self.server:
            self.server.close()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.server.wait_closed(), 1)


@pytest.fixture
async def ami(hass: HomeAssistant, socket_enabled) -> AsyncIterator[tuple[FakePbx, FakeAmi]]:
    pbx, fake = FakePbx(), FakeAmi()
    await pbx.start()
    await fake.start()
    yield pbx, fake
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)
    await fake.stop()
    await pbx.stop()


async def _setup(
    hass: HomeAssistant, pbx: FakePbx, fake: FakeAmi, secret: str = "s3cret"
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Teak phones",
        data={CONF_HOST: "127.0.0.1", CONF_PORT: pbx.port},
        options={
            CONF_EXTENSIONS: "901: NEC Line 2",
            CONF_PHONEBOOK: "0491570156: Alex",
            CONF_AMI_HOST: "127.0.0.1",
            CONF_AMI_PORT: fake.port,
            CONF_AMI_USER: "homeassistant",
            CONF_AMI_SECRET: secret,
            CONF_DND_EXTENSIONS: "901",
        },
        unique_id=f"127.0.0.1:{pbx.port}",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_ringing_answered_ended(hass: HomeAssistant, ami) -> None:
    pbx, fake = ami
    ringing = async_capture_events(hass, EVENT_RINGING)
    entry = await _setup(hass, pbx, fake)
    async with asyncio.timeout(3):
        await fake.logged_in.wait()
    await _wait(
        hass, lambda: hass.states.get("binary_sensor.teak_phones_freepbx_connection").state == "on"
    )

    await fake.event(
        Event="Newchannel",
        Uniqueid="1.1",
        Linkedid="1.1",
        ChannelStateDesc="Ring",
        CallerIDNum="0491570156",
        CallerIDName="<unknown>",
        Exten="901",
    )
    await fake.event(
        Event="DialBegin",
        Uniqueid="1.1",
        Linkedid="1.1",
        CallerIDNum="0491570156",
        DestCallerIDNum="901",
    )
    await _wait(hass, lambda: hass.states.get("binary_sensor.teak_phones_ringing").state == "on")
    assert ringing and ringing[0].data["caller_name"] == "Alex"
    assert ringing[0].data["station_name"] == "NEC Line 2"
    assert hass.states.get("sensor.teak_phones_current_caller").state == "Alex"
    assert hass.states.get("event.teak_phones_live_call").attributes["event_type"] == "ringing"

    await fake.event(
        Event="DialEnd", Uniqueid="1.1", Linkedid="1.1", DialStatus="ANSWER", DestCallerIDNum="901"
    )
    await _wait(hass, lambda: hass.states.get("binary_sensor.teak_phones_on_a_call").state == "on")
    assert hass.states.get("binary_sensor.teak_phones_ringing").state == "off"

    await fake.event(Event="Hangup", Uniqueid="1.1", Linkedid="1.1")
    await _wait(hass, lambda: hass.states.get("binary_sensor.teak_phones_on_a_call").state == "off")
    assert hass.states.get("event.teak_phones_live_call").attributes["event_type"] == "ended"
    assert hass.states.get("sensor.teak_phones_current_caller").state == "none"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_do_not_disturb_switch(hass: HomeAssistant, ami) -> None:
    pbx, fake = ami
    entry = await _setup(hass, pbx, fake)
    async with asyncio.timeout(3):
        await fake.logged_in.wait()
    switch = "switch.teak_phones_do_not_disturb_901"
    await _wait(hass, lambda: hass.states.get(switch).state != "unavailable")
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    assert fake.db["DND/901"] == "YES"
    assert hass.states.get(switch).state == "on"
    await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
    assert "DND/901" not in fake.db
    # Set from a phone (*76): the next check picks it up.
    fake.db["DND/901"] = "YES"
    from homeassistant.helpers.entity_component import async_update_entity

    await async_update_entity(hass, switch)
    assert hass.states.get(switch).state == "on"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_wrong_ami_password_stops_trying(hass: HomeAssistant, ami) -> None:
    pbx, fake = ami
    entry = await _setup(hass, pbx, fake, secret="wrong")
    client = entry.runtime_data.ami
    await _wait(
        hass, lambda: client.last_error is not None and client.last_error.startswith("login")
    )
    assert hass.states.get("binary_sensor.teak_phones_freepbx_connection").state == "off"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_announcement_blueprint(hass: HomeAssistant, ami) -> None:
    from pathlib import Path
    import shutil

    from homeassistant.core import ServiceCall
    from homeassistant.setup import async_setup_component
    from homeassistant.util import dt as dt_util

    pbx, fake = ami
    await _setup(hass, pbx, fake)
    async with asyncio.timeout(3):
        await fake.logged_in.wait()
    name = "caller_announcement.yaml"
    source = Path(__file__).parent.parent / "blueprints/automation/nec_pbx" / name
    target = Path(hass.config.path("blueprints/automation/nec_pbx"))
    await hass.async_add_executor_job(lambda: target.mkdir(parents=True, exist_ok=True))
    await hass.async_add_executor_job(shutil.copy, source, target / name)
    spoken: list[dict] = []

    async def speak(call: ServiceCall) -> None:
        spoken.append(dict(call.data))

    hass.services.async_register("tts", "speak", speak)
    # Quiet hours that never cover now.
    now = dt_util.now()
    quiet_from = (now + __import__("datetime").timedelta(hours=2)).strftime("%H:%M:00")
    quiet_until = (now + __import__("datetime").timedelta(hours=3)).strftime("%H:%M:00")
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "id": "announce",
                "use_blueprint": {
                    "path": f"nec_pbx/{name}",
                    "input": {
                        "live_call": "event.teak_phones_live_call",
                        "tts_engine": "tts.piper",
                        "speakers": ["media_player.kitchen"],
                        "quiet_from": quiet_from,
                        "quiet_until": quiet_until,
                    },
                },
            }
        },
    )
    await hass.async_block_till_done()
    await fake.event(
        Event="Newchannel",
        Uniqueid="2.1",
        Linkedid="2.1",
        ChannelStateDesc="Ring",
        CallerIDNum="0491570156",
        CallerIDName="",
        Exten="901",
    )
    for _ in range(100):
        await asyncio.sleep(0.02)
        if spoken:
            break
    assert spoken[0]["message"] == "Phone call from Alex"
    assert spoken[0]["media_player_entity_id"] == ["media_player.kitchen"]
    await hass.services.async_call(
        "automation", "turn_off", {"entity_id": "automation.automation_0"}, blocking=True
    )
