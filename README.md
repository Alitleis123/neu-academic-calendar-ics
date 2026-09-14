# Northeastern academic calendar → iCalendar

Northeastern publishes its academic calendar **only as a PDF** — there is no
iCal/ICS feed anywhere on the registrar site. This repo scrapes that PDF weekly
and republishes it as a subscribable `.ics` feed, filtered to **Boston-campus
undergraduate** events.

## Subscribe

The **entire university-wide calendar** is the root. Each audience is a branch;
big branches split further by category. Subscribe at whatever depth you want —
one link per calendar. Base URL:
`https://alitleis123.github.io/neu-academic-calendar-ics/`

### Bundles

Common combinations, pre-merged so each is one subscription instead of several.
A bundle is a union of categories — nothing is exclusive to a bundle, so you can
always rebuild one from its parts.

| Bundle | Contains | Events | Feed |
|---|---|--:|---|
| **Everything except attendance** — the full calendar minus the I Am Here rows | all categories except `attendance` | 85 | `current-undergrad-no-attendance.ics` |
| **Drop risk** — every date that can remove you from a course | attendance + deadlines | 63 | `current-undergrad-drop-risk.ics` |
| **Essentials** — anything that costs money or cancels your day | deadlines + exams + holidays | 49 | `current-undergrad-essentials.ics` |
| **Term shape** — when terms run and when you're off | classes + holidays | 37 | `current-undergrad-term-shape.ics` |
| **Planning** — time off and when to sign up | holidays + registration | 16 | `current-undergrad-planning.ics` |
| **Conferral & schedules** | conferral + schedules | 9 | `current-undergrad-admin.ics` |
| **Enrollment** — schedule posts, then registration opens | registration + schedules | 6 | `current-undergrad-enrollment.ics` |

Bundles overlap by design — `essentials` and `planning` both contain the 13
holidays, so subscribing to both shows them twice. Combine non-overlapping
pieces instead.

Bundles exist for any audience large enough to split by category, as
`current-<audience>-<bundle>.ics`. `no-attendance` derives its members from
`CATEGORIES` rather than listing them, so a category added later is included
automatically.

### Full tree

| Branch | Events | Feed |
|---|--:|---|
| Entire university-wide calendar | 159 | `current-all.ics` |
| ├ **Boston undergraduate** | 121 | `current-undergrad.ics` |
| │ ├ Attendance (I Am Here) | 36 | `current-undergrad-attendance.ics` |
| │ ├ Add/drop & withdrawal | 27 | `current-undergrad-deadlines.ics` |
| │ ├ Term start & end | 24 | `current-undergrad-classes.ics` |
| │ ├ Holidays & breaks | 13 | `current-undergrad-holidays.ics` |
| │ ├ Final exam periods | 9 | `current-undergrad-exams.ics` |
| │ ├ Class schedule posting | 3 | `current-undergrad-schedules.ics` |
| │ ├ Degree conferral | 6 | `current-undergrad-conferral.ics` |
| │ └ Registration periods | 3 | `current-undergrad-registration.ics` |
| ├ Faculty grade deadlines | 14 | `current-faculty.ics` |
| ├ Canadian campuses | 9 | `current-canada-campus.ics` |
| ├ School of Law | 7 | `current-law.ics` |
| ├ Graduate-only | 4 | `current-grad-only.ics` |
| ├ Other US campuses | 2 | `current-other-campus.ics` |
| └ ABSN & CPS | 2 | `current-other-program.ics` |

In Google Calendar: **Other calendars → + → From URL**, paste one, subscribe.
One URL = one calendar = one checkbox. Want three branches? Subscribe three
times; each gets its own colour and toggle.

Every `current-*` feed tracks the newest academic year automatically, so when
Northeastern posts the next one it appears without you doing anything. Fixed
years are published too, as `neu-undergrad-<YYYY>-<YYYY>-<branch>.ics`.

Events carry ICS `CATEGORIES`, so clients that expose it (Apple Calendar,
Thunderbird) can filter a combined feed directly.

**Legacy paths.** `current.ics` and `current-<category>.ics` predate the
audience dimension and still resolve to the Boston-undergraduate branch, so
existing subscriptions keep working.

## Audiences

The registrar's PDF is *university-wide*. Nothing is discarded — every row is
labelled with the audience it applies to and published as its own branch:

| Audience | Example |
|---|---|
| `undergrad` | The default — anything not matched below |
| `law` | School of Law / JD classes, exams, registration |
| `canada-campus` | `CAN:` holidays (Vancouver, Toronto) |
| `faculty` | Faculty grade deadlines — i.e. when grades post |
| `grad-only` | Graduate registration that doesn't also name undergraduates |
| `other-campus` | Charlotte, Oakland/Silicon Valley, etc. |
| `other-program` | ABSN, College of Professional Studies |
| `quarter-calendar` | `QTR:` rows — programs on quarters, not semesters |

Boston-specific rows count as undergraduate (e.g. Patriots Day, "Boston and
Portland only"). **Not on the Boston campus?** Edit `OTHER_CAMPUSES` and
`AUDIENCES` in `neucal/categorize.py`.

Five first-day/last-day row pairs are collapsed into single multi-day events —
fall/spring break and the three final exam periods. This is derived from the row
text, not hardcoded dates, so it keeps working for future years.

## How it works

```
discover.py    scrape the registrar for <YYYY>-<YYYY>-Academic-Calendar.pdf links
pdf.py         inflate the Flate-compressed streams, pull text operators
parse.py       group rows, filter to undergraduate, collapse date spans
categorize.py  assign each event a category (first match wins; order matters)
ics.py         render RFC 5545 (CRLF, 75-octet folding, stable UIDs, CATEGORIES)
build.py       orchestrate, sanity-check, write every feed variant to docs/
```

**Adding a category or a bundle** is a one-line edit to `CATEGORIES` or
`BUNDLES` in `neucal/categorize.py`; the feeds, the index page, and the README table are all
driven from it. Order matters — "I Am Here" rows mention classes too, so
attendance is tested first.

No third-party dependencies — standard library only, so CI needs no install step.

**Stable UIDs.** Each event's UID is a hash of its date and title, so re-importing
updates events in place instead of duplicating them.

**Idempotent.** `DTSTAMP` is ignored when deciding whether to write, so the weekly
job only commits when the calendar actually changed. The git history of `docs/`
is therefore a record of when the registrar revised dates.

**Cron keepalive.** GitHub disables scheduled workflows on public repos after 60
days of repository inactivity. Since the registrar changes dates rarely, the job
would eventually switch itself off — so if the last commit is more than 50 days
old it writes `docs/last-checked.txt` to keep the schedule alive.

## Guardrails

`build.py` fails loudly rather than publishing a bad calendar. It rejects a build
where the event count falls outside 90–400, any of the three terms is missing, a
date lands outside the academic year, or **any event fails to categorize** — that
last check is what surfaced the `QTR:` quarter-calendar rows hiding in 2025-2026. If the registrar changes the PDF layout,
the job goes red and the last good calendar stays published.

Calendars before 2025-2026 use an older PDF layout this parser doesn't read, so
`EARLIEST_SUPPORTED` in `neucal/discover.py` skips them.

## Local use

```sh
python build.py                 # rebuild everything into docs/
python build.py --only-latest   # just the newest year
python -m unittest discover -s tests -v
```

Requires Python 3.9+.

## Caveat

Unofficial. Dates are subject to change and a scraper can be wrong — verify
anything that costs money (add/drop, withdrawal) against the
[registrar](https://registrar.northeastern.edu/article/academic-calendar/).
