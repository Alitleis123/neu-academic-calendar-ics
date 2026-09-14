"""Render events as an RFC 5545 iCalendar file."""

import hashlib
from datetime import datetime, timedelta

PRODID = "-//neu-academic-calendar-ics//Northeastern Undergraduate Calendar//EN"


def _esc(s):
    return (s.replace("\\", "\\\\").replace(";", r"\;")
             .replace(",", r"\,").replace("\n", r"\n"))


def _fold(line):
    """RFC 5545 caps content lines at 75 octets; continuations start with a space."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return [line]
    out, cur = [], raw
    while len(cur) > 75:
        cut = 75
        while cut > 0 and (cur[cut] & 0xC0) == 0x80:   # don't split a UTF-8 sequence
            cut -= 1
        out.append(cur[:cut].decode("utf-8"))
        cur = b" " + cur[cut:]
    out.append(cur.decode("utf-8"))
    return out


def _uid(start, title, namespace):
    digest = hashlib.sha1("{:%Y%m%d}|{}".format(start, title).encode()).hexdigest()
    return "{}@{}".format(digest[:16], namespace)


def render(events, name, description, namespace, stamp=None):
    """events: iterable of (start, end_inclusive, title[, category_key])."""
    from . import categorize
    stamp = stamp or datetime.utcnow()
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:" + PRODID,
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:" + name,
        "X-WR-CALDESC:" + description,
        "REFRESH-INTERVAL;VALUE=DURATION:P1D",
        "X-PUBLISHED-TTL:P1D",
    ]
    for event in events:
        start, end, title = event[:3]
        cat_key = event[3] if len(event) > 3 else None
        lines += [
            "BEGIN:VEVENT",
            "UID:" + _uid(start, title, namespace),
            "DTSTAMP:{:%Y%m%dT%H%M%SZ}".format(stamp),
            "DTSTART;VALUE=DATE:{:%Y%m%d}".format(start),
            # DTEND is exclusive for all-day events
            "DTEND;VALUE=DATE:{:%Y%m%d}".format(end + timedelta(days=1)),
            "SUMMARY:" + _esc(title),
            "TRANSP:TRANSPARENT",
        ]
        if cat_key:
            lines.append("CATEGORIES:" + categorize.categorize(title)[1])
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")

    folded = []
    for line in lines:
        folded.extend(_fold(line))
    return "\r\n".join(folded) + "\r\n"
