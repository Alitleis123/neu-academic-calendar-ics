"""Find the academic-calendar PDFs the registrar currently publishes.

The registrar does not offer a feed or an index API, so we scrape the two pages
that link to calendar PDFs. URLs have followed the pattern
``<YYYY>-<YYYY>-Academic-Calendar.pdf`` since the 2022-2023 year; anything older
used ad-hoc names and is out of scope.
"""

import re
import urllib.parse
import urllib.request

INDEX_PAGES = (
    "https://registrar.northeastern.edu/article/academic-calendar/",
    "https://registrar.northeastern.edu/article/past-calendars/",
)

# The current-year page links the PDF relatively; the past-calendars page links
# it absolutely. Match either and resolve against the page URL.
PDF_RE = re.compile(
    r'(?:https://registrar\.northeastern\.edu)?'
    r'/wp-content/uploads/sites/9/(\d{4})-(\d{4})-Academic-Calendar\.pdf',
    re.I,
)

# Calendars before this year use a different PDF layout this parser does not read.
EARLIEST_SUPPORTED = "2025-2026"

USER_AGENT = "neu-academic-calendar-ics (+https://github.com/Alitleis123)"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def discover():
    """Return {"2026-2027": url, ...} for every calendar PDF we can find."""
    found = {}
    errors = []
    for page in INDEX_PAGES:
        try:
            html = fetch(page).decode("utf-8", "replace")
        except Exception as exc:                      # a dead index page is not fatal
            errors.append("{}: {}".format(page, exc))
            continue
        for m in PDF_RE.finditer(html):
            year = "{}-{}".format(m.group(1), m.group(2))
            if year >= EARLIEST_SUPPORTED:
                found[year] = urllib.parse.urljoin(page, m.group(0))

    if not found:
        raise RuntimeError(
            "No calendar PDFs found on the registrar site. The page layout or URL "
            "pattern probably changed. Errors: " + ("; ".join(errors) or "none")
        )
    return dict(sorted(found.items()))


def latest(found):
    """The most recent academic year in a discover() result."""
    return max(found)
