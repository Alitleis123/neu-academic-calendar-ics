# Northeastern academic calendar → iCalendar

Northeastern publishes its academic calendar **only as a PDF** — there is no
iCal/ICS feed anywhere on the registrar site. This repo scrapes that PDF weekly
and republishes it as a subscribable `.ics` feed, filtered to **Boston-campus
undergraduate** events.

## Subscribe

```
https://alitleis123.github.io/neu-academic-calendar-ics/current.ics
```

In Google Calendar: **Other calendars → + → From URL**, paste, subscribe.

`current.ics` always serves the newest academic year the registrar has posted,
so when Northeastern publishes the next one it appears automatically — no
re-subscribing. Individual years are also published as
`neu-undergrad-<YYYY>-<YYYY>.ics`.

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

Boston-specific rows are kept (e.g. Patriots Day, "Boston and Portland only").

**Not on the Boston campus?** Edit `OTHER_CAMPUSES` and `exclusion_reason()` in
`neucal/parse.py`. Want faculty grade deadlines (they tell you when grades post)?
Delete the `faculty` branch.

Five first-day/last-day row pairs are collapsed into single multi-day events —
fall/spring break and the three final exam periods. This is derived from the row
text, not hardcoded dates, so it keeps working for future years.

## How it works

```
discover.py  scrape the registrar for <YYYY>-<YYYY>-Academic-Calendar.pdf links
pdf.py       inflate the Flate-compressed streams, pull text operators
parse.py     group rows, filter to undergraduate, collapse date spans
ics.py       render RFC 5545 (CRLF, 75-octet folding, stable UIDs)
build.py     orchestrate, sanity-check, write docs/
```

No third-party dependencies — standard library only, so CI needs no install step.

**Stable UIDs.** Each event's UID is a hash of its date and title, so re-importing
updates events in place instead of duplicating them.

**Idempotent.** `DTSTAMP` is ignored when deciding whether to write, so the weekly
job only commits when the calendar actually changed. The git history of `docs/`
is therefore a record of when the registrar revised dates.

## Guardrails

`build.py` fails loudly rather than publishing a bad calendar. It rejects a build
where the event count falls outside 90–400, any of the three terms is missing, or
a date lands outside the academic year. If the registrar changes the PDF layout,
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
