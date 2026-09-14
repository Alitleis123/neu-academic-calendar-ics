# Audit and verification record

Audited September 14, 2026, starting from commit `f62f72c` with a clean working
tree. The audit covered every Python module, the build workflow, published
feeds, the subscription page, documentation and tests.

## Confirmed defects and fixes

| Finding | Effect | Fix |
|---|---|---|
| PDF extraction matched `ET` inside text as an operator | Truncated 39 grade-deadline descriptions across both source PDFs, including four lost Law qualifiers | Replaced the regex reader with strict, bounded `pypdf` extraction and real PDF regression fixtures |
| Every mention of final exams matched the exam category | Filed six undergraduate class-end dates per year under exams; quarter-calendar rows had the same problem | Exam rules now require an exam period or window; class boundaries remain in classes |
| Prefixed quarter-calendar markers never formed spans | Published first/last markers separately and missed winter exam ranges | Normalize recognized prefixes, support winter and preserve audience/scope when pairing |
| Span pairing trusted source order and ignored scope | Could pair unrelated rows or create backward or excessive ranges | Match unambiguous markers by audience, term and qualifier; validate dates before merging |
| Unreadable PDF streams and orphan text were silently skipped | Could publish incomplete or truncated data without a clear error | Check the PDF structure, each page, resource limits, decoded text, row dates and descriptions |
| Audience matching was case sensitive in several paths | Uppercase graduate labels and mixed-case Boston qualifiers could be classified incorrectly | Consistent case-insensitive rules, individual campus names and explicit checks for unknown scope |
| Event counts covered only the university-wide total | A largely missing undergraduate calendar could still pass | Separate undergraduate bounds, category minimums, term checks, required spans and comparison with the previous year-specific feed |
| A failed build could modify some year files first | Left a partial local publication; old-year failures could be hidden by successful current feeds | Parse, validate and render all selected years before staging any publication |
| Empty or smaller branches stopped generating files | Old events remained at existing subscription URLs | Emit valid empty feeds and preserve previously split branches; reject unmapped retired feed names |
| Short aliases copied whatever happened to be on disk | Could copy stale target files into supposedly current aliases | Generate aliases from the same build, then enforce exact target bytes |
| `--only-latest` replaced the archive index with one year | Hid retained historical feeds from the site | Preserve archive links and metadata for years not rebuilt |
| Date-only corrections changed event IDs | Calendar clients could treat a moved event as unrelated | Preserve the prior UID for unique title matches and update revision metadata |
| Calendar metadata was unescaped and timestamps assumed UTC | Could emit malformed fields, injected content lines or incorrect UTC timestamps | Escape all text, declare extension TEXT values, normalize timestamps and validate every rendered feed |
| Assigned category values were ignored when rendering | An explicit classification could differ from its ICS category | Render the stored category directly and verify source-event membership |
| Git could normalize ICS line endings | Checked-out feeds could violate required CRLF formatting | Added per-format Git attributes; validation checks CRLF and UTF-8 folding |
| Downloads had no retries, response bounds or transfer checks | Transient errors failed immediately; invalid responses had weak diagnostics | Bounded retries, Retry-After handling, byte/time limits, expected content checks and trusted HTTPS redirects |
| Writes were not atomic and local builds could overlap | Readers could receive truncated files or competing updates | Per-output OS locks, staged replacements, rollback and retained recovery files if rollback itself fails |
| Logs lacked consistent severity and structured results | Failures were hard to diagnose or compare between runs | UTC logs, verbose tracebacks, JSON reports, source fingerprints, count summaries and changed-file lists |
| The workflow ignored newly created files when detecting changes | A build adding only new feeds could skip its commit | Stage generated files before checking the diff |
| Scheduled bot commits relied on branch-based Pages publishing | GitHub documents that `GITHUB_TOKEN` pushes do not trigger a Pages build | Added explicit upload/deploy jobs, restricted permissions, diagnostics artifacts and SHA-pinned actions |
| Feed URLs were plain code text with script-dependent expansion | Links were less usable from the keyboard and without JavaScript | Native links, scoped table headers, focus outlines, readable contrast and scrollable tables |
| README counts and implementation claims were stale | Described an obsolete parser, wrong counts and stronger UID guarantees than the code provided | Rewrote usage, data semantics, maintenance and operational limits; counts now live in generated output |

## Source results

Both live downloads matched the fingerprints stored with the test fixtures.

| Academic year | Source rows | Published events | Undergraduate events | Merged ranges |
|---|---:|---:|---:|---:|
| 2025-2026 | 269 | 259 | 120 | 10 |
| 2026-2027 | 164 | 159 | 121 | 5 |

The earlier 2025-2026 total was 264. Its five-event reduction comes from merging
five quarter-calendar ranges, with no lost source rows. Undergraduate exam
feeds now contain three exam periods, and class-boundary feeds contain 30
events. The undergraduate total is unchanged in both years.

All 230 unchanged date/title identities in 2025-2026 and all 144 in 2026-2027
retain their original UIDs. Restoring truncated titles creates new identities;
the affected old entries disappear from the regenerated full feeds. Corrected
category assignments increment the existing event sequence.

The local output contains 174 ICS files. All 135 original published paths,
including the index page, remain present. Added empty feeds prevent missing
categories and disappearing audiences from leaving stale subscriptions.

## Verification

- 103 tests passed on Python 3.10.21 and Python 3.14.7.
- Coverage reported 94%, including branches. CI enforces a minimum of 85%.
- Ruff, actionlint and `git diff --check` passed.
- Runtime and complete local development-environment dependency audits reported no known vulnerabilities.
- Both real source PDFs passed live discovery, fetching, extraction and validation.
- A second live build changed zero of 177 generated files and reported zero warnings.
- An independent iCalendar library parsed all 174 generated calendars.
- All 26 local links on the generated page returned HTTP 200; ICS responses used `text/calendar`.
- Desktop and 390-pixel mobile browser checks confirmed working URL expansion and no document overflow. Tables scroll horizontally to keep feed links readable.
- Failure tests cover either year's failure, rendering failures, disk failures, failed rollback recovery, concurrent builds, stale URLs, year rollback and interrupted builds.
- Regression tests verify date corrections, exact aliases, retained archives, empty feeds, decompression bounds, Unicode folding, metadata escaping and timezone conversion.

Diagnostic artifacts from the audit are local to the Mac mini:

- `/tmp/neucal-final-build.json` and `/tmp/neucal-final-build.log`
- `/tmp/neucal-regeneration.json`, including the reviewed classification migration
- `/tmp/neucal-tests.log` and `/tmp/neucal-tests-py310.log`
- `/tmp/neucal-audit-desktop.png`, `/tmp/neucal-audit-mobile.png` and `/tmp/neucal-audit-mobile-table.png`

## Deployment and remaining limits

At audit completion, these changes and regenerated feeds were local. The audit
did not deploy the public site or change repository settings.

The repository's Pages configuration was verified as `legacy`, publishing
`main:/docs`. When deploying the new workflow, select **GitHub Actions** as the
Pages source and run **Rebuild calendars**. This avoids the documented
[bot-push limitation](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).

PDF layout changes can still require parser updates. Unsupported or ambiguous
input fails validation rather than publishing inferred dates. There are no
source event IDs, so title changes and ambiguous matches cannot reliably retain
identity. The mirror assigns one audience per row and keeps all events all-day.
The source omits closing dates for some Law exam periods; these remain opening
markers. Calendar apps control refresh and event-removal behavior.

Each file replacement is atomic, but the whole local directory is not a single
atomic operation. OS termination or power loss can interrupt publication.
Ordinary exceptions and Ctrl-C trigger rollback; failed rollback keeps its
recovery files. Pages receives a complete validated artifact. Local OS locking
currently supports macOS and Linux.

The supported local setup now uses Python 3.10+ and a pinned PDF dependency.
See [README.md](README.md) for installation and recovery options.

Reference behavior was checked against the
[pypdf extraction documentation](https://pypdf.readthedocs.io/en/stable/user/extract-text.html),
[RFC 5545](https://www.rfc-editor.org/rfc/rfc5545.html) and
[RFC 7986](https://www.rfc-editor.org/rfc/rfc7986.html).
