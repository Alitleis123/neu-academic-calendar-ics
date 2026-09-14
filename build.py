#!/usr/bin/env python3
"""Build, validate and publish Northeastern academic calendar subscriptions."""

import argparse
import datetime as dt
import hashlib
import json
import logging
import pathlib
import re
import sys
import time

from neucal import categorize, discover, ics, parse, pdf, publish
from neucal.logging import configured
from neucal.validate import SanityError, check

LOG = logging.getLogger("neucal.build")
DOCS = pathlib.Path(__file__).resolve().parent / "docs"
NAMESPACE = "neu-academic-calendar-ics"
CATEGORY_SPLIT_MIN = 20
SHORT_ALIASES = {
    "": "-undergrad",
    **{"-" + key: "-undergrad-" + key
       for key in categorize.keys() + categorize.bundle_keys()},
}
ARCHIVE_RE = re.compile(r"^neu-undergrad-(\d{4}-\d{4})-all\.ics$")
FEED_RE = re.compile(r"^(?:current|neu-undergrad-\d{4}-\d{4})(.*)\.ics$")


def _without_stamp(text):
    return ics.without_stamp(text)


def write_if_changed(path, text):
    """Compatibility helper for a single feed, with atomic replacement."""
    path = pathlib.Path(path)
    data = text.encode("utf-8")
    if path.exists():
        old = path.read_bytes()
        if ics.without_stamp(old.decode("utf-8")) == ics.without_stamp(text):
            return False
    publish.write_atomic(path, data)
    return True


def _variants(events, known_suffixes=()):
    yield "-all", "University-wide", lambda event: True
    for aud in categorize.audience_keys():
        items = [event for event in events if event.audience == aud]
        label = categorize.audience_label(aud)
        yield "-" + aud, label, lambda event, a=aud: event.audience == a
        split = (aud == "undergrad" or len(items) >= CATEGORY_SPLIT_MIN
                 or any(suffix.startswith("-" + aud + "-") for suffix in known_suffixes))
        if not split:
            continue
        for key in categorize.bundle_keys():
            members = categorize.bundle_members(key)
            yield ("-{}-{}".format(aud, key), label + " " + categorize.bundle_label(key),
                   lambda event, a=aud, m=members: event.audience == a and event.category in m)
        for key in categorize.keys():
            yield ("-{}-{}".format(aud, key), label + " " + categorize.label(key),
                   lambda event, a=aud, c=key: event.audience == a and event.category == c)


def render_feeds(events, year, url, stamp, prefix, known_suffixes=()):
    """Render every feed in memory, including empty feeds for existing URLs."""
    files, counts = {}, {}
    for suffix, label, keep in _variants(events, known_suffixes):
        subset = [event for event in events if keep(event)]
        undergrad = suffix.startswith("-undergrad")
        pretty = label.removeprefix("Boston undergraduate").strip() if undergrad else label
        title = "NEU {}{}".format("Undergrad " if undergrad else "", year)
        if pretty:
            title += " - " + pretty
        text = ics.render(
            subset, name=title,
            description="Northeastern Academic Calendar {}. {}. Source: {}".format(year, label, url),
            namespace=NAMESPACE, stamp=stamp)
        decoded = ics.read(text)
        if len(decoded) != len(subset) or [event[:5] for event in decoded] != [event[:5] for event in subset]:
            raise SanityError("Rendered feed does not match its input: " + prefix + suffix)
        files[prefix + suffix + ".ics"] = text.encode("utf-8")
        counts[suffix] = len(subset)
    for alias, target in SHORT_ALIASES.items():
        files[prefix + alias + ".ics"] = files[prefix + target + ".ics"]
    return files, counts


def _previous(output, year):
    path = output / ("neu-undergrad-" + year + "-all.ics")
    return ics.read(path.read_bytes().decode("utf-8")) if path.exists() else []


def _archives(output):
    years = set()
    if output.exists():
        for path in output.glob("neu-undergrad-*-all.ics"):
            match = ARCHIVE_RE.fullmatch(path.name)
            if match:
                discover.year_start(match[1])
                years.add(match[1])
    return years


def _local_sources(folder):
    found = {}
    metadata_path = folder / "sources.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    for path in sorted(folder.glob("*.pdf")):
        year = path.stem
        discover.year_start(year)
        if year >= discover.EARLIEST_SUPPORTED:
            info = metadata.get(year, {})
            url = info.get("url", path.resolve().as_uri())
            if not url.startswith("file:"):
                discover._validate_url(url)
            found[year] = url
    if not found:
        raise discover.SourceError("No supported YYYY-YYYY.pdf files in " + str(folder))
    return found


def _json(data):
    return (json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def rebuild(args, report):
    output = args.output_dir.resolve()
    stamp = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    with publish.locked(output):
        categorize.validate_config()
        found = _local_sources(args.source_dir) if args.source_dir else discover.discover(only_latest=args.only_latest)
        newest = discover.latest(found)
        archives = _archives(output)
        if archives and newest < max(archives):
            raise SanityError("Refusing to move current feeds from {} back to {}".format(max(archives), newest))
        years = [newest] if args.only_latest else sorted(found)
        report["current_year"] = newest
        report["discovered"] = found
        known_suffixes = {
            match[1] for path in output.glob("*.ics")
            if (match := FEED_RE.fullmatch(path.name))
        }
        built, failures = {}, {}
        # All selected years must succeed before publication starts.
        for year in years:
            started = time.monotonic()
            LOG.info("Building year=%s source=%s", year, found[year])
            try:
                if args.source_dir:
                    with (args.source_dir / (year + ".pdf")).open("rb") as stream:
                        raw = stream.read(discover.MAX_DOWNLOAD_BYTES + 1)
                else:
                    raw = discover.fetch(found[year])
                events, stats = parse.build(pdf.to_lines(raw))
                previous = _previous(output, year)
                check(events, year, previous=previous, accept_count_change=args.accept_count_change)
                events = ics.reconcile(events, previous, NAMESPACE, stamp)
                built[year] = (events, stats)
                report["years"][year] = {
                    "status": "valid", "source": found[year],
                    "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                    "elapsed_seconds": round(time.monotonic() - started, 3), **stats,
                }
            except Exception as exc:
                failures[year] = str(exc)
                report["years"][year] = {"status": "failed", "source": found[year], "error": str(exc)}
                LOG.error("Build failed year=%s error=%s", year, exc, exc_info=args.verbose)
        if failures:
            raise SanityError("No feeds published; {} year(s) failed: {}".format(
                len(failures), "; ".join("{}: {}".format(year, error) for year, error in failures.items())))

        # Include previously split audiences even when they disappear this year.
        for events, _ in built.values():
            known_suffixes.update(suffix for suffix, _, _ in _variants(events))
        files = {}
        manifest_path = output / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {
            "schema_version": 1, "years": {},
        }
        if manifest.get("schema_version") != 1 or not isinstance(manifest.get("years"), dict):
            raise SanityError("Unsupported or malformed manifest.json")
        manifest["current_year"] = newest
        for year, (events, stats) in built.items():
            rendered, counts = render_feeds(events, year, found[year], stamp, "neu-undergrad-" + year, known_suffixes)
            files.update(rendered)
            manifest["years"][year] = {
                "source": found[year], "sha256": report["years"][year]["sha256"],
                **stats, "feeds": counts,
            }
        current, current_counts = render_feeds(
            built[newest][0], newest, found[newest], stamp, "current", known_suffixes)
        files.update(current)
        prefixes = ["current"] + ["neu-undergrad-" + year for year in built]
        missing = sorted(path.name for prefix in prefixes for path in output.glob(prefix + "*.ics")
                         if path.name not in files)
        if missing:
            raise SanityError("Published subscription URLs would become stale: {}. "
                              "Keep compatibility aliases when renaming feeds".format(", ".join(missing)))
        files["manifest.json"] = _json(manifest)
        files["index.html"] = render_index(sorted(archives | set(built)), newest, current_counts, stamp).encode("utf-8")
        files[".nojekyll"] = b""
        # Keep timestamps when the semantic file content did not change.
        for name, data in files.items():
            path = output / name
            if not path.exists():
                continue
            old = path.read_bytes()
            if name.endswith(".ics"):
                equal = ics.without_stamp(old.decode("utf-8")) == ics.without_stamp(data.decode("utf-8"))
                if equal:
                    try:
                        ics.read(old.decode("utf-8"))
                    except ValueError:
                        # A semantically equal feed can still have broken folding.
                        equal = False
            elif name == "index.html":
                def scrub(value):
                    return re.sub(rb"Rebuilt \d{4}-\d{2}-\d{2}", b"Rebuilt", value)
                equal = scrub(old) == scrub(data)
            else:
                equal = old == data
            if equal:
                files[name] = old
        # An alias always has exactly the target bytes, including preserved stamps.
        for prefix in prefixes:
            for alias, target in SHORT_ALIASES.items():
                files[prefix + alias + ".ics"] = files[prefix + target + ".ics"]
        report["publication"] = publish.commit(output, files, dry_run=args.dry_run)
        report["feed_count"] = sum(name.endswith(".ics") for name in files)
        LOG.info("Build complete current=%s feeds=%d output=%s",
                 newest, report["feed_count"], output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only-latest", action="store_true", help="build the newest year and preserve existing archives")
    parser.add_argument("--output-dir", type=pathlib.Path, default=DOCS, help="feed destination, default: docs/")
    parser.add_argument("--source-dir", type=pathlib.Path, help="read YYYY-YYYY.pdf files locally instead of downloading")
    parser.add_argument("--dry-run", action="store_true", help="validate and report changes without writing feeds")
    parser.add_argument("--report", type=pathlib.Path, help="write a JSON diagnostic report, including on failure")
    parser.add_argument("--log-file", type=pathlib.Path, help="also append logs to this UTF-8 file")
    parser.add_argument("--verbose", action="store_true", help="show page details and exception tracebacks")
    parser.add_argument("--accept-count-change", action="store_true",
                        help="accept reviewed count reductions; all structural checks still apply")
    args = parser.parse_args(argv)
    # Reports and logs must not overwrite published feeds or local source PDFs.
    for path in (args.report, args.log_file):
        if path and (path.resolve().is_relative_to(args.output_dir.resolve())
                     or (args.source_dir and path.resolve().is_relative_to(args.source_dir.resolve()))):
            parser.error("Reports and logs must be outside the output and source directories")
    if args.report and args.log_file and args.report.resolve() == args.log_file.resolve():
        parser.error("--report and --log-file must be different files")
    started = time.monotonic()
    report = {"schema_version": 1, "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "status": "failed", "dry_run": args.dry_run, "years": {}, "warnings": []}
    code = 1
    try:
        with configured(logging.DEBUG if args.verbose else logging.INFO, args.log_file, report["warnings"]):
            try:
                rebuild(args, report)
                report["status"] = "dry-run" if args.dry_run else "success"
                code = 0
            except KeyboardInterrupt:
                report["error"] = "Interrupted"
                LOG.error("Build interrupted")
                code = 130
            except Exception as exc:
                report["error"] = str(exc)
                LOG.error("Build failed: %s", exc, exc_info=args.verbose)
    except OSError as exc:
        report["error"] = str(exc)
        print("Cannot configure logging: {}".format(exc), file=sys.stderr)
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        if args.report:
            try:
                publish.write_atomic(args.report, _json(report))
            except OSError as exc:
                print("Cannot write build report: {}".format(exc), file=sys.stderr)
                code = 1
    return code


def render_index(years, newest, written, stamp):
    from html import escape

    def feed_link(suffix):
        filename = "current" + suffix + ".ics"
        return '<a class="feed" href="{0}"><code>{0}</code></a>'.format(escape(filename, quote=True))

    def row(suffix, label, depth):
        count = written.get(suffix)
        if not count:
            return ""
        return ('<tr><th scope="row" class="d{depth}">{label}</th><td class="n">{count}</td>'
                '<td>{link}</td></tr>').format(
                    depth=depth, label=escape(label), count=count, link=feed_link(suffix))

    rows = [row("-all", "Entire university-wide calendar", 0)]
    for aud in categorize.audience_keys():
        if not written.get("-" + aud):
            continue
        rows.append(row("-" + aud, categorize.audience_label(aud), 1))
        for cat in categorize.keys():
            rows.append(row("-{}-{}".format(aud, cat), categorize.label(cat), 2))
    bundle_rows = []
    for key in categorize.bundle_keys():
        suffix = "-undergrad-" + key
        count = written.get(suffix)
        if count:
            bundle_rows.append(
                '<tr><th scope="row">{label}<br><small>{blurb}</small></th>'
                '<td>{members}</td><td class="n">{count}</td><td>{link}</td></tr>'.format(
                    label=escape(categorize.bundle_label(key)), blurb=escape(categorize.bundle_blurb(key)),
                    members=escape(" + ".join(categorize.label(member) for member in categorize.bundle_members(key))),
                    count=count, link=feed_link(suffix)))
    archive = "\n".join(
        '<li><a href="neu-undergrad-{year}-all.ics">{year}</a>{tag}</li>'.format(
            year=escape(year), tag=" <em>current</em>" if year == newest else "")
        for year in reversed(years))
    return INDEX_HTML.format(
        rows="\n".join(filter(None, rows)), bundles="\n".join(bundle_rows), archive=archive,
        newest=escape(newest), updated=stamp.strftime("%Y-%m-%d"))


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Northeastern academic calendar subscriptions</title>
<style>
  body {{ font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         max-width: 64rem; margin: 3rem auto; padding: 0 1.25rem; color: #1a1a1a; }}
  .table-scroll {{ overflow-x: auto; margin: 1.5rem 0; }}
  table {{ border-collapse: collapse; width: 100%; min-width: 48rem; }}
  th:last-child, td:last-child {{ min-width: 14rem; }}
  caption {{ text-align: left; font-weight: 600; padding-bottom: .5rem; }}
  td, th {{ text-align: left; padding: .6rem .5rem; border-bottom: 1px solid #ddd; vertical-align: top; }}
  tbody th {{ font-weight: 400; }}
  .n {{ text-align: right; color: #555; white-space: nowrap; }}
  .d0 {{ font-weight: 700; }}
  .d1 {{ padding-left: 1.5rem; font-weight: 600; }}
  .d2 {{ padding-left: 3rem; }}
  small {{ color: #555; }}
  a {{ color: #064d94; text-underline-offset: .15em; }}
  :focus-visible {{ outline: 3px solid #064d94; outline-offset: 3px; }}
  code {{ font-size: .82em; overflow-wrap: anywhere; }}
  footer {{ margin-top: 3rem; font-size: .9em; color: #555; }}
</style>
</head>
<body>
<main>
<h1>Northeastern academic calendar subscriptions</h1>
<p>Subscribe to the registrar's PDF calendar as <code>.ics</code> feeds.
The mirror rebuilds weekly and groups events by audience and category.</p>
<p>To subscribe in Google Calendar, choose <strong>Other calendars &rarr; + &rarr; From URL</strong>
and paste a feed link. In Apple Calendar, choose <strong>File &rarr; New Calendar Subscription</strong>.
Use the link address for a subscription. Opening a downloaded file imports a snapshot.</p>
<p><code>current-*</code> feeds track the newest published academic year, currently <strong>{newest}</strong>.
A future year's publication switches these feeds before that year begins.
Use a fixed-year archive link to keep following a particular year.</p>

<h2>Boston undergraduate bundles</h2>
<p>Each bundle combines the categories listed. Bundles overlap, so subscribing to several can show duplicate events.</p>
<p>On small screens, scroll tables sideways to reach the feed links.</p>
<div class="table-scroll" role="region" aria-label="Undergraduate bundles" tabindex="0">
<table>
<caption>Common category combinations</caption>
<thead><tr><th scope="col">Bundle</th><th scope="col">Contains</th><th scope="col" class="n">Events</th><th scope="col">Feed link</th></tr></thead>
<tbody>{bundles}</tbody>
</table>
</div>

<h2>All audiences and categories</h2>
<p>Choose the university-wide feed, an audience, or a category within a larger audience.
Events belong to one audience in this mirror. Check the registrar if a row applies to several populations.</p>
<div class="table-scroll" role="region" aria-label="Audience and category feeds" tabindex="0">
<table>
<caption>Available feeds</caption>
<thead><tr><th scope="col">Branch</th><th scope="col" class="n">Events</th><th scope="col">Feed link</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</div>

<h2>Archives</h2>
<ul>{archive}</ul>
<p>Fixed-year branches use <code>neu-undergrad-&lt;year&gt;-&lt;branch&gt;.ics</code>.
Existing feed URLs remain available even when a category becomes empty.</p>
<p>All events are all-day. Times mentioned in titles remain source text.
Calendar apps choose their own refresh schedule, so changes may take time to appear.</p>
</main>
<footer>
<p>Rebuilt {updated}. Source: <a href="https://registrar.northeastern.edu/article/academic-calendar/">Northeastern Office of the University Registrar</a>.
This is an unofficial mirror. Verify deadlines against the registrar.</p>
<p><a href="manifest.json">Calendar counts and source fingerprints</a></p>
</footer>
<script>
  document.querySelectorAll('a.feed').forEach(function (link) {{
    link.querySelector('code').textContent = new URL(link.getAttribute('href'), document.baseURI).href;
  }});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
