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

    months = {e.start.strftime("%b") for e in events}
    for term, needed in (("fall", "Sep"), ("spring", "Jan"), ("summer", "Jun")):
        if needed not in months:
            raise SanityError("{}: no {} events found (missing {}) — parse is incomplete."
                              .format(year, term, needed))

    lo, hi = dt.datetime(start_year, 7, 1), dt.datetime(start_year + 2, 1, 1)
    stray = [(e.start, e.title) for e in events if not lo <= e.start < hi]
    if stray:
        raise SanityError("{}: {} event(s) outside the academic year, e.g. {}"
                          .format(year, len(stray), stray[0]))

    uncategorized = [e.title for e in events if e.category == "other"]
    if uncategorized:
        raise SanityError("{}: {} uncategorized event(s), e.g. {!r}. Add a rule to "
                          "neucal/categorize.py.".format(year, len(uncategorized),
                                                         uncategorized[0]))


# An audience only gets per-category feeds if it is big enough for the split to
# be useful; a 7-event branch does not need seven sub-branches.
CATEGORY_SPLIT_MIN = 20


def _variants(events):
    """Yield (filename suffix, calendar-name suffix, predicate) over the tree.

    Root is the entire university-wide calendar. Each audience is a branch, and
    large audiences get category sub-branches.
    """
    yield "-all", " University-wide", lambda e: True

    present = [a for a in categorize.audience_keys()
               if any(e.audience == a for e in events)]
    for aud in present:
        in_aud = [e for e in events if e.audience == aud]
        label = categorize.audience_label(aud)
        yield "-" + aud, " " + label, (lambda e, a=aud: e.audience == a)

        if len(in_aud) < CATEGORY_SPLIT_MIN:
            continue
        for bkey in categorize.bundle_keys():
            members = categorize.bundle_members(bkey)
            if not any(e.category in members for e in in_aud):
                continue
            yield ("-{}-{}".format(aud, bkey),
                   " {} {}".format(label, categorize.bundle_label(bkey)),
                   (lambda e, a=aud, m=members: e.audience == a and e.category in m))
        for cat in categorize.keys():
            if not any(e.category == cat for e in in_aud):
                continue
            yield ("-{}-{}".format(aud, cat),
                   " {} {}".format(label, categorize.label(cat)),
                   (lambda e, a=aud, c=cat: e.audience == a and e.category == c))


# Short forms that omit the audience and mean "undergraduate", which is what
# almost everyone wants. These also cover the paths published before the
# audience dimension existed, so nobody already subscribed loses their calendar.
#
# Every category AND bundle gets one. Publishing current-essentials.ics but not
# current-planning.ics invites a guess that 404s, and a 404 subscription in
# Google Calendar fails silently as an empty calendar rather than an error.
SHORT_ALIASES = {
    "": "-undergrad",
    **{"-" + k: "-undergrad-" + k
       for k in list(categorize.keys()) + list(categorize.bundle_keys())},
}


def emit(events, year, url, stamp, prefix):
    """Write every variant for one year. Returns {suffix: count}."""
    written = {}
    for suffix, name_suffix, keep in _variants(events):
        subset = [e for e in events if keep(e)]
        if not subset:
            continue
        # "NEU Undergrad <year>" already says Boston undergraduate; repeating the
        # audience label produced "NEU Undergrad 2026-2027 Boston undergraduate".
        pretty = name_suffix.strip()
        if pretty.startswith("Boston undergraduate"):
            pretty = pretty[len("Boston undergraduate"):].strip()
        title = "NEU {} {}".format("Undergrad" if not pretty or
                                   suffix.startswith("-undergrad") else "", year)
        title = " ".join(title.split())
        if pretty:
            title += " — " + pretty

        text = ics.render(
            subset,
            name=title,
            description=("Northeastern University-Wide Academic Calendar {}{}. "
                         "Source: {}".format(
                             year, " — " + pretty if pretty else "", url)),
            namespace=NAMESPACE,
            stamp=stamp,
        )
        write_if_changed(DOCS / "{}{}.ics".format(prefix, suffix), text)
        written[suffix] = len(subset)

    for legacy, target in SHORT_ALIASES.items():
        src = DOCS / "{}{}.ics".format(prefix, target)
        if src.exists():
            write_if_changed(DOCS / "{}{}.ics".format(prefix, legacy),
                             src.read_bytes().decode())
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
        print("  {}  {} events  audiences={}".format(
            year, stats["kept"], stats["audiences"]))

    # The newest year must always build — it is what the `current-*` feeds serve.
    if newest in failures:
        raise SystemExit("FATAL: newest year {} failed to build: {}"
                         .format(newest, failures[newest]))

    events, _ = built[newest]
    written = emit(events, newest, found[newest], stamp, "current")
    print("current* -> {}  ({} feeds)".format(newest, len(written)))

    write_index(sorted(built), newest, built[newest][1], written)
    return 0


def write_index(years, newest, stats, written):
    from html import escape

    def row(suffix, label, depth):
        n = written.get(suffix)
        if not n:
            return ""
        return ('  <tr><td class="d{d}">{label}</td><td class="n">{n}</td>'
                '<td><code class="f">current{sfx}.ics</code></td></tr>').format(
            d=depth, label=escape(label), n=n, sfx=escape(suffix))

    lines = [row("-all", "Entire university-wide calendar", 0)]
    for aud in categorize.audience_keys():
        if not written.get("-" + aud):
            continue
        lines.append(row("-" + aud, categorize.audience_label(aud), 1))
        for cat in categorize.keys():
            lines.append(row("-{}-{}".format(aud, cat), categorize.label(cat), 2))
    rows = "\n".join(l for l in lines if l)

    bundle_rows = []
    for bkey in categorize.bundle_keys():
        sfx = "-undergrad-{}".format(bkey)
        n = written.get(sfx)
        if not n:
            continue
        members = " + ".join(categorize.label(m) for m in categorize.bundle_members(bkey))
        bundle_rows.append(
            '  <tr><td><strong>{label}</strong><br><small>{blurb}</small></td>'
            '<td>{members}</td><td class="n">{n}</td>'
            '<td><code class="f">current{sfx}.ics</code></td></tr>'.format(
                label=escape(categorize.bundle_label(bkey)),
                blurb=escape(categorize.bundle_blurb(bkey)),
                members=escape(members), n=n, sfx=escape(sfx)))
    bundles = "\n".join(bundle_rows)

    archive = "\n".join(
        '    <li><a href="neu-undergrad-{y}-all.ics">{y}</a>{tag}</li>'.format(
            y=escape(y), tag=" <em>(current)</em>" if y == newest else "")
        for y in reversed(years))

    html = INDEX_HTML.format(rows=rows, bundles=bundles, archive=archive,
                             newest=escape(newest),
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
  td.d0 {{ font-weight: 600; }}
  td.d1 {{ padding-left: 1.5rem; font-weight: 600; }}
  td.d2 {{ padding-left: 3rem; color: #444; }}
  small {{ color: #666; }}
  code {{ background: #f4f4f5; padding: .15em .4em; border-radius: 4px;
          font-size: .82em; word-break: break-all; }}
  footer {{ margin-top: 3rem; font-size: .85em; color: #666; }}
</style>
</head>
<body>
<h1>Northeastern academic calendar, as iCalendar feeds</h1>
<p>Northeastern publishes its academic calendar only as a PDF. This rebuilds it
   weekly as <code>.ics</code> feeds, split by <strong>audience</strong> and
   <strong>category</strong> so you can subscribe to exactly the slice you
   want.</p>

<h2>Bundles</h2>
<p>Common combinations, pre-merged so they are one subscription instead of
   several. Each is a union of the categories listed.</p>
<table>
  <tr><th>Bundle</th><th>Contains</th><th class="n">Events</th><th>URL</th></tr>
{bundles}
</table>

<h2>Full tree</h2>
<p>Or pick any single branch. The whole university-wide calendar is the root;
   each audience is a branch, and the big ones split further by category.
   Bundles above are unions of the category rows below.</p>
<table>
  <tr><th>Branch</th><th class="n">Events</th><th>URL</th></tr>
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
<p><small>Every branch exists per-year too, as
   <code>neu-undergrad-&lt;year&gt;-&lt;branch&gt;.ics</code>.</small></p>

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
