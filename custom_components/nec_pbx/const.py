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
# A to-do list that gets a "Call back ..." item for every missed call.
CONF_MISSED_TODO: Final = "missed_todo"
# Optional AI attendant add-on: a separately run nec-ai-attendant engine's HTTP API.
CONF_ATTENDANT_URL: Final = "attendant_url"
CONF_ATTENDANT_TOKEN: Final = "attendant_token"

DEFAULT_PORT: Final = 4001
DEFAULT_NAME: Final = "NEC SL2100"

EVENT_CALL: Final = "nec_pbx_call"
EVENT_MISSED_CALL: Final = "nec_pbx_missed_call"

SIGNAL_UPDATE: Final = "nec_pbx_update_{}"
SIGNAL_CALL: Final = "nec_pbx_new_call_{}"
SIGNAL_LIVE: Final = "nec_pbx_live_{}"  # live call change from FreePBX
SIGNAL_DND: Final = "nec_pbx_dnd_{}"  # FreePBX said do-not-disturb changed: (extension, on)
# Once FreePBX has pushed a do-not-disturb change, the switches only poll this often.
DND_FALLBACK_POLL: Final = timedelta(minutes=5)
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

# AI attendant add-on.
SERVICE_ATTENDANT_MARK_DONE: Final = "attendant_mark_message_done"
SERVICE_ATTENDANT_SET_ANSWERING: Final = "attendant_set_answering"
# Polled this often; once the engine's event websocket is connected, only this often.
ATTENDANT_POLL: Final = timedelta(seconds=30)
ATTENDANT_POLL_WITH_EVENTS: Final = timedelta(minutes=5)
# Websocket reconnect backoff: first retry after this, doubling up to the maximum.
ATTENDANT_RETRY_MIN: Final = 5.0
ATTENDANT_RETRY_MAX: Final = 300.0
ATTENDANT_TIMEOUT: Final = 10.0  # seconds per HTTP request
ATTENDANT_STATS_DAYS: Final = 7  # the average response time covers this many days
ATTENDANT_MESSAGES_SHOWN: Final = 10  # latest new messages kept as an attribute
ISSUE_ATTENDANT_AUTH: Final = "attendant_auth_{}"
