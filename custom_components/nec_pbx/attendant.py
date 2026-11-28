"""Optional AI attendant add-on: talks to a separately run nec-ai-attendant engine.

The engine answers calls itself and fires ``nec_ai_attendant_call`` on the Home
Assistant event bus on its own. This module only reads its HTTP API (status, new
messages, the last call and response times), changes its answering setting and
listens to its event websocket so the entities update the moment a call starts.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
import json
import logging
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ATTENDANT_POLL,
    ATTENDANT_POLL_WITH_EVENTS,
    ATTENDANT_RETRY_MAX,
    ATTENDANT_RETRY_MIN,
    ATTENDANT_STATS_DAYS,
    ATTENDANT_TIMEOUT,
    DOMAIN,
    ISSUE_ATTENDANT_AUTH,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


class AttendantError(Exception):
    """The engine couldn't be reached or answered with an error."""


class AttendantAuthError(AttendantError):
    """The engine rejected the API token."""


def normalise_url(url: str) -> str:
    """ " http://10.0.0.5:8099/ " -> "http://10.0.0.5:8099"."""
    return url.strip().rstrip("/")


def valid_url(url: str) -> bool:
    """Only http:// and https:// addresses with a host."""
    for scheme in ("http://", "https://"):
        if url.startswith(scheme) and len(url) > len(scheme):
            return True
    return False


class AttendantApi:
    """A small client for the engine's HTTP API (bearer token, JSON)."""

    def __init__(self, session: aiohttp.ClientSession, url: str, token: str) -> None:
        self.session = session
        self.url = normalise_url(url)
        self._token = token

    @property
    def headers(self) -> dict[str, str]:
        """The bearer token, if the engine has one set."""
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    @property
    def events_url(self) -> str:
        """The websocket address for live events."""
        if self.url.startswith("https://"):
            return "wss://" + self.url[len("https://") :] + "/api/events"
        return "ws://" + self.url[len("http://") :] + "/api/events"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        try:
            async with (
                asyncio.timeout(ATTENDANT_TIMEOUT),
                self.session.request(
                    method, f"{self.url}{path}", headers=self.headers, params=params, json=body
                ) as resp,
            ):
                if resp.status in (401, 403):
                    raise AttendantAuthError(f"HTTP {resp.status}")
                if resp.status >= 400:
                    raise AttendantError(f"HTTP {resp.status} from {path}")
                text = await resp.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise AttendantError(str(err) or type(err).__name__) from err
        if not text.strip():
            return None
        try:
            return json.loads(text)
        except ValueError as err:
            raise AttendantError(f"{path} didn't answer with JSON") from err

    async def status(self) -> dict[str, Any]:
        """GET /api/status."""
        data = await self._request("GET", "/api/status")
        if not isinstance(data, dict):
            raise AttendantError("/api/status didn't answer like an AI attendant engine")
        return data

    async def messages(self, status: str = "new") -> list[dict[str, Any]]:
        """GET /api/messages?status=new|done|all."""
        data = await self._request("GET", "/api/messages", params={"status": status})
        return [m for m in data if isinstance(m, dict)] if isinstance(data, list) else []

    async def calls(self, limit: int = 1) -> list[dict[str, Any]]:
        """GET /api/calls?limit=N, newest first."""
        data = await self._request("GET", "/api/calls", params={"limit": str(limit)})
        return [c for c in data if isinstance(c, dict)] if isinstance(data, list) else []

    async def stats(self, days: int) -> dict[str, Any]:
        """GET /api/stats?days=N."""
        data = await self._request("GET", "/api/stats", params={"days": str(days)})
        return data if isinstance(data, dict) else {}

    async def set_settings(self, **settings: Any) -> None:
        """PUT /api/settings with only the keys given."""
        await self._request("PUT", "/api/settings", body=settings)

    async def set_message_status(self, message_id: str, status: str) -> None:
        """POST /api/messages/{id} {"status": "done"|"new"}."""
        await self._request("POST", f"/api/messages/{message_id}", body={"status": status})


@dataclass
class AttendantData:
    """What the engine last told us."""

    status: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)  # new ones, newest first
    last_call: dict[str, Any] | None = None
    stats: dict[str, Any] = field(default_factory=dict)


class AttendantCoordinator(DataUpdateCoordinator[AttendantData]):
    """Polls the engine every 30 seconds, or every 5 minutes while its events arrive."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: AttendantApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{entry.title} AI attendant",
            update_interval=ATTENDANT_POLL,
        )
        self.api = api
        self.events_connected = False
        self.last_error: str | None = None
        self._issue_id = ISSUE_ATTENDANT_AUTH.format(entry.entry_id)

    async def _async_update_data(self) -> AttendantData:
        try:
            status, messages, calls, stats = await asyncio.gather(
                self.api.status(),
                self.api.messages("new"),
                self.api.calls(1),
                self.api.stats(ATTENDANT_STATS_DAYS),
            )
        except AttendantAuthError as err:
            self.last_error = "token rejected"
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="attendant_auth",
                translation_placeholders={"name": self.config_entry.title, "url": self.api.url},
            )
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="attendant_auth_failed"
            ) from err
        except AttendantError as err:
            self.last_error = str(err)
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="attendant_unreachable",
                translation_placeholders={"error": str(err)},
            ) from err
        self.last_error = None
        ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)
        messages.sort(key=lambda m: str(m.get("created_at") or ""), reverse=True)
        return AttendantData(
            status=status,
            messages=messages,
            last_call=calls[0] if calls else None,
            stats=stats,
        )

    def delete_issue(self) -> None:
        """Clear the token Repairs issue (on unload)."""
        ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)

    async def async_set_answering(self, enabled: bool) -> None:
        """Turn answering of outside calls on or off."""
        try:
            await self.api.set_settings(answering_outside=enabled)
        except AttendantError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="attendant_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        if self.data is not None:
            status = {**self.data.status, "answering_outside": enabled}
            self.async_set_updated_data(replace(self.data, status=status))

    async def async_mark_message(self, message_id: str, status: str = "done") -> None:
        """Mark a message done (or new again) and refresh the list."""
        try:
            await self.api.set_message_status(message_id, status)
        except AttendantError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="attendant_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        if self.data is not None and status == "done":
            messages = [m for m in self.data.messages if str(m.get("id")) != message_id]
            self.async_set_updated_data(replace(self.data, messages=messages))
        await self.async_request_refresh()

    def handle_event(self, event: dict[str, Any]) -> None:
        """One event from the websocket: update now, then fetch the details."""
        kind = event.get("type")
        if kind not in ("call_started", "call_ended", "message"):
            return  # "turn" comes with every line of every call; nothing shown changes
        if self.data is not None:
            data = self.data
            if kind == "message":
                message = event.get("data")
                if isinstance(message, dict) and message.get("status", "new") == "new":
                    others = [m for m in data.messages if m.get("id") != message.get("id")]
                    data = replace(data, messages=[message, *others])
            else:
                active = int(data.status.get("active_calls") or 0)
                active = active + 1 if kind == "call_started" else max(active - 1, 0)
                data = replace(data, status={**data.status, "active_calls": active})
            self.async_set_updated_data(data)
        # The engine has the full picture (outcome, timings); fetch it.
        self.hass.async_create_task(self.async_request_refresh())

    async def async_listen(self) -> None:
        """Keep the event websocket open, reconnecting with backoff (5 s doubling to 5 min).

        Polling carries on underneath; while events arrive it slows to every 5 minutes."""
        delay = ATTENDANT_RETRY_MIN
        while True:
            try:
                async with self.api.session.ws_connect(
                    self.api.events_url, headers=self.api.headers, heartbeat=30
                ) as ws:
                    delay = ATTENDANT_RETRY_MIN
                    self.events_connected = True
                    self.update_interval = ATTENDANT_POLL_WITH_EVENTS
                    _LOGGER.debug("AI attendant events connected")
                    # Catch up on anything that happened while disconnected.
                    await self.async_request_refresh()
                    async for msg in ws:
                        if msg.type is not aiohttp.WSMsgType.TEXT:
                            continue
                        try:
                            event = json.loads(msg.data)
                        except ValueError:
                            _LOGGER.debug("Ignored an AI attendant event that isn't JSON")
                            continue
                        if isinstance(event, dict):
                            self.handle_event(event)
            except aiohttp.WSServerHandshakeError as err:
                _LOGGER.debug("AI attendant events refused (HTTP %s)", err.status)
            except (aiohttp.ClientError, TimeoutError) as err:
                _LOGGER.debug("AI attendant events unavailable: %s", err)
            if self.events_connected:
                _LOGGER.debug("AI attendant events disconnected; polling every 30 seconds")
                self.events_connected = False
                self.update_interval = ATTENDANT_POLL
            await asyncio.sleep(delay)
            delay = min(delay * 2, ATTENDANT_RETRY_MAX)
