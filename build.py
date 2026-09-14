#!/usr/bin/env python3
"""Rebuild the published calendars from whatever the registrar has today.

Writes, per academic year: one full .ics, one per category, and an "essentials"
bundle. Each also gets a `current-*` alias pointing at the newest year, so a
subscriber never has to re-subscribe when the registrar posts a new calendar.
"""

import argparse
import datetime as dt
import pathlib
import sys

from neucal import categorize, discover, ics, parse

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
    if path.exists() and _without_stamp(path.read_bytes().decode()) == _without_stamp(text):
        return False
    path.write_bytes(text.encode("utf-8"))
    return True


def check(events, year):
    start_year = int(year.split("-")[0])
    if not MIN_EVENTS <= len(events) <= MAX_EVENTS:
        raise SanityError(
            "{}: got {} events, expected {}-{}. The PDF layout likely changed."
            .format(year, len(events), MIN_EVENTS, MAX_EVENTS))

    months = {e[0].strftime("%b") for e in events}
    for term, needed in (("fall", "Sep"), ("spring", "Jan"), ("summer", "Jun")):
        if needed not in months:
            raise SanityError("{}: no {} events found (missing {}) — parse is incomplete."
                              .format(year, term, needed))

    lo, hi = dt.datetime(start_year, 7, 1), dt.datetime(start_year + 2, 1, 1)
    stray = [(e[0], e[2]) for e in events if not lo <= e[0] < hi]
    if stray:
        raise SanityError("{}: {} event(s) outside the academic year, e.g. {}"
                          .format(year, len(stray), stray[0]))

    uncategorized = [e[2] for e in events if e[3] == "other"]
    if uncategorized:
        raise SanityError("{}: {} uncategorized event(s), e.g. {!r}. Add a rule to "
                          "neucal/categorize.py.".format(year, len(uncategorized),
                                                         uncategorized[0]))


# (filename suffix, calendar-name suffix, predicate over category key)
def _variants():
    yield "", "", lambda k: True
    yield "-essentials", " essentials", lambda k: k in categorize.ESSENTIALS
    for key in categorize.keys():
        yield "-" + key, " " + categorize.label(key), (lambda k, want=key: k == want)


def emit(events, year, url, stamp, prefix):
    """Write every variant for one year. Returns {suffix: count}."""
    written = {}
    for suffix, name_suffix, keep in _variants():
        subset = [e for e in events if keep(e[3])]
        if not subset:
            continue
        text = ics.render(
            subset,
            name="NEU Undergrad {}{}".format(year, name_suffix),
            description=("Northeastern University-Wide Academic Calendar {} "
                         "(Boston undergraduate{}). Source: {}"
                         .format(year, name_suffix or "", url)),
            namespace=NAMESPACE,
            stamp=stamp,
        )
        write_if_changed(DOCS / "{}{}.ics".format(prefix, suffix), text)
        written[suffix or "(all)"] = len(subset)
    return written


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
            raw = discover.fetch(found[year])
            from neucal import pdf
            events, stats = parse.build(pdf.to_lines(raw))
            check(events, year)
        except Exception as exc:
            failures[year] = exc
            print("  {}  FAILED: {}".format(year, exc), file=sys.stderr)
            continue
        emit(events, year, found[year], stamp, "neu-undergrad-" + year)
        built[year] = (events, stats)
        print("  {}  {} events  {}".format(year, stats["kept"], stats["categories"]))

    # The newest year must always build — it is what the `current-*` feeds serve.
    if newest in failures:
        raise SystemExit("FATAL: newest year {} failed to build: {}"
                         .format(newest, failures[newest]))

    events, _ = built[newest]
    written = emit(events, newest, found[newest], stamp, "current")
    print("current* -> {}  ({} feeds)".format(newest, len(written)))

    write_index(sorted(built), newest, built[newest][1]["categories"])
    return 0


def write_index(years, newest, counts):
    from html import escape
    feeds = [("current.ics", "Everything", sum(counts.values()),
              "Every undergraduate event.")]
    feeds.append(("current-essentials.ics", "Essentials", 
                  sum(counts.get(k, 0) for k in categorize.ESSENTIALS),
                  "Deadlines, exams, holidays. Recommended."))
    for key in categorize.keys():
        if counts.get(key):
            feeds.append(("current-{}.ics".format(key), categorize.label(key),
                          counts[key], categorize.blurb(key)))

    rows = "\n".join(
        '  <tr><td><strong>{label}</strong><br><small>{blurb}</small></td>'
        '<td class="n">{n}</td><td><code class="f">{f}</code></td></tr>'.format(
            label=escape(l), blurb=escape(b), n=n, f=escape(f))
        for f, l, n, b in feeds)

    archive = "\n".join(
        '    <li><a href="neu-undergrad-{y}.ics">{y}</a>{tag}</li>'.format(
            y=escape(y), tag=" <em>(current)</em>" if y == newest else "")
        for y in reversed(years))

    html = INDEX_HTML.format(rows=rows, archive=archive, newest=escape(newest),
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
         max-width: 52rem; margin: 3rem auto; padding: 0 1.25rem; color: #1a1a1a; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1.5rem 0; }}
  td, th {{ text-align: left; padding: .6rem .5rem; border-bottom: 1px solid #e5e5e5;
            vertical-align: top; }}
  td.n {{ text-align: right; color: #666; white-space: nowrap; }}
  small {{ color: #666; }}
  code {{ background: #f4f4f5; padding: .15em .4em; border-radius: 4px;
          font-size: .82em; word-break: break-all; }}
  footer {{ margin-top: 3rem; font-size: .85em; color: #666; }}
</style>
</head>
<body>
<h1>Northeastern academic calendar, as iCalendar feeds</h1>
<p>Northeastern publishes its academic calendar only as a PDF. This rebuilds it
   weekly as <code>.ics</code> feeds, filtered to <strong>Boston-campus
   undergraduate</strong> events and split by category so you can subscribe to
   only what you want.</p>

<h2>Pick a feed</h2>
<table>
  <tr><th>Feed</th><th class="n">Events</th><th>URL</th></tr>
{rows}
</table>

<p>In Google Calendar: <strong>Other calendars &rarr; + &rarr; From URL</strong>,
   paste one, subscribe. Subscribe to several and colour them separately.</p>
<p>Every feed tracks the newest academic year automatically (currently
   <strong>{newest}</strong>), so you never re-subscribe.</p>
<p><em>Subscribed feeds are read-only and Google refreshes them on its own
   schedule &mdash; often up to 24 hours. For editable events, download a file
   and use Import instead.</em></p>

<h2>Archive</h2>
<ul>
{archive}
</ul>
<p><small>Per-category files exist for past years too, as
   <code>neu-undergrad-&lt;year&gt;-&lt;category&gt;.ics</code>.</small></p>

<footer>
  <p>Rebuilt {updated}. Source:
     <a href="https://registrar.northeastern.edu/article/academic-calendar/">NEU
     Office of the University Registrar</a>. Dates are subject to change and this
     is an unofficial mirror &mdash; verify anything that matters against the
     registrar.</p>
</footer>
<script>
  var base = location.href.replace(/(index\\.html)?(\\?.*)?(#.*)?$/, '');
  document.querySelectorAll('code.f').forEach(function (el) {{
    el.textContent = base + el.textContent;
  }});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
