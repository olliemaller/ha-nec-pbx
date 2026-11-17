"""Tests for the SMDR line parser."""

from datetime import datetime

import pytest

from custom_components.nec_pbx.smdr import (
    DIRECTION_INCOMING,
    DIRECTION_INTERNAL,
    DIRECTION_OUTGOING,
    format_mapping,
    is_record_line,
    lookup_name,
    normalise_number,
    parse_line,
    parse_mapping,
)

NOW = datetime(2026, 11, 10, 18, 30)
EXTS = {"101": "Rumpus", "103": "Oliver", "104": "Family", "106": "Jordan"}
BOOK = {"0491570156": "Alex", "0491570157": "Sam"}


@pytest.mark.parametrize(
    "line",
    [
        "",
        "   ",
        "CLSS  TIME   LINE   DURATION  STATION  DIALLED No./CLI   RD.COST  ACCOUNT",
        "-------------------------------------------------------------",
        "TOTAL   12 CALLS",
        "short",
    ],
)
def test_headers_and_noise_are_skipped(line: str) -> None:
    assert not is_record_line(line)
    assert parse_line(line, now=NOW) is None


def test_outgoing_table_2_11_layout() -> None:
    line = "OG 0001  18:12  001   00:02:35  103   0491570156            $0,000"
    rec = parse_line(line, extensions=EXTS, phonebook=BOOK, now=NOW)
    assert rec is not None
    assert rec.direction == DIRECTION_OUTGOING
    assert rec.call_class == "OG"
    assert rec.start == datetime(2026, 11, 10, 18, 12)
    assert rec.duration == 155
    assert rec.trunk == "001"
    assert rec.station == "103"
    assert rec.station_name == "Oliver"
    assert rec.number == "0491570156"
    assert rec.caller_name == "Alex"
    assert rec.cost == "$0,000"
    assert rec.answered
    assert not rec.missed


def test_incoming_answered_with_ring_time() -> None:
    line = "IC 0002  17:55  001   00:00:41  104   0491570157   0:12"
    rec = parse_line(line, extensions=EXTS, phonebook=BOOK, now=NOW)
    assert rec is not None
    assert rec.direction == DIRECTION_INCOMING
    assert rec.station == "104"
    assert rec.station_name == "Family"
    assert rec.duration == 41
    assert rec.ring_time == 12
    assert rec.caller_name == "Sam"
    assert not rec.missed


def test_incoming_no_answer_is_missed() -> None:
    # Overseas layout as printed by SL1000/SL1100 loggers, names on.
    line = "29 NAME  08:29 22/04 017                      226xxxxx         0:19    NO ANSWER"
    rec = parse_line(line, now=NOW)
    assert rec is not None
    assert rec.direction == DIRECTION_INCOMING
    assert not rec.answered
    assert rec.missed
    assert rec.flags == ["no_answer"]
    assert rec.ring_time == 19
    assert rec.start == datetime(2026, 4, 22, 8, 29)


def test_date_column_and_masked_number() -> None:
    line = "28 PIN   08:28 22/04 003  00:00:04 5500       2261234X         0:25"
    rec = parse_line(line, now=NOW)
    assert rec is not None
    assert rec.start == datetime(2026, 4, 22, 8, 28)
    assert rec.duration == 4
    assert rec.trunk == "003"
    assert rec.station == "5500"
    assert rec.number == "2261234X"


def test_time_after_now_without_date_is_yesterday() -> None:
    line = "OG 0003  23:58  001   00:01:00  101   0399998888"
    rec = parse_line(line, extensions=EXTS, now=datetime(2026, 11, 10, 0, 5))
    assert rec is not None
    assert rec.start == datetime(2026, 11, 9, 23, 58)


def test_internal_call_without_number() -> None:
    line = "IT 0004  12:00        00:00:30  101   103"
    rec = parse_line(line, extensions=EXTS, now=NOW)
    assert rec is not None
    assert rec.direction == DIRECTION_INTERNAL
    assert rec.station == "101"


def test_station_found_by_name() -> None:
    line = "IC 0005  10:00  001   00:01:10  Jordan   0491570156"
    rec = parse_line(line, extensions=EXTS, phonebook=BOOK, now=NOW)
    assert rec is not None
    assert rec.station == "106"
    assert rec.station_name == "Jordan"


def test_never_raises_on_garbage() -> None:
    for line in ["12:00 ????", "99:99:99 x", "00:00:01", "\x00\x01 12:30 abc"]:
        parse_line(line, now=NOW)


def test_as_dict_is_json_safe() -> None:
    rec = parse_line("OG 0001  18:12  001   00:02:35  103   0491570156", now=NOW)
    assert rec is not None
    data = rec.as_dict()
    assert data["start"] == "2026-11-10T18:12:00"
    assert data["missed"] is False


def test_numbers_and_names() -> None:
    assert normalise_number("+61 491 570 156") == "0491570156"
    assert normalise_number("61491570156") == "0491570156"
    assert lookup_name("0491570156", BOOK) == "Alex"
    assert lookup_name("049157015X", BOOK) == "Alex"
    assert lookup_name("0400000000", BOOK) is None
    assert lookup_name("", BOOK) is None


def test_mapping_round_trip() -> None:
    text = "101: Rumpus\n103 = Oliver\n0491 570 156: Alex, 105: Spare Room"
    mapping = parse_mapping(text)
    assert mapping == {
        "101": "Rumpus",
        "103": "Oliver",
        "0491570156": "Alex",
        "105": "Spare Room",
    }
    assert parse_mapping(format_mapping(mapping)) == mapping
    assert parse_mapping("no colon here") == {}


def test_timezone_aware_now() -> None:
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Australia/Melbourne")
    now = datetime(2026, 11, 10, 18, 30, tzinfo=tz)
    rec = parse_line("OG 0001  18:12  001   00:02:35  103   0491570156", now=now)
    assert rec is not None
    assert rec.start == datetime(2026, 11, 10, 18, 12, tzinfo=tz)
    rec = parse_line("29 NAME  08:29 22/04 017   226xxxxx  0:19  NO ANSWER", now=now)
    assert rec is not None
    assert rec.start.tzinfo is tz


def test_is_live() -> None:
    from datetime import datetime, timedelta

    from custom_components.nec_pbx.smdr import SmdrRecord

    now = datetime(2026, 11, 11, 18, 30)
    window = timedelta(minutes=15)
    just_now = SmdrRecord(raw="", start=now - timedelta(minutes=3), duration=60, ring_time=5)
    stored = SmdrRecord(raw="", start=now - timedelta(hours=19), duration=15)
    assert just_now.is_live(now, window)
    assert not stored.is_live(now, window)
    assert SmdrRecord(raw="").is_live(now, window)


def _sv9100(t, tm, d, ln, du, st, num, acc=""):
    """Fixed columns as printed by an SV9100 (see the ADFDiesel nec-smdr project)."""
    return f"{t:<4} {tm:<5} {d:<5} {ln:<4} {du:<8} {st:<10} {num:<20} {acc:<16}"


@pytest.mark.parametrize(
    ("kind", "direction"),
    [
        ("PIN", DIRECTION_INCOMING),
        ("IVIN", DIRECTION_INCOMING),
        ("PTRS", DIRECTION_INCOMING),
        ("POT", DIRECTION_OUTGOING),
        ("POTA", DIRECTION_OUTGOING),
    ],
)
def test_sv9100_call_types(kind: str, direction: str) -> None:
    now = datetime(2026, 11, 17, 15, 0)
    rec = parse_line(
        _sv9100(kind, "14:32", "11/17", "001", "00:03:12", "103", "0491570156"),
        extensions=EXTS,
        now=now,
    )
    assert rec is not None
    assert rec.call_class == kind
    assert rec.direction == direction
    assert rec.start == datetime(2026, 11, 17, 14, 32)
    assert rec.duration == 192
    assert rec.trunk == "001"
    assert rec.station == "103"
    assert rec.number == "0491570156"
    assert ("transferred" in rec.flags) == (kind == "PTRS")


def test_ambiguous_date_picks_the_reading_that_is_not_in_the_future() -> None:
    from custom_components.nec_pbx.smdr import DATE_DMY, DATE_MDY

    now = datetime(2026, 11, 17, 15, 0)
    line = _sv9100("PIN", "09:00", "11/05", "001", "00:01:00", "103", "0491570156")
    # 11/05 could be 11 May or 5 November: auto takes the latest date not in the future.
    assert parse_line(line, now=now).start == datetime(2026, 11, 5, 9, 0)
    assert parse_line(line, now=now, date_order=DATE_DMY).start == datetime(2026, 5, 11, 9, 0)
    assert parse_line(line, now=now, date_order=DATE_MDY).start == datetime(2026, 11, 5, 9, 0)
    # Australian order on New Year's Day: 31/12 is last year.
    ny = datetime(2027, 1, 1, 0, 10)
    line = _sv9100("POT", "23:58", "31/12", "001", "00:01:00", "103", "0491570156")
    assert parse_line(line, now=ny).start == datetime(2026, 12, 31, 23, 58)


def test_keepalive_is_enabled() -> None:
    import socket
    from unittest.mock import MagicMock

    from custom_components.nec_pbx.client import _enable_keepalive

    sock = MagicMock()
    writer = MagicMock()
    writer.get_extra_info.return_value = sock
    _enable_keepalive(writer)
    sock.setsockopt.assert_any_call(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
