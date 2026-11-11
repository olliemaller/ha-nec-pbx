"""Parser for NEC SL2100 / SV9100 SMDR (Station Message Detail Recording) lines.

The SL2100 prints one fixed-width text line per finished call (Programming
Manual, Program 35-02, Table 2-11). The exact columns move about with the
35-01 / 35-02 options (name or number, date on or off, overseas or North
American format), so this parser works on tokens rather than character
offsets. It never raises: anything it cannot read comes back as ``None`` and
the raw line is always kept, so a new layout can be checked in the
diagnostics and added to the tests.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
import re
from typing import Any

DIRECTION_INCOMING = "incoming"
DIRECTION_OUTGOING = "outgoing"
DIRECTION_INTERNAL = "internal"
DIRECTION_UNKNOWN = "unknown"

# Class codes seen in NEC SMDR output (first column).
_CLASS_DIRECTIONS: dict[str, str] = {
    "IC": DIRECTION_INCOMING,
    "IN": DIRECTION_INCOMING,
    "INC": DIRECTION_INCOMING,
    "DID": DIRECTION_INCOMING,
    "DIL": DIRECTION_INCOMING,
    "CLI": DIRECTION_INCOMING,
    "OG": DIRECTION_OUTGOING,
    "OUT": DIRECTION_OUTGOING,
    "TR": DIRECTION_OUTGOING,
    "TRF": DIRECTION_OUTGOING,
    "IT": DIRECTION_INTERNAL,
    "ICM": DIRECTION_INTERNAL,
}

_MISSED_FLAGS = ("NO ANSWER", "NOANSWER", "ABANDON", "UNANSWERED", "LOST")

_HEADER_WORDS = ("CLSS", "STATION", "DURATION", "DIALLED", "DIALED")
_SUMMARY_WORDS = ("TOTAL", "SUMMARY", "DAILY", "WEEKLY", "MONTHLY", "PAGE")

_RE_DURATION = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2}):(\d{2})(?![\d:])")
_RE_TIME = re.compile(r"(?<![\d:/])([01]?\d|2[0-3]):([0-5]\d)(?![\d:])")
_RE_DATE = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?![\d/])")
_RE_RING = re.compile(r"(?<![\d:])(\d{1,3}):([0-5]\d)(?![\d:])")
_RE_COST = re.compile(r"\$\s?[\d,]+(?:\.\d+)?")
# External numbers: 6+ digits, possibly ending in X where digits were hidden.
_RE_NUMBER = re.compile(r"(?<![\w:/])\+?\d[\d*#]{4,}[\dX]*(?![\w:/])")
_RE_SHORT = re.compile(r"(?<![\w:/$,.])(\d{2,5})(?![\w:/,.])")


@dataclass(slots=True)
class SmdrRecord:
    """One call, as read from a single SMDR line."""

    raw: str
    direction: str = DIRECTION_UNKNOWN
    call_class: str | None = None
    start: datetime | None = None
    duration: int | None = None
    ring_time: int | None = None
    trunk: str | None = None
    station: str | None = None
    station_name: str | None = None
    number: str | None = None
    caller_name: str | None = None
    cost: str | None = None
    answered: bool = True
    flags: list[str] = field(default_factory=list)

    @property
    def missed(self) -> bool:
        """An incoming call that nobody answered."""
        return self.direction == DIRECTION_INCOMING and not self.answered

    @property
    def ended(self) -> datetime | None:
        """When the call ended: start plus ring and talk time."""
        if self.start is None:
            return None
        return self.start + timedelta(seconds=(self.ring_time or 0) + (self.duration or 0))

    def is_live(self, now: datetime, window: timedelta) -> bool:
        """True for a call that just finished, not one replayed from the phone system's store."""
        ended = self.ended
        return ended is None or now - ended <= window

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe dict for events and attributes."""
        data = asdict(self)
        data["start"] = self.start.isoformat() if self.start else None
        data["missed"] = self.missed
        return data


def is_record_line(line: str) -> bool:
    """True for a line that looks like a call record, not a header or blank."""
    text = line.strip()
    if len(text) < 8:
        return False
    upper = text.upper()
    if any(word in upper for word in _HEADER_WORDS):
        return False
    if any(upper.startswith(word) for word in _SUMMARY_WORDS):
        return False
    if set(text) <= set("-=_* "):
        return False
    # A call record always carries a clock time or a duration.
    return bool(_RE_DURATION.search(text) or _RE_TIME.search(text))


def _seconds(h: str | int, m: str | int, s: str | int = 0) -> int:
    return int(h) * 3600 + int(m) * 60 + int(s)


def parse_line(
    line: str,
    *,
    extensions: dict[str, str] | None = None,
    phonebook: dict[str, str] | None = None,
    now: datetime | None = None,
) -> SmdrRecord | None:
    """Parse one SMDR line. Returns None for headers, summaries and blanks."""
    raw = line.rstrip("\r\n")
    if not is_record_line(raw):
        return None

    extensions = extensions or {}
    phonebook = phonebook or {}
    now = now or datetime.now()
    rec = SmdrRecord(raw=raw)
    work = raw

    upper = work.upper()
    for flag in _MISSED_FLAGS:
        if flag in upper:
            rec.flags.append(flag.replace(" ", "_").lower())
            rec.answered = False
            work = re.sub(re.escape(flag), " ", work, flags=re.IGNORECASE)

    cost = _RE_COST.search(work)
    if cost:
        rec.cost = cost.group(0).replace(" ", "")
        work = work[: cost.start()] + " " + work[cost.end() :]

    # Duration (H:MM:SS) comes before any ring time (M:SS).
    dur = _RE_DURATION.search(work)
    if dur:
        rec.duration = _seconds(*dur.groups())
        work = work[: dur.start()] + " " + work[dur.end() :]

    # Class code: first alphabetic token in the first two tokens.
    tokens = work.split()
    for tok in tokens[:2]:
        if tok.upper() in _CLASS_DIRECTIONS:
            rec.call_class = tok.upper()
            rec.direction = _CLASS_DIRECTIONS[rec.call_class]
            break

    # Clock time and optional date.
    tm = _RE_TIME.search(work)
    call_time: time | None = None
    if tm:
        call_time = time(int(tm.group(1)), int(tm.group(2)))
        work = work[: tm.start()] + " " + work[tm.end() :]
    dt = _RE_DATE.search(work)
    call_date: date | None = None
    if dt:
        day, month = int(dt.group(1)), int(dt.group(2))
        year = now.year
        if dt.group(3):
            year = int(dt.group(3))
            if year < 100:
                year += 2000
        if 1 <= month <= 12 and 1 <= day <= 31:
            try:
                call_date = date(year, month, day)
            except ValueError:
                call_date = None
            else:
                work = work[: dt.start()] + " " + work[dt.end() :]
    if call_time is not None:
        when = datetime.combine(call_date or now.date(), call_time, tzinfo=now.tzinfo)
        if call_date is None and when > now + timedelta(minutes=5):
            when -= timedelta(days=1)  # call started before midnight
        if call_date is not None and dt and not dt.group(3) and when > now + timedelta(days=1):
            when = when.replace(year=when.year - 1)  # record from last year
        rec.start = when

    # Ring time (M:SS), usually after the number on incoming calls.
    ring = _RE_RING.search(work)
    if ring:
        rec.ring_time = _seconds(0, ring.group(1), ring.group(2))
        work = work[: ring.start()] + " " + work[ring.end() :]

    # External number: the longest long digit string.
    numbers = sorted(_RE_NUMBER.findall(work), key=len, reverse=True)
    if numbers:
        rec.number = numbers[0]
        work = work.replace(numbers[0], " ", 1)

    # Station: a known extension number or name wins; otherwise the first
    # short number that is not the trunk.
    short = _RE_SHORT.findall(work)
    for ext, name in extensions.items():
        if ext in short:
            rec.station, rec.station_name = ext, name
            short.remove(ext)
            break
        if name and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", work, re.IGNORECASE):
            rec.station, rec.station_name = ext, name
            break
    trunks = [s for s in short if len(s) == 3 and s.startswith("0")]
    if trunks:
        rec.trunk = trunks[0]
        short.remove(trunks[0])
    # Sequence numbers (1-2 digits) and zero-padded counters are never
    # extensions.
    short = [s for s in short if len(s) >= 3 and not s.startswith("0")]
    if rec.station is None and short:
        rec.station = short[0]
        rec.station_name = extensions.get(rec.station)

    # Direction fallback when there is no class code.
    if rec.direction == DIRECTION_UNKNOWN:
        if rec.ring_time is not None or not rec.answered:
            rec.direction = DIRECTION_INCOMING
        elif rec.number:
            rec.direction = DIRECTION_OUTGOING
        elif rec.station:
            rec.direction = DIRECTION_INTERNAL

    if rec.number:
        rec.caller_name = lookup_name(rec.number, phonebook)

    return rec


def normalise_number(number: str) -> str:
    """Digits only, with +61 turned into a leading 0."""
    digits = re.sub(r"[^\d]", "", number)
    if number.strip().startswith("+61") or (digits.startswith("61") and len(digits) == 11):
        digits = "0" + digits[2:]
    return digits


def lookup_name(number: str, phonebook: dict[str, str]) -> str | None:
    """Find a name for a number. Masked numbers (ending in X) match on the prefix."""
    if not number:
        return None
    target = normalise_number(number.rstrip("Xx"))
    masked = number.upper().endswith("X")
    for book_number, name in phonebook.items():
        candidate = normalise_number(book_number)
        if candidate == target or (masked and target and candidate.startswith(target)):
            return name
    return None


def parse_mapping(text: str) -> dict[str, str]:
    """Parse 'key: value' or 'key=value' lines (or comma separated) into a dict."""
    result: dict[str, str] = {}
    for part in re.split(r"[\n,;]+", text or ""):
        if not part.strip():
            continue
        key, sep, value = _split_pair(part)
        if sep and key:
            result[key.replace(" ", "")] = value.strip()
    return result


def _split_pair(part: str) -> tuple[str, str, str]:
    match = re.match(r"\s*([^:=]+?)\s*([:=])\s*(.*)$", part)
    if not match:
        return "", "", ""
    return match.group(1), match.group(2), match.group(3)


def format_mapping(mapping: dict[str, str]) -> str:
    """Inverse of parse_mapping, one pair per line."""
    return "\n".join(f"{key}: {value}" for key, value in mapping.items())
