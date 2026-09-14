#!/usr/bin/env python3
"""Rebuild the published calendars from whatever the registrar has today.

Writes one .ics per academic year plus a stable `current.ics` that always points
at the newest year, so a subscriber never has to re-subscribe when the registrar
posts a new calendar.
"""

import argparse
import datetime as dt
import pathlib
import sys

from neucal import discover, ics, parse, pdf

DOCS = pathlib.Path(__file__).parent / "docs"
NAMESPACE = "neu-academic-calendar-ics"

# A correct calendar has ~120 undergraduate rows across three terms. These
# bounds exist so a registrar format change fails the build instead of silently
# publishing an empty or truncated calendar to subscribers.
MIN_EVENTS = 90
MAX_EVENTS = 400


class SanityError(RuntimeError):
    pass


def _without_stamp(text):
    return "\n".join(l for l in text.splitlines() if not l.startswith("DTSTAMP:"))


def write_if_changed(path, text):
    """Write only on a real change.

    DTSTAMP is regenerated every run, so a naive write would make the weekly
    job commit an identical calendar forever. Compare everything else.
    """
    if path.exists():
        old = path.read_bytes().decode("utf-8")
        if _without_stamp(old) == _without_stamp(text):
            return False
    path.write_bytes(text.encode("utf-8"))
    return True


def check(events, year):
    start_year = int(year.split("-")[0])
    if not MIN_EVENTS <= len(events) <= MAX_EVENTS:
        raise SanityError(
            "{}: got {} events, expected {}-{}. The PDF layout likely changed."
            .format(year, len(events), MIN_EVENTS, MAX_EVENTS))

    months = {d.strftime("%b") for d, _, _ in events}
    for term, needed in (("fall", "Sep"), ("spring", "Jan"), ("summer", "Jun")):
        if needed not in months:
            raise SanityError(
                "{}: no {} events found (missing {}) — parse is incomplete."
                .format(year, term, needed))

    lo = dt.datetime(start_year, 7, 1)
    hi = dt.datetime(start_year + 2, 1, 1)
    stray = [(d, t) for d, _, t in events if not lo <= d < hi]
    if stray:
        raise SanityError("{}: {} event(s) outside the academic year, e.g. {}"
                          .format(year, len(stray), stray[0]))


def build_year(year, url, stamp):
    raw = discover.fetch(url)
    events, stats = parse.build(pdf.to_lines(raw))
    check(events, year)

    text = ics.render(
        events,
        name="NEU Undergrad {}".format(year),
        description=("Northeastern University-Wide Academic Calendar {} "
                     "(Boston undergraduate). Source: {}".format(year, url)),
        namespace=NAMESPACE,
        stamp=stamp,
    )
    return events, stats, text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-latest", action="store_true",
                    help="build just the newest year (faster; CI builds all)")
    args = ap.parse_args()

    stamp = dt.datetime.utcnow()
    found = discover.discover()
    print("discovered {} calendar(s): {}".format(len(found), ", ".join(found)))

    newest = discover.latest(found)
    years = [newest] if args.only_latest else list(found)

    DOCS.mkdir(exist_ok=True)
    built, failures = {}, {}
    for year in years:
        try:
            events, stats, text = build_year(year, found[year], stamp)
        except Exception as exc:
            failures[year] = exc
            print("  {}  FAILED: {}".format(year, exc), file=sys.stderr)
            continue
        changed = write_if_changed(DOCS / "neu-undergrad-{}.ics".format(year), text)
        built[year] = (events, stats)
        print("  {}  {} events (from {} rows, dropped {}){}".format(
            year, stats["kept"], stats["parsed"], stats["dropped"],
            "" if changed else "  [unchanged]"))

    # The newest year must always build — it is what `current.ics` serves.
    if newest in failures:
        raise SystemExit("FATAL: newest year {} failed to build: {}"
                         .format(newest, failures[newest]))

    current = (DOCS / "neu-undergrad-{}.ics".format(newest)).read_bytes().decode("utf-8")
    write_if_changed(DOCS / "current.ics", current)
    print("current.ics -> {}".format(newest))

    write_index(sorted(built), newest)
    return 0


def write_index(years, newest):
    from html import escape
    rows = "\n".join(
        '      <li><a href="neu-undergrad-{y}.ics">{y}</a>{tag}</li>'.format(
            y=escape(y), tag=" <em>(current)</em>" if y == newest else "")
        for y in reversed(years))
    html = INDEX_HTML.format(rows=rows, newest=escape(newest),
                             updated=dt.datetime.utcnow().strftime("%Y-%m-%d"))
    path = DOCS / "index.html"
    old = path.read_text() if path.exists() else ""
    import re as _re
    strip = lambda h: _re.sub(r"Rebuilt \d{4}-\d{2}-\d{2}", "", h)
    if strip(old) != strip(html):
        path.write_text(html)


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Northeastern Undergraduate Academic Calendar &rarr; iCalendar</title>
<style>
  body {{ font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         max-width: 44rem; margin: 3rem auto; padding: 0 1.25rem; color: #1a1a1a; }}
  code {{ background: #f4f4f5; padding: .15em .4em; border-radius: 4px;
          font-size: .9em; word-break: break-all; }}
  .feed {{ background: #f4f4f5; padding: 1rem; border-radius: 8px; }}
  footer {{ margin-top: 3rem; font-size: .85em; color: #666; }}
</style>
</head>
<body>
<h1>Northeastern academic calendar, as an iCalendar feed</h1>
<p>Northeastern publishes its academic calendar only as a PDF. This rebuilds it
   weekly as an <code>.ics</code> feed, filtered to <strong>Boston-campus
   undergraduate</strong> events.</p>

<h2>Subscribe</h2>
<div class="feed"><code id="u"></code></div>
<p>In Google Calendar: <strong>Other calendars &rarr; + &rarr; From URL</strong>,
   paste that, and subscribe. It always serves the newest academic year
   (currently <strong>{newest}</strong>), so you never re-subscribe.</p>
<p><em>Subscribed feeds are read-only and Google refreshes them on its own
   schedule &mdash; often up to 24 hours. If you want the events editable, or
   want them immediately, download a file below and import it instead.</em></p>

<h2>Download a specific year</h2>
<ul>
{rows}
</ul>

<footer>
  <p>Rebuilt {updated}. Source:
     <a href="https://registrar.northeastern.edu/article/academic-calendar/">NEU
     Office of the University Registrar</a>. Dates are subject to change and this
     is an unofficial mirror &mdash; verify anything that matters against the
     registrar.</p>
</footer>
<script>document.getElementById('u').textContent =
  location.href.replace(/(index\\.html)?(#.*)?$/, '') + 'current.ics';</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
