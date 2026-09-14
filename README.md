# Northeastern academic calendar subscriptions

Mirrors Northeastern's university-wide academic-calendar PDFs as subscribable
iCalendar feeds. The scheduled build checks the registrar every Monday and
publishes feeds by audience, category, and common category combinations.

[Browse the feeds](https://alitleis123.github.io/neu-academic-calendar-ics/).
The mirror is unofficial. Verify deadlines against the
[registrar](https://registrar.northeastern.edu/article/academic-calendar/).

## Subscribe

Copy a feed's link address from the site. In Google Calendar, use **Other
calendars → + → From URL**. In Apple Calendar, use **File → New Calendar
Subscription**. Opening a downloaded file imports a snapshot.

Common feed names, relative to the site URL:

| Feed | Contents |
|---|---|
| current-all.ics | Every audience |
| current-undergrad.ics | Boston undergraduate events |
| current-undergrad-no-attendance.ics | All undergraduate categories except I Am Here |
| current-undergrad-essentials.ics | Deadlines, exam periods, holidays and breaks |
| current-undergrad-drop-risk.ics | Attendance confirmations, drops and course deadlines |
| current-undergrad-term-shape.ics | Class start/end dates, holidays and breaks |
| current-undergrad-planning.ics | Holidays and registration |
| current-undergrad-enrollment.ics | Schedule postings and registration |
| current-undergrad-admin.ics | Degree conferrals and schedule postings |

Each category also has its own feed, such as
`current-undergrad-deadlines.ics`. Bundles overlap, so subscribing to several
may display duplicate events.

`current-*` follows the **newest published academic year**, including a future
year as soon as the registrar publishes it. It does not select a year based on
today's date. Fixed-year feeds such as `neu-undergrad-2026-2027-all.ics` remain
available, including all their branches.

Legacy short names such as `current.ics`, `current-deadlines.ics` and
`current-planning.ics` are exact copies of their undergraduate counterparts.
An existing feed becomes a valid empty calendar when its audience or category
has no events. It never keeps serving old events just because its count is zero.

The generated site and [manifest](https://alitleis123.github.io/neu-academic-calendar-ics/manifest.json)
contain current counts. There are no manually maintained count tables in this
README.

## Audience and category rules

Each source row belongs to one audience and one category. Specific audiences
include Law, Canadian campuses, quarter-calendar programs, other campuses,
faculty, graduate-only events, and ABSN/CPS. Rows that do not match a specific
audience default to Boston undergraduate. Shared rows are not duplicated into
several audiences.

Rules live in `neucal/categorize.py`. Order matters. Campus matching is case
insensitive and keeps rows that explicitly include Boston. Unknown source
prefixes and unknown "only" qualifiers fail the build for review.

Class boundaries that mention "with final exams" or "without final exams" belong
to classes. The exams category contains actual exam periods. Grade deadlines
retain the source's times, but every event in these feeds is **all-day**.
A faculty submission deadline does not promise a student grade-release time.

Matching break and exam rows collapse into inclusive ranges, separately for
each audience and scope. Breaks end the day before classes resume. Exam periods
include their closing day. The current PDFs give only opening dates for some
Law exam periods; those remain single-day source markers. Ambiguous or
backward ranges fail validation.

## Run locally

Python 3.10 or newer on macOS or Linux. PDF parsing uses the pinned `pypdf`
dependency. All network access stays on the registrar's HTTPS host.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

python build.py --dry-run --report build-report.json
python build.py --report build-report.json --log-file build.log
python build.py --only-latest
```

Useful options:

| Option | Behavior |
|---|---|
| --dry-run | Run discovery, parsing, validation and rendering without writing feeds |
| --output-dir PATH | Write feeds into another directory |
| --source-dir PATH | Read local YYYY-YYYY.pdf files without network access |
| --only-latest | Build only the newest year; retain existing archives and links |
| --report PATH | Write JSON diagnostics on success or failure |
| --log-file PATH | Append timestamped UTF-8 logs |
| --verbose | Include per-page details and exception tracebacks |
| --accept-count-change | Accept a reviewed count reduction; structural checks still apply |

Reports and logs must be outside the source and output directories. A dry run
may write an explicitly requested report or log. Exit codes are 0 for success,
1 for build or I/O failure, 2 for invalid CLI arguments, and 130 for interruption.

To reproduce the checked-in source fixtures offline:

```sh
python build.py --source-dir tests/fixtures --output-dir /tmp/neucal-preview
```

An optional `sources.json` in the source directory maps each year to its
original `url`. Without it, descriptions identify the local PDF by file URI.
The fixture metadata also records SHA-256 checksums; regression tests verify
those checksums.

## Checks and publication

All selected years must pass before the builder changes any feed. A failed
archive year also fails a full build. The current index cannot silently fall
back to an older archive, and the latest year cannot move backward relative
to existing fixed-year feeds.

The build checks:

- Download signatures, response sizes, transfer completeness, redirects and timeouts.
- PDF page count, decompression limits, readable page text and document structure.
- Empty descriptions, malformed dates, duplicate rows and unknown audience scopes.
- Total and undergraduate counts, required categories and coverage of each term.
- Paired undergraduate breaks and exam periods, inclusive end dates and duplicate IDs.
- Large count reductions compared with the previous feed for the same year.
- Every rendered feed's encoding, structure, categories, dates and source-event membership.
- Continued generation of every existing subscription URL in the years being rebuilt.

Exact duplicate source rows are counted, logged and collapsed to one event.
Structural failures cannot be bypassed with `--accept-count-change`.
The academic-year date window runs from July 1 through September 30 of the
following year to include registration and summer Law grade deadlines.

All changed files are staged before replacement. Each replacement is atomic,
and ordinary write failures or Ctrl-C restore the originals. A failed rollback
retains recovery files and reports their path. Local readers can briefly see
a mixture of files during replacement. A machine crash or forced process kill
cannot be rolled back by Python. GitHub Pages deploys the completed artifact
only after the build succeeds.

A per-output OS lock prevents concurrent local builds. Unchanged files keep
their bytes and modification times. `manifest.json` records source URLs,
fingerprints, counts and feed membership counts without adding a timestamp
that would create weekly commit churn. The separate build report records
elapsed times, warnings, errors and changed/unchanged filenames.

## Event identity

Unchanged events retain existing UIDs and revision timestamps. When a title
occurs exactly once in the old and new versions of a year, a corrected date
keeps its UID and increments `SEQUENCE`. Category or range changes also update
the revision. The fixed-year `-all.ics` file supplies this previous state, so
keep it when rebuilding existing subscriptions.

The PDF has no source event IDs. Changed titles and ambiguous matches receive
new IDs; the builder does not guess which event was renamed. Calendar clients
control how quickly they refresh and remove replaced events. Restored text in
this audit necessarily replaces the IDs of previously truncated descriptions.

## Tests and maintenance

```sh
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m coverage run -m unittest discover -s tests -v
python -m coverage report
python -m pip_audit -r requirements.txt --progress-spinner off
actionlint .github/workflows/rebuild.yml
```

The test suite is offline. It uses both supported PDF layouts, real malformed
PDF inputs, simulated network and filesystem failures, complete builds, and an
independent iCalendar reader. Coverage includes branches and must remain at
least 85%. CI runs on Python 3.10 and 3.14. Install `actionlint` separately to
validate the workflow locally.

Calendars before 2025-2026 use unsupported layouts. The builder fails if a new
layout cannot be read safely. Review the registrar PDF, update the parser or
classification rules, add a regression case, then build with `--dry-run`.
Use `--accept-count-change` only after checking an intentional reduction.
The September 2026 audit used it to migrate class-end rows out of the exam
category; the regenerated feeds already contain that migration.

When renaming categories or bundles, retain compatibility aliases for their
published URLs. Dependabot checks pinned Python packages weekly and GitHub
Actions monthly.

## GitHub Actions and Pages

The workflow tests pull requests with read-only repository access. Main-branch
builds fetch the live PDFs, save diagnostics even on failure, commit generated
changes, upload the site artifact and deploy it to Pages. Actions are pinned
to commit SHAs. A keepalive commit after 50 idle days prevents the public
repository's scheduled workflow from reaching GitHub's inactivity limit.

**One-time deployment setup:** after merging this workflow, set repository
**Settings → Pages → Build and deployment → Source → GitHub Actions**, then
run **Rebuild calendars**. The repository used branch publishing from
`main:/docs` at audit time. GitHub documents that commits pushed with
`GITHUB_TOKEN` do not trigger a branch-based Pages build, so the workflow
now uses explicit artifact deployment.
See [GitHub's publishing-source documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).

A failed push or build prevents deployment. Do not switch Pages back to
branch publishing while relying on the scheduled bot commits.

The detailed findings and verification record are in [AUDIT.md](AUDIT.md).
