"""Constants for the NEC PBX integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "nec_pbx"

CONF_EXTENSIONS: Final = "extensions"
CONF_PHONEBOOK: Final = "phonebook"
CONF_DATE_ORDER: Final = "date_order"

DEFAULT_PORT: Final = 4001
DEFAULT_NAME: Final = "NEC SL2100"

EVENT_CALL: Final = "nec_pbx_call"
EVENT_MISSED_CALL: Final = "nec_pbx_missed_call"

SIGNAL_UPDATE: Final = "nec_pbx_update_{}"
SIGNAL_CALL: Final = "nec_pbx_new_call_{}"
# A call seen for the first time (not a replay): daily totals count these.
SIGNAL_NEW_RECORD: Final = "nec_pbx_new_record_{}"

# Lines already counted are remembered (and saved) so the phone system's replay
# on reconnect, or after a restart, is never counted twice.
SEEN_LINES: Final = 400
STORAGE_VERSION: Final = 1

RECENT_CALLS: Final = 20

# The phone system replays its stored call log on connect. Only calls that ended
# within this window fire events, so a reconnect never re-announces old calls.
LIVE_WINDOW: Final = timedelta(minutes=15)

# Raise a Repairs issue when the call log has been unreachable this long.
OUTAGE_ISSUE_AFTER: Final = timedelta(minutes=10)
ISSUE_UNREACHABLE: Final = "call_log_unreachable_{}"

# Reconnect back-off (seconds).
RECONNECT_MIN: Final = 5
RECONNECT_MAX: Final = 300
CONNECT_TIMEOUT: Final = 10

# TCP keepalive on the SMDR socket: notice a dead link within about 90 s.
KEEPALIVE_IDLE: Final = 60
KEEPALIVE_INTERVAL: Final = 10
KEEPALIVE_COUNT: Final = 3
