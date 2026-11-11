"""Constants for the NEC PBX integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "nec_pbx"

CONF_EXTENSIONS: Final = "extensions"
CONF_PHONEBOOK: Final = "phonebook"

DEFAULT_PORT: Final = 4001
DEFAULT_NAME: Final = "NEC SL2100"

EVENT_CALL: Final = "nec_pbx_call"
EVENT_MISSED_CALL: Final = "nec_pbx_missed_call"

SIGNAL_UPDATE: Final = "nec_pbx_update_{}"
SIGNAL_CALL: Final = "nec_pbx_new_call_{}"

RECENT_CALLS: Final = 20

# The phone system replays its stored call log on connect. Only calls that ended
# within this window fire events, so a reconnect never re-announces old calls.
LIVE_WINDOW: Final = timedelta(minutes=15)

# Reconnect back-off (seconds).
RECONNECT_MIN: Final = 5
RECONNECT_MAX: Final = 300
CONNECT_TIMEOUT: Final = 10
