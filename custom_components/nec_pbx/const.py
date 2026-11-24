"""Constants for the NEC PBX integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "nec_pbx"

CONF_EXTENSIONS: Final = "extensions"
CONF_PHONEBOOK: Final = "phonebook"
# A Home Assistant to-do list used as a phonebook: each item is a name with a number.
CONF_PHONEBOOK_TODO: Final = "phonebook_todo"
SERVICE_SAVE_CALLER: Final = "save_caller"
CONF_DATE_ORDER: Final = "date_order"
CONF_LINES: Final = "lines"  # "001: Main line" - trunk numbers to names
# Optional FreePBX / Asterisk manager connection for live ringing.
CONF_AMI_HOST: Final = "ami_host"
CONF_AMI_PORT: Final = "ami_port"
CONF_AMI_USER: Final = "ami_user"
CONF_AMI_SECRET: Final = "ami_secret"
CONF_DND_EXTENSIONS: Final = "dnd_extensions"  # FreePBX extensions with a DND switch

DEFAULT_PORT: Final = 4001
DEFAULT_NAME: Final = "NEC SL2100"

EVENT_CALL: Final = "nec_pbx_call"
EVENT_MISSED_CALL: Final = "nec_pbx_missed_call"

SIGNAL_UPDATE: Final = "nec_pbx_update_{}"
SIGNAL_CALL: Final = "nec_pbx_new_call_{}"
SIGNAL_LIVE: Final = "nec_pbx_live_{}"  # live call change from FreePBX
EVENT_RINGING: Final = "nec_pbx_ringing"  # a phone started ringing (FreePBX)
EVENT_LIVE: Final = "nec_pbx_live_call"  # ringing / answered / ended (FreePBX)
HISTORY_CALLS: Final = 500  # calls kept for the call history calendar
# A call seen for the first time (not a replay): daily totals count these.
SIGNAL_NEW_RECORD: Final = "nec_pbx_new_record_{}"

# Lines already counted are remembered (and saved) so the phone system's replay
# on reconnect, or after a restart, is never counted twice. More than the call
# history holds, so a replay of every stored call can't create duplicates.
SEEN_LINES: Final = HISTORY_CALLS + 100
STORAGE_VERSION: Final = 1

RECENT_CALLS: Final = 20

# The phone system replays its stored call log on connect. Only calls that ended
# within this window fire events, so a reconnect never re-announces old calls.
LIVE_WINDOW: Final = timedelta(minutes=15)

# Raise a Repairs issue when the call log has been unreachable this long.
OUTAGE_ISSUE_AFTER: Final = timedelta(minutes=10)
ISSUE_UNREACHABLE: Final = "call_log_unreachable_{}"
