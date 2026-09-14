"""Turn calendar rows into events with explicit audience and category labels."""

import collections
import logging
import re
from datetime import datetime, timedelta

from . import categorize

LOG = logging.getLogger(__name__)
Event = collections.namedtuple(
    "Event", "start end title category audience uid sequence modified", defaults=(None, 0, None)
)

_DATE = re.compile(r"^([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})(?:\s+(.*))?$")
_DATE_LIKE = re.compile(r"^(?:[A-Za-z]{3,9}\.?\s+\d{1,2}\s*,|\d{1,4}[-/]\d{1,2}[-/]\d{1,4})")
_MONTHS = {m.lower(): i + 1 for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}
_MONTHS.update({m.lower(): i + 1 for i, m in enumerate(
    "January February March April May June July August September October November December".split())})
_HEADER = re.compile(r"^(?:University[- ]Wide\s+)?Academic Calendar\b", re.I)
_PAGE = re.compile(r"^(?:Page\s+)?\d+\s+of\s+\d+$", re.I)
OTHER_CAMPUSES = categorize.OTHER_CAMPUSES
_CAMPUS_ONLY = categorize.CAMPUS_ONLY


class ParseError(RuntimeError):
    """Source rows cannot be interpreted without losing or guessing data."""


def parse_rows(lines):
    """Join wrapped rows; reject orphan text, empty rows and malformed dates."""
    rows, current_date, parts = [], None, []

    def finish():
        if current_date is not None:
            if not parts:
                raise ParseError("Empty description for {:%Y-%m-%d}".format(current_date))
            title = " ".join(parts)
            if len(title) > 1500:
                raise ParseError("Description exceeds 1500 characters for {:%Y-%m-%d}".format(current_date))
            rows.append((current_date, title))

    for number, raw in enumerate(lines, 1):
        if any(ord(c) < 32 and c not in "\t\r\n" for c in raw) or "\ufffd" in raw:
            raise ParseError("Invalid text at line {}".format(number))
        line = " ".join(raw.split())
        if (not line or line.lower() in ("date", "event", "date event")
                or _HEADER.match(line) or _PAGE.fullmatch(line)):
            continue
        match = _DATE.fullmatch(line)
        if match:
            finish()
            try:
                current_date = datetime(int(match[3]), _MONTHS[match[1].lower()], int(match[2]))
            except (KeyError, ValueError) as exc:
                raise ParseError("Invalid date at line {}: {!r}".format(number, line)) from exc
            parts = [match[4]] if match[4] else []
        elif _DATE_LIKE.match(line):
            raise ParseError("Unrecognized date at line {}: {!r}".format(number, line))
        elif current_date is None:
            raise ParseError("Text before the first date at line {}: {!r}".format(number, line))
        else:
            parts.append(line)
    finish()
    if not rows:
        raise ParseError("No dated rows found")
    return rows


def audience(text):
    return categorize.audience(text, _CAMPUS_ONLY, bool(OTHER_CAMPUSES))


def exclusion_reason(text):
    """Compatibility helper: non-undergraduate audience, or None."""
    key = audience(text)
    return None if key == "undergrad" else key


_SPANS = (
    (r"^First day of (fall|winter|spring|summer) break\b(.*)$",
     r"^(fall|winter|spring|summer) classes resume\b(.*)$", "{} Break", False),
    (r"^First day of (fall|winter|spring|summer) final exam period\b(.*)$",
     r"^Last day of (fall|winter|spring|summer) final exam period\b(.*)$",
     "{} Final Exam Period", True),
)


def _context(suffix):
    # The source uses "for full term" only on the opening summer exam row.
    return re.sub(r"\s+", " ", re.sub(
        r"\(if applicable\)|\bfor full term\b", "", suffix, flags=re.I)).strip().casefold()


def collapse_spans(events):
    """Merge unambiguous pairs, preserving population, scope and inclusive dates."""
    used, spans = set(), []
    for open_re, close_re, title_fmt, inclusive in _SPANS:
        openings, closings = collections.defaultdict(list), collections.defaultdict(list)
        for index, (date, text) in enumerate(events):
            plain = categorize.without_prefix(text)
            for regex, groups in ((open_re, openings), (close_re, closings)):
                match = re.match(regex, plain, re.I)
                if match:
                    key = (audience(text), match[1].lower(), _context(match[2]))
                    groups[key].append((index, date, text, match[2]))
        for key in sorted(openings.keys() | closings.keys()):
            left, right = openings.get(key, []), closings.get(key, [])
            if len(left) > 1 or len(right) > 1:
                raise ParseError("Ambiguous span markers for {} {}".format(key[0], key[1]))
            if not left or not right:
                marker = (left or right)[0]
                log = LOG.info if key[0] == "law" else LOG.warning
                log("Unpaired span marker date=%s title=%r", marker[1].date(), marker[2])
                continue
            i, start, text, suffix = left[0]
            j, end, _, _ = right[0]
            last = end if inclusive else end - timedelta(days=1)
            if last < start or (last - start).days > 62:
                raise ParseError("Invalid span dates {} to {} for {!r}".format(start.date(), last.date(), text))
            # Preserve scope in the title, including QTR and campus qualifiers.
            prefix = categorize._AUD_PREFIX.match(text)
            title = title_fmt.format(key[1].capitalize())
            if key[2]:
                title += " " + re.sub(r"\(if applicable\)", "", suffix, flags=re.I).strip()
            if prefix:
                title = prefix[0] + title
            spans.append((start, last, title))
            used.update((i, j))
    singles = [(date, text) for i, (date, text) in enumerate(events) if i not in used]
    return singles, sorted(spans, key=lambda event: (event[0], event[2]))


def build(lines):
    rows = parse_rows(lines)
    by_audience = collections.OrderedDict()
    seen = set()
    duplicates = 0
    for date, text in rows:
        try:
            categorize.validate_scope(text)
        except ValueError as exc:
            raise ParseError(str(exc)) from exc
        if (date, text) in seen:
            duplicates += 1
            LOG.warning("Duplicate source row date=%s title=%r", date.date(), text)
            continue
        seen.add((date, text))
        by_audience.setdefault(audience(text), []).append((date, text))

    events, collapsed = [], 0
    for aud, items in by_audience.items():
        singles, spans = collapse_spans(items)
        collapsed += len(spans)
        for date, title in singles:
            events.append(Event(date, date, title, categorize.categorize(title)[0], aud))
        for start, end, title in spans:
            events.append(Event(start, end, title, categorize.categorize(title)[0], aud))
    events.sort(key=lambda event: (event.start, event.title, event.audience))
    audiences = collections.Counter(event.audience for event in events)
    categories = collections.Counter(event.category for event in events if event.audience == "undergrad")
    stats = {"parsed": len(rows), "kept": len(events), "duplicates": duplicates,
             "collapsed": collapsed, "audiences": dict(sorted(audiences.items())),
             "categories": dict(sorted(categories.items()))}
    LOG.info("Parsed rows=%d events=%d collapsed=%d duplicates=%d",
             len(rows), len(events), collapsed, duplicates)
    return events, stats
