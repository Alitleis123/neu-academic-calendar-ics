# Northeastern academic calendar → iCalendar

Northeastern publishes its academic calendar **only as a PDF** — there is no
iCal/ICS feed anywhere on the registrar site. This repo scrapes that PDF weekly
and republishes it as a subscribable `.ics` feed, filtered to **Boston-campus
undergraduate** events.

## Subscribe

Pick the slice you want — subscribe to one, or several with different colours.
Base URL: `https://alitleis123.github.io/neu-academic-calendar-ics/`

| Feed | Events | What's in it |
|---|--:|---|
| `current-essentials.ics` | 49 | **Recommended.** Deadlines, exams, holidays. |
| `current.ics` | 121 | Everything below, combined. |
| `current-deadlines.ics` | 27 | Add/drop and withdrawal — the ones with money attached. |
| `current-attendance.ics` | 36 | "I Am Here" confirmations and the drops for missing them. |
| `current-classes.ics` | 24 | First/last day of each term, session, and third. |
| `current-holidays.ics` | 13 | No-class days, fall break, spring break. |
| `current-exams.ics` | 9 | Final exam periods. |
| `current-admin.ics` | 9 | Degree conferral, next term's schedule posting. |
| `current-registration.ics` | 3 | When your registration window opens. |

In Google Calendar: **Other calendars → + → From URL**, paste, subscribe.

Attendance is 36 of the 121 events — nearly a third — which is why it's split
out. `current-essentials.ics` is the version most people actually want.

Every `current-*` feed tracks the newest academic year the registrar has posted,
so when Northeastern publishes the next one it appears automatically — no
re-subscribing. Per-year, per-category files are published too, as
`neu-undergrad-<YYYY>-<YYYY>[-<category>].ics`.

Events also carry an ICS `CATEGORIES` property, so clients that expose it
(Apple Calendar, Thunderbird) can filter the combined feed directly.

> Subscribed feeds are read-only, and Google refreshes them on its own schedule
> (often up to 24h). If you want editable events or an immediate update,
> download a year file and use **Import** instead.

## What gets filtered

The registrar's PDF is *university-wide*. Each row is dropped if it is:

| Reason | Example |
|---|---|
| `law` | School of Law / JD classes, exams, registration |
| `canada-campus` | `CAN:` holidays (Vancouver, Toronto) |
| `faculty` | Faculty grade deadlines — not student-facing |
| `grad-only` | Graduate registration that doesn't also name undergraduates |
| `other-campus` | Charlotte, Oakland/Silicon Valley, etc. |
| `other-program` | ABSN, College of Professional Studies |
| `quarter-calendar` | `QTR:` rows — programs on quarters, not semesters |

Boston-specific rows are kept (e.g. Patriots Day, "Boston and Portland only").

**Not on the Boston campus?** Edit `OTHER_CAMPUSES` and `exclusion_reason()` in
`neucal/parse.py`. Want faculty grade deadlines (they tell you when grades post)?
Delete the `faculty` branch.

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

**Adding or changing a category** is a one-line edit to `CATEGORIES` in
`neucal/categorize.py`; the feeds, the index page, and the README table are all
driven from it. Order matters — "I Am Here" rows mention classes too, so
attendance is tested first.

No third-party dependencies — standard library only, so CI needs no install step.

**Stable UIDs.** Each event's UID is a hash of its date and title, so re-importing
updates events in place instead of duplicating them.

**Idempotent.** `DTSTAMP` is ignored when deciding whether to write, so the weekly
job only commits when the calendar actually changed. The git history of `docs/`
is therefore a record of when the registrar revised dates.

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
