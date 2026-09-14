"""Turn extracted calendar lines into filtered, undergraduate-scoped events."""

import re
from datetime import datetime, timedelta

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


def exclusion_reason(text):
    """Why this university-wide row is not a Boston undergraduate event, or None."""
    if "School of Law" in text or re.search(r"\b(JD|Law)\b", text):
        return "law"
    if "ABSN" in text or "College of Professional Studies" in text:
        return "other-program"
    if text.startswith("CAN:"):
        return "canada-campus"
    if _CAMPUS_ONLY.search(text) and "Boston" not in text:
        return "other-campus"
    if text.startswith("Faculty grade deadline"):
        return "faculty"
    # \b keeps this from matching inside "undergraduate"
    if re.search(r"\bgraduate\b", text) and not re.search(r"\bundergraduate\b", text):
        return "grad-only"
    return None


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
    """lines -> (all_day_events, stats). Each event is (start, end_inclusive, title)."""
    rows = parse_rows(lines)
    dropped = {}
    kept = []
    for date, text in rows:
        reason = exclusion_reason(text)
        if reason:
            dropped[reason] = dropped.get(reason, 0) + 1
        else:
            kept.append((date, text))

    singles, spans = collapse_spans(kept)
    events = [(d, d, t) for d, t in singles] + spans
    events.sort(key=lambda e: (e[0], e[2]))
    return events, {"parsed": len(rows), "kept": len(events), "dropped": dropped}
