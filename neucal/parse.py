"""Turn extracted calendar lines into labelled events.

Nothing is discarded here. Every row gets an audience and a category, and
build.py decides which slices to publish.
"""

import collections
import re
from datetime import datetime, timedelta

from . import categorize

Event = collections.namedtuple("Event", "start end title category audience")

_DATE = re.compile(r"^([A-Z][a-z]{2}) (\d{1,2}), (\d{4})$")
_MONTHS = {m: i + 1 for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}
_NOISE = ("University-Wide", "Academic Calendar")

# Campuses other than the one we build for. Rows scoped to these are dropped.
OTHER_CAMPUSES = ("Vancouver", "Charlotte", "Oakland and Silicon Valley",
                  "Toronto", "Miami", "Seattle", "Arlington", "Burlington")

_CAMPUS_ONLY = re.compile(
    r"\((?:[^)]*\b(?:{})\b[^)]*)only\)".format("|".join(OTHER_CAMPUSES)), re.I)


def parse_rows(lines):
    """Group lines into (date, description) pairs.

    A date line opens a record; every following non-date line is part of that
    record's description (the PDF wraps descriptions across several lines).
    """
    rows, cur = [], None
    for line in lines:
        line = line.strip()
        if not line or line in ("Date", "Event") or any(n in line for n in _NOISE):
            continue
        m = _DATE.match(line)
        if m:
            if cur:
                rows.append(cur)
            cur = [datetime(int(m.group(3)), _MONTHS[m.group(1)], int(m.group(2))), []]
        elif cur:
            cur[1].append(line)
    if cur:
        rows.append(cur)
    return [(d, " ".join(parts)) for d, parts in rows]


def audience(text):
    """Which population this university-wide row applies to."""
    return categorize.audience(text, _CAMPUS_ONLY, bool(OTHER_CAMPUSES))


def exclusion_reason(text):
    """Deprecated: the audience a row belongs to, or None if Boston undergraduate.

    Kept because "is this an undergraduate row" reads better than an equality
    check at several call sites.
    """
    key = audience(text)
    return None if key == "undergrad" else key


# (opening row, closing row, title, whether the closing row is itself in the span)
_SPANS = (
    (r"^First day of (fall|spring|summer) break",
     r"^(fall|spring|summer) classes resume", "{} Break", False),
    (r"^First day of (fall|spring|summer) final exam period",
     r"^Last day of (fall|spring|summer) final exam period",
     "{} Final Exam Period", True),
)


def collapse_spans(events):
    """Replace first-day/last-day row pairs with single multi-day events.

    Derived from the row text rather than hardcoded dates, so it keeps working
    for future academic years.
    """
    used, spans = set(), []
    for open_re, close_re, title_fmt, inclusive in _SPANS:
        for i, (start, text) in enumerate(events):
            mo = re.match(open_re, text, re.I)
            if not mo or i in used:
                continue
            term = mo.group(1).lower()
            for j in range(i + 1, len(events)):
                end, other = events[j]
                mc = re.match(close_re, other, re.I)
                if j not in used and mc and mc.group(1).lower() == term:
                    spans.append((start, end if inclusive else end - timedelta(days=1),
                                  title_fmt.format(term.capitalize())))
                    used.update({i, j})
                    break
    singles = [(d, t) for i, (d, t) in enumerate(events) if i not in used]
    return singles, spans


def build(lines):
    """lines -> (events, stats). Each event is an Event namedtuple."""
    rows = parse_rows(lines)

    # Collapse spans per audience: a "first day of fall break" row and its
    # "fall classes resume" partner always belong to the same population, and
    # collapsing across audiences could pair unrelated rows.
    by_audience = collections.OrderedDict()
    for date, text in rows:
        by_audience.setdefault(audience(text), []).append((date, text))

    events = []
    for aud, items in by_audience.items():
        singles, spans = collapse_spans(items)
        for d, t in singles:
            events.append(Event(d, d, t, categorize.categorize(t)[0], aud))
        for a, b, t in spans:
            events.append(Event(a, b, t, categorize.categorize(t)[0], aud))
    events.sort(key=lambda e: (e.start, e.title))

    audiences = collections.Counter(e.audience for e in events)
    categories = collections.Counter(
        e.category for e in events if e.audience == "undergrad")
    return events, {"parsed": len(rows), "kept": len(events),
                    "audiences": dict(audiences), "categories": dict(categories)}
