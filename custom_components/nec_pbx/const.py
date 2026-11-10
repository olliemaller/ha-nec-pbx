"""Constants for the NEC PBX integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "nec_pbx"

CONF_EXTENSIONS: Final = "extensions"
CONF_PHONEBOOK: Final = "phonebook"

DEFAULT_PORT: Final = 4001
DEFAULT_NAME: Final = "NEC SL2100"

EVENT_CALL: Final = "nec_pbx_call"
EVENT_MISSED_CALL: Final = "nec_pbx_missed_call"

SIGNAL_UPDATE: Final = "nec_pbx_update_{}"

RECENT_CALLS: Final = 20

# Reconnect back-off (seconds).
RECONNECT_MIN: Final = 5
RECONNECT_MAX: Final = 300
CONNECT_TIMEOUT: Final = 10
