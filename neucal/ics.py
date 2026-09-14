"""Render and verify the all-day RFC 5545 subset this project publishes."""

import collections
import hashlib
import logging
import re
from datetime import date, datetime, time, timedelta, timezone

from . import categorize
from .parse import Event

LOG = logging.getLogger(__name__)
PRODID = "-//neu-academic-calendar-ics//Northeastern Academic Calendar//EN"


def _esc(value):
    if not isinstance(value, str) or any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise ValueError("Calendar text must be a string without control characters")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return (value.replace("\\", "\\\\").replace(";", r"\;")
            .replace(",", r"\,").replace("\n", r"\n"))


def _unesc(value):
    return re.sub(r"\\([nN,;\\])", lambda m: "\n" if m[1].lower() == "n" else m[1], value)


def _fold(line):
    raw = line.encode("utf-8")
    out = []
    while len(raw) > 75:
        cut = 75
        while (raw[cut] & 0xC0) == 0x80:
            cut -= 1
        out.append(raw[:cut].decode("utf-8"))
        raw = b" " + raw[cut:]
    return out + [raw.decode("utf-8")]


def _uid(start, title, namespace):
    # Keep the original scheme so unchanged published events retain their UID.
    digest = hashlib.sha1("{:%Y%m%d}|{}".format(start, title).encode()).hexdigest()
    return "{}@{}".format(digest[:16], namespace)


def _day(value):
    if not isinstance(value, date):
        raise ValueError("All-day event dates must be date or datetime values")
    if isinstance(value, datetime) and (value.time() != time() or value.tzinfo is not None):
        raise ValueError("All-day datetimes must be naive midnight; use a date for local days")
    return datetime(value.year, value.month, value.day)


def _utc(value):
    if not isinstance(value, datetime):
        raise ValueError("Timestamps must be datetime values")
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def render(events, name, description, namespace, stamp=None):
    """Render all-day events; naive timestamps are interpreted as UTC."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", namespace):
        raise ValueError("Invalid UID namespace")
    stamp = _utc(stamp if stamp is not None else datetime.now(timezone.utc))
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:" + PRODID,
        "CALSCALE:GREGORIAN",
        "NAME:" + _esc(name),
        "DESCRIPTION:" + _esc(description),
        "X-WR-CALNAME;VALUE=TEXT:" + _esc(name),
        "X-WR-CALDESC;VALUE=TEXT:" + _esc(description),
        "REFRESH-INTERVAL;VALUE=DURATION:P1D",
        "X-PUBLISHED-TTL:P1D",
    ]
    seen = set()
    for event in events:
        start, end, title = event[:3]
        start, end = _day(start), _day(end)
        if end < start or end.date() == date.max:
            raise ValueError("Invalid inclusive date range for {!r}".format(title))
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Events require a nonempty title")
        uid = getattr(event, "uid", None) or _uid(start, title, namespace)
        if not re.fullmatch(r"[A-Za-z0-9._@-]{1,255}", uid):
            raise ValueError("Invalid event UID")
        if uid in seen:
            raise ValueError("Duplicate event UID {} for {!r}".format(uid, title))
        seen.add(uid)
        cat_key = event[3] if len(event) > 3 else None
        audience = event[4] if len(event) > 4 else None
        modified = _utc(getattr(event, "modified", None) or stamp)
        sequence = getattr(event, "sequence", 0)
        if not isinstance(sequence, int) or not 0 <= sequence <= 2_147_483_647:
            raise ValueError("Invalid event sequence")
        lines.extend([
            "BEGIN:VEVENT", "UID:" + uid,
            "DTSTAMP:{:%Y%m%dT%H%M%SZ}".format(modified),
            "LAST-MODIFIED:{:%Y%m%dT%H%M%SZ}".format(modified),
            "SEQUENCE:{}".format(sequence),
            "DTSTART;VALUE=DATE:{:%Y%m%d}".format(start),
            "DTEND;VALUE=DATE:{:%Y%m%d}".format(end + timedelta(days=1)),
            "SUMMARY:" + _esc(title), "TRANSP:TRANSPARENT",
        ])
        if cat_key:
            lines.append("CATEGORIES:" + categorize.ics_value(cat_key))
        if audience:
            if audience not in categorize.audience_keys():
                raise ValueError("Unknown audience {!r}".format(audience))
            lines.append("X-NEUCAL-AUDIENCE:" + audience)
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(part for line in lines for part in _fold(line)) + "\r\n"


def unfold(text):
    """Unfold on CRLF only, so Unicode line separators remain part of text."""
    return re.sub(r"\r\n[ \t]", "", text).split("\r\n")


def without_stamp(text):
    return "\r\n".join(line for line in unfold(text) if not line.startswith("DTSTAMP:"))


def read(text):
    """Validate and read our generated feeds, including the legacy format.

    This intentionally accepts only the calendar subset we emit, not arbitrary
    imported iCalendar files. It also supplies the previous event IDs for rebuilds.
    """
    if not text.endswith("\r\n") or re.search(r"(?<!\r)\n|\r(?!\n)", text):
        raise ValueError("Calendar must use CRLF line endings")
    if any(len(line.encode("utf-8")) > 75 for line in text.split("\r\n")):
        raise ValueError("Calendar line exceeds 75 octets")
    if any(ord(c) < 32 and c not in "\r\n\t" for c in text):
        raise ValueError("Calendar contains control characters")
    lines = unfold(text)
    if lines[0] != "BEGIN:VCALENDAR" or lines[-2:] != ["END:VCALENDAR", ""]:
        raise ValueError("Invalid calendar boundaries")
    events, props, calendar_props = [], None, {}
    seen = set()
    by_value = {categorize.ics_value(key): key for key in categorize.keys()}
    for line in lines[1:-2]:
        if line == "BEGIN:VEVENT":
            if props is not None:
                raise ValueError("Nested VEVENT")
            props = {}
        elif line == "END:VEVENT":
            if props is None:
                raise ValueError("Unexpected END:VEVENT")
            required = ("UID", "DTSTAMP", "DTSTART;VALUE=DATE", "DTEND;VALUE=DATE", "SUMMARY")
            if any(key not in props for key in required):
                raise ValueError("Event is missing required properties")
            for key in ("DTSTART;VALUE=DATE", "DTEND;VALUE=DATE"):
                if not re.fullmatch(r"\d{8}", props[key]):
                    raise ValueError("Invalid DATE value for " + key)
            for key in ("DTSTAMP", "LAST-MODIFIED"):
                if key in props and not re.fullmatch(r"\d{8}T\d{6}Z", props[key]):
                    raise ValueError("Invalid UTC timestamp for " + key)
            uid = props["UID"]
            if not re.fullmatch(r"[A-Za-z0-9._@-]{1,255}", uid) or uid in seen:
                raise ValueError("Invalid or duplicate UID: " + uid)
            seen.add(uid)
            start = datetime.strptime(props["DTSTART;VALUE=DATE"], "%Y%m%d")
            exclusive_end = datetime.strptime(props["DTEND;VALUE=DATE"], "%Y%m%d")
            end = exclusive_end - timedelta(days=1)
            if end < start:
                raise ValueError("DTEND must follow DTSTART")
            title = _unesc(props["SUMMARY"])
            if not title.strip():
                raise ValueError("Empty event summary")
            stamp = datetime.strptime(props["DTSTAMP"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            modified = datetime.strptime(props.get("LAST-MODIFIED", props["DTSTAMP"]),
                                         "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            if stamp != modified and "LAST-MODIFIED" in props:
                raise ValueError("DTSTAMP and LAST-MODIFIED disagree")
            sequence = int(props.get("SEQUENCE", 0))
            if not 0 <= sequence <= 2_147_483_647:
                raise ValueError("Invalid sequence number")
            category = by_value.get(props.get("CATEGORIES"))
            if "CATEGORIES" in props and category is None:
                raise ValueError("Unrecognized ICS category")
            aud = props.get("X-NEUCAL-AUDIENCE", categorize.audience(title))
            if aud not in categorize.audience_keys():
                raise ValueError("Unrecognized event audience")
            events.append(Event(start, end, title, category, aud, uid, sequence, modified))
            props = None
        else:
            key, sep, value = line.partition(":")
            if not sep or key in ("BEGIN", "END"):
                raise ValueError("Invalid content line: {!r}".format(line))
            target = calendar_props if props is None else props
            if key in target:
                raise ValueError("Duplicate property: " + key)
            target[key] = value
    if props is not None or calendar_props.get("VERSION") != "2.0" or not calendar_props.get("PRODID"):
        raise ValueError("Incomplete calendar")
    return events


def reconcile(events, previous, namespace, stamp):
    """Preserve IDs and revision times, including unambiguous date corrections.

    The PDF provides no event identifiers. Match date/title first, then a title
    that occurs exactly once in both versions. Changed titles get new IDs.
    """
    stamp = _utc(stamp)
    old_by_exact = {(event.start, event.title): event for event in previous}
    old_by_title = collections.defaultdict(list)
    new_titles = collections.Counter(event.title for event in events)
    for event in previous:
        old_by_title[event.title].append(event)
    reconciled, matched, changed = [], set(), 0
    for event in events:
        old = old_by_exact.get((event.start, event.title))
        if old is None and len(old_by_title[event.title]) == 1 and new_titles[event.title] == 1:
            old = old_by_title[event.title][0]
        if old is None or old.uid in matched:
            reconciled.append(event._replace(uid=_uid(event.start, event.title, namespace), modified=stamp))
            continue
        matched.add(old.uid)
        same = event[:5] == old[:5]
        if not same:
            changed += 1
        reconciled.append(event._replace(
            uid=old.uid, sequence=old.sequence + (not same),
            modified=old.modified if same else max(stamp, old.modified)))
    LOG.info("Reconciled events retained=%d changed=%d added=%d removed=%d",
             len(matched), changed, len(events) - len(matched), len(previous) - len(matched))
    return reconciled
