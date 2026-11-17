"""Asterisk Manager Interface (AMI) client for live call state from FreePBX.

The NEC's call log (SMDR) only prints a line when a call ends. When calls also
pass through FreePBX (for example the lines bridged in with an ATA), Asterisk's
manager interface says the moment a phone starts ringing, is answered or hangs
up, and who is calling. This client logs in, listens to those events and keeps
a small table of live calls. It can also turn FreePBX's do-not-disturb on and
off per extension.

FreePBX: Settings > Asterisk Manager Users > Add Manager. Allow this Home
Assistant's address under "Permit", and give it at least read "call" and
"system" and write "system" (for do-not-disturb).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
from dataclasses import dataclass, field
import itertools
import logging
import time

_LOGGER = logging.getLogger(__name__)

DEFAULT_AMI_PORT = 5038
_RECONNECT_MIN = 5
_RECONNECT_MAX = 300
_TIMEOUT = 10

LIVE_RINGING = "ringing"
LIVE_ANSWERED = "answered"
LIVE_ENDED = "ended"


class AmiAuthError(Exception):
    """FreePBX rejected the manager login."""


@dataclass
class LiveCall:
    """One call in progress, as Asterisk sees it."""

    uniqueid: str
    caller_number: str | None = None
    caller_name: str | None = None
    extension: str | None = None  # the extension or number being rung
    state: str = LIVE_RINGING
    started: float = field(default_factory=time.time)
    answered: float | None = None


def parse_message(block: str) -> dict[str, str]:
    """``Key: value`` lines into a dict (first value wins for repeated keys)."""
    out: dict[str, str] = {}
    for line in block.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() and key.strip() not in out:
            out[key.strip()] = value.strip()
    return out


def _clean(value: str | None) -> str | None:
    if not value or value in ("<unknown>", "unknown", "s"):
        return None
    return value


class AmiClient:
    """Keeps an AMI connection, tracks live calls and calls back on changes."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        secret: str,
        on_change: Callable[[LiveCall, str], None],
        on_state: Callable[[bool], None] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self._username = username
        self._secret = secret
        self._on_change = on_change
        self._on_state = on_state
        self.calls: dict[str, LiveCall] = {}
        self.connected = False
        self.last_error: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._ids = itertools.count(1)
        self._pending: dict[str, asyncio.Future[dict[str, str]]] = {}
        self._auth_failed = False

    # ── lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(
                self._run(), name=f"nec_pbx ami {self.host}:{self.port}"
            )

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._close()
        self._set_connected(False)

    def _set_connected(self, value: bool) -> None:
        if value != self.connected:
            self.connected = value
            if self._on_state:
                self._on_state(value)

    async def _close(self) -> None:
        writer, self._writer = self._writer, None
        for future in self._pending.values():
            if not future.done():
                future.set_exception(ConnectionError("AMI connection closed"))
        self._pending.clear()
        if writer:
            writer.close()
            with contextlib.suppress(OSError, asyncio.CancelledError):
                await writer.wait_closed()

    async def _run(self) -> None:
        delay = _RECONNECT_MIN
        while not self._auth_failed:
            try:
                reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port), _TIMEOUT
                )
                await asyncio.wait_for(reader.readline(), _TIMEOUT)  # banner
                reader_task = asyncio.get_running_loop().create_task(self._read(reader))
                try:
                    reply = await self.action(
                        "Login", Username=self._username, Secret=self._secret, Events="call,system"
                    )
                    if reply.get("Response", "").lower() != "success":
                        raise AmiAuthError(reply.get("Message", "login rejected"))
                    _LOGGER.info("Connected to Asterisk manager at %s:%s", self.host, self.port)
                    self.last_error = None
                    self._set_connected(True)
                    delay = _RECONNECT_MIN
                    await reader_task
                finally:
                    reader_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await reader_task
            except AmiAuthError as err:
                self.last_error = f"login: {err}"
                self._auth_failed = True  # don't hammer FreePBX with a wrong password
                _LOGGER.error("Asterisk manager login rejected: %s", err)
            except (OSError, TimeoutError, ConnectionError, asyncio.IncompleteReadError) as err:
                self.last_error = f"connect: {err}"
                _LOGGER.debug("AMI %s:%s: %s", self.host, self.port, err)
            finally:
                await self._close()
                self._set_connected(False)
                self._end_all()
            if self._auth_failed:
                return
            await asyncio.sleep(delay)
            delay = min(delay * 2, _RECONNECT_MAX)

    # ── protocol ───────────────────────────────────────────────────────────

    async def action(self, name: str, **fields: str) -> dict[str, str]:
        """Send an action and wait for its response."""
        if self._writer is None:
            raise ConnectionError("not connected to the Asterisk manager")
        action_id = f"ha{next(self._ids)}"
        future: asyncio.Future[dict[str, str]] = asyncio.get_running_loop().create_future()
        self._pending[action_id] = future
        lines = [f"Action: {name}", f"ActionID: {action_id}"]
        lines += [f"{key}: {value}" for key, value in fields.items()]
        self._writer.write(("\r\n".join(lines) + "\r\n\r\n").encode())
        await self._writer.drain()
        try:
            return await asyncio.wait_for(future, _TIMEOUT)
        finally:
            self._pending.pop(action_id, None)

    async def _read(self, reader: asyncio.StreamReader) -> None:
        buffer: list[str] = []
        while True:
            raw = await reader.readline()
            if not raw:
                raise ConnectionError("closed by the Asterisk manager")
            line = raw.decode(errors="replace").rstrip("\r\n")
            if line:
                buffer.append(line)
                continue
            if buffer:
                self._handle(parse_message("\n".join(buffer)))
                buffer = []

    def _handle(self, msg: dict[str, str]) -> None:
        if "Response" in msg and "follow" in msg.get("Message", "").lower():
            return  # the answer comes in an event with the same ActionID (DBGet)
        if "Response" in msg or ("ActionID" in msg and "Event" not in msg):
            future = self._pending.get(msg.get("ActionID", ""))
            if future and not future.done():
                future.set_result(msg)
            return
        event = msg.get("Event")
        if event == "DBGetResponse":
            future = self._pending.get(msg.get("ActionID", ""))
            if future and not future.done():
                future.set_result(msg)
            return
        if event:
            try:
                self._call_event(event, msg)
            except Exception:  # a strange event must never drop the connection
                _LOGGER.exception("Error handling AMI event %s", event)

    def _call_event(self, event: str, msg: dict[str, str]) -> None:
        uid = msg.get("Linkedid") or msg.get("Uniqueid")
        if not uid:
            return
        call = self.calls.get(uid)
        if event in ("Newchannel", "DialBegin") or (event == "Newstate" and call is None):
            if call is None:
                if event == "Newchannel" and msg.get("ChannelStateDesc") not in ("Ring", "Ringing"):
                    return  # an outgoing leg or a local channel, not a call coming in
                call = self.calls[uid] = LiveCall(uid)
            call.caller_number = call.caller_number or _clean(msg.get("CallerIDNum"))
            call.caller_name = call.caller_name or _clean(msg.get("CallerIDName"))
            if event == "DialBegin":
                call.extension = _clean(msg.get("DestCallerIDNum")) or _clean(msg.get("DialString"))
            else:
                call.extension = call.extension or _clean(msg.get("Exten"))
            self._on_change(call, LIVE_RINGING)
        elif event == "Newstate" and call is not None:
            if (
                msg.get("ChannelStateDesc") == "Up"
                and call.state != LIVE_ANSWERED
                and msg.get("Uniqueid") != uid
            ):
                call.state, call.answered = LIVE_ANSWERED, time.time()
                self._on_change(call, LIVE_ANSWERED)
        elif event == "DialEnd" and call is not None:
            if msg.get("DialStatus") == "ANSWER" and call.state != LIVE_ANSWERED:
                call.state, call.answered = LIVE_ANSWERED, time.time()
                call.extension = _clean(msg.get("DestCallerIDNum")) or call.extension
                self._on_change(call, LIVE_ANSWERED)
        elif event == "Hangup" and call is not None and msg.get("Uniqueid") == uid:
            del self.calls[uid]
            call.state = LIVE_ENDED
            self._on_change(call, LIVE_ENDED)

    def _end_all(self) -> None:
        for uid in list(self.calls):
            call = self.calls.pop(uid)
            call.state = LIVE_ENDED
            self._on_change(call, LIVE_ENDED)

    # ── state for entities ─────────────────────────────────────────────────

    @property
    def ringing(self) -> list[LiveCall]:
        return [c for c in self.calls.values() if c.state == LIVE_RINGING]

    @property
    def active(self) -> list[LiveCall]:
        return [c for c in self.calls.values() if c.state == LIVE_ANSWERED]

    # ── do not disturb (FreePBX keeps it in AstDB: DND/<ext> = YES) ────────

    async def get_dnd(self, extension: str) -> bool:
        reply = await self.action("DBGet", Family="DND", Key=extension)
        return reply.get("Val", reply.get("Value", "")).upper() == "YES"

    async def set_dnd(self, extension: str, on: bool) -> None:
        if on:
            reply = await self.action("DBPut", Family="DND", Key=extension, Val="YES")
        else:
            reply = await self.action("DBDel", Family="DND", Key=extension)
        if reply.get("Response", "").lower() == "error" and on:
            raise ConnectionError(reply.get("Message", "FreePBX refused"))


async def async_test_login(host: str, port: int, username: str, secret: str) -> None:
    """Log in once and out again. Raises OSError/TimeoutError or AmiAuthError."""
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), _TIMEOUT)
    try:
        await asyncio.wait_for(reader.readline(), _TIMEOUT)  # banner
        login = f"Action: Login\r\nUsername: {username}\r\nSecret: {secret}\r\n"
        writer.write((login + "Events: off\r\n\r\n").encode())
        await writer.drain()
        lines: list[str] = []
        while True:
            raw = await asyncio.wait_for(reader.readline(), _TIMEOUT)
            if not raw:
                raise ConnectionError("closed by the Asterisk manager")
            line = raw.decode(errors="replace").strip()
            if not line and lines:
                break
            if line:
                lines.append(line)
        reply = parse_message("\n".join(lines))
        if reply.get("Response", "").lower() != "success":
            raise AmiAuthError(reply.get("Message", "login rejected"))
        writer.write(b"Action: Logoff\r\n\r\n")
        await writer.drain()
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
