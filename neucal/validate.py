"""Checks that stop incomplete calendars from replacing published feeds."""

import collections
import logging
import re
from datetime import datetime

from . import categorize
from .discover import year_start

LOG = logging.getLogger(__name__)
MIN_EVENTS = 90
MAX_EVENTS = 400
REQUIRED_CATEGORIES = {
    "attendance": 12, "deadlines": 9, "classes": 6, "exams": 3,
    "holidays": 3, "registration": 1, "schedules": 1, "conferral": 1,
}


class SanityError(RuntimeError):
    """Calendar data failed a publication guardrail."""


def check(events, year, *, previous=(), accept_count_change=False):
    start_year = year_start(year)
    categorize.validate_config()
    if not MIN_EVENTS <= len(events) <= MAX_EVENTS:
        raise SanityError("{}: got {} events, expected {}-{}".format(
            year, len(events), MIN_EVENTS, MAX_EVENTS))
    # Registration starts before fall. Summer Law grade deadlines extend into
    # September of the following year, so an August cutoff would lose them.
    lo, hi = datetime(start_year, 7, 1), datetime(start_year + 1, 10, 1)
    seen = set()
    for event in events:
        if event.category not in categorize.keys():
            raise SanityError("{}: uncategorized event {!r}; update categorize.py".format(year, event.title))
        if event.audience not in categorize.audience_keys():
            raise SanityError("{}: unknown audience {!r}".format(year, event.audience))
        if not event.title.strip() or len(event.title) > 1500:
            raise SanityError("{}: invalid event title {!r}".format(year, event.title))
        if not lo <= event.start <= event.end < hi or (event.end - event.start).days > 62:
            raise SanityError("{}: invalid date range {} to {} for {!r}".format(
                year, event.start, event.end, event.title))
        identity = (event.start, event.title)
        if identity in seen:
            raise SanityError("{}: duplicate date/title identity {!r}".format(year, identity))
        seen.add(identity)
    undergrad = [event for event in events if event.audience == "undergrad"]
    if not MIN_EVENTS <= len(undergrad) <= 250:
        raise SanityError("{}: got {} undergraduate events, expected 90-250".format(year, len(undergrad)))
    counts = collections.Counter(event.category for event in undergrad)
    for category, minimum in REQUIRED_CATEGORIES.items():
        if counts[category] < minimum:
            raise SanityError("{}: too few undergraduate {} events: {} < {}".format(
                year, category, counts[category], minimum))
    for term in ("fall", "spring", "summer"):
        term_events = [event for event in undergrad if re.search(r"\b" + term + r"\b", event.title, re.I)]
        for category in ("attendance", "deadlines", "classes", "exams"):
            if not any(event.category == category for event in term_events):
                raise SanityError("{}: missing undergraduate {} {}".format(year, term, category))
        if not any(event.title == term.capitalize() + " Final Exam Period" for event in term_events):
            raise SanityError("{}: missing paired undergraduate {} final exam period".format(year, term))
    for term in ("Fall", "Spring"):
        if not any(event.title == term + " Break" for event in undergrad):
            raise SanityError("{}: missing paired undergraduate {} break".format(year, term))

    if previous:
        old_counts = collections.Counter((event.audience, event.category) for event in previous)
        new_counts = collections.Counter((event.audience, event.category) for event in events)
        drops = ["all events {} -> {}".format(len(previous), len(events))] if len(events) < len(previous) * .8 else []
        for key, old_count in sorted(old_counts.items()):
            new_count = new_counts[key]
            if old_count >= 4 and new_count < old_count * .75 and old_count - new_count >= 3:
                drops.append("{}/{} {} -> {}".format(*key, old_count, new_count))
        if drops:
            message = "{}: large count reduction: {}".format(year, "; ".join(drops))
            if not accept_count_change:
                raise SanityError(message + ". Review the PDF, then use --accept-count-change if intentional")
            LOG.warning("Accepted %s", message)
    LOG.info("Validated year=%s total=%d undergraduate=%d categories=%s",
             year, len(events), len(undergrad), dict(sorted(counts.items())))
