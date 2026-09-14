import contextlib
import datetime as dt
import io
import json
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

from helpers import FIXTURES
from icalendar import Calendar

import build
from neucal import ics, parse, pdf, publish
from neucal.validate import SanityError, check


def snapshot(folder):
    return {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in folder.iterdir() if path.is_file()}


class TestValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events, _ = parse.build(pdf.to_lines((FIXTURES / "2026-2027.pdf").read_bytes()))

    def test_rejects_partial_undergraduate_calendar(self):
        events = [event._replace(audience="quarter-calendar") if index > 60 else event
                  for index, event in enumerate(self.events)]
        with self.assertRaisesRegex(SanityError, "undergraduate events"):
            check(events, "2026-2027")

    def test_rejects_bad_counts_dates_categories_and_duplicates(self):
        cases = [self.events[:30], self.events * 3, self.events + [self.events[0]],
                 [self.events[0]._replace(category="other")] + self.events[1:],
                 [self.events[0]._replace(audience="missing")] + self.events[1:],
                 [self.events[0]._replace(end=dt.datetime(2029, 1, 1))] + self.events[1:]]
        for events in cases:
            with self.subTest(events=len(events)), self.assertRaises(SanityError):
                check(events, "2026-2027")

    def test_terms_and_span_integrity(self):
        events = [event for event in self.events if event.title != "Spring Break"]
        with self.assertRaisesRegex(SanityError, "Spring break"):
            check(events, "2026-2027")
        events = [event._replace(title="Exam window") if event.title == "Spring Final Exam Period" else event
                  for event in self.events]
        with self.assertRaisesRegex(SanityError, "spring exams"):
            check(events, "2026-2027")

    def test_large_loss_requires_review_but_override_keeps_other_checks(self):
        previous = self.events + [event._replace(title=event.title + " old") for event in self.events]
        with self.assertRaisesRegex(SanityError, "large count reduction"):
            check(self.events, "2026-2027", previous=previous)
        with self.assertLogs("neucal.validate", "WARNING"):
            check(self.events, "2026-2027", previous=previous, accept_count_change=True)
        with self.assertRaises(SanityError):
            check(self.events[:10], "2026-2027", previous=previous, accept_count_change=True)


class TestPublication(unittest.TestCase):
    def test_dry_run_has_no_output_side_effect(self):
        with tempfile.TemporaryDirectory() as folder:
            target = pathlib.Path(folder) / "output"
            result = publish.commit(target, {"a.ics": b"new"}, dry_run=True)
            self.assertEqual(result["changed"], ["a.ics"])
            self.assertFalse(target.exists())

    def test_write_failure_restores_originals_and_removes_new_files(self):
        with tempfile.TemporaryDirectory() as folder:
            target = pathlib.Path(folder) / "output"
            target.mkdir()
            (target / "b.ics").write_bytes(b"old b")
            (target / "c.ics").write_bytes(b"old c")
            replace = publish.os.replace
            def fail_once(source, destination):
                if pathlib.Path(source).name == "c.ics" and pathlib.Path(destination).parent == target:
                    raise OSError("simulated disk failure")
                return replace(source, destination)
            with mock.patch.object(publish.os, "replace", side_effect=fail_once):
                with self.assertLogs("neucal.publish", "ERROR"), self.assertRaises(OSError):
                    publish.commit(target, {"a.ics": b"new a", "b.ics": b"new b", "c.ics": b"new c"})
            self.assertEqual({path.name: path.read_bytes() for path in target.iterdir()},
                             {"b.ics": b"old b", "c.ics": b"old c"})
            self.assertEqual(sorted(path.name for path in pathlib.Path(folder).iterdir()), ["output"])

    def test_stage_failure_does_not_change_output(self):
        with tempfile.TemporaryDirectory() as folder:
            target = pathlib.Path(folder) / "output"
            with mock.patch.object(publish, "write_atomic", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    publish.commit(target, {"a.ics": b"new"})
            self.assertFalse(target.exists())

    def test_failed_rollback_keeps_recovery_files(self):
        with tempfile.TemporaryDirectory() as folder:
            target = pathlib.Path(folder) / "output"
            target.mkdir()
            (target / "a.ics").write_bytes(b"old a")
            (target / "b.ics").write_bytes(b"old b")
            replace = publish.os.replace
            def fail(source, destination):
                if pathlib.Path(destination).parent == target:
                    if pathlib.Path(source).name == "b.ics" or pathlib.Path(source).parent.name == "backup":
                        raise OSError("filesystem unavailable")
                return replace(source, destination)
            with mock.patch.object(publish.os, "replace", side_effect=fail):
                with self.assertRaisesRegex(RuntimeError, "recovery files retained"):
                    publish.commit(target, {"a.ics": b"new a", "b.ics": b"new b"})
            recovery = list(pathlib.Path(folder).glob(".neucal-stage-*/backup/a.ics"))
            self.assertEqual(len(recovery), 1)
            self.assertEqual(recovery[0].read_bytes(), b"old a")

    def test_noop_preserves_mtime_and_rejects_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            target = pathlib.Path(folder)
            publish.commit(target, {"test.ics": b"same"})
            before = snapshot(target)
            result = publish.commit(target, {"test.ics": b"same"})
            self.assertEqual(result["changed"], [])
            self.assertEqual(before, snapshot(target))
            with self.assertRaises(ValueError):
                publish.commit(target, {"../outside": b"x"})
            (target / "link.ics").symlink_to(target / "test.ics")
            with self.assertRaises(ValueError):
                publish.commit(target, {"link.ics": b"x"})

    def test_os_lock_prevents_concurrent_builds_and_releases(self):
        with tempfile.TemporaryDirectory() as folder:
            target = pathlib.Path(folder)
            with publish.locked(target):
                with self.assertRaisesRegex(RuntimeError, "Another build"):
                    with publish.locked(target):
                        self.fail("concurrent lock acquired")
            with publish.locked(target):
                pass


class TestBuildIntegration(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name)
        self.output = self.root / "docs"
        self.report = self.root / "report.json"

    def run_build(self, *args, source=FIXTURES):
        with contextlib.redirect_stderr(io.StringIO()):
            return build.main(["--source-dir", str(source), "--output-dir", str(self.output),
                               "--report", str(self.report), *args])

    def test_build_is_idempotent_and_all_feeds_are_readable(self):
        self.assertEqual(self.run_build(), 0)
        before = snapshot(self.output)
        report = json.loads(self.report.read_text())
        self.assertEqual(report["status"], "success")
        self.assertEqual(report["years"]["2026-2027"]["categories"]["exams"], 3)
        for filename, (data, _) in before.items():
            if filename.endswith(".ics"):
                cal = Calendar.from_ical(data)
                items = cal.walk("VEVENT")
                self.assertEqual(len(items), len(ics.read(data.decode())))
                for event in items:
                    self.assertFalse(event.errors)
                    self.assertGreater(event.decoded("DTEND"), event.decoded("DTSTART"))
                    self.assertEqual(event.decoded("DTSTAMP").utcoffset(), dt.timedelta(0))
        self.assertEqual(self.run_build(), 0)
        self.assertEqual(before, snapshot(self.output))
        self.assertEqual(json.loads(self.report.read_text())["publication"]["changed"], [])

    def test_aliases_are_exact_and_empty_feeds_do_not_keep_stale_events(self):
        self.assertEqual(self.run_build(), 0)
        for prefix in ("current", "neu-undergrad-2025-2026", "neu-undergrad-2026-2027"):
            for alias, target in build.SHORT_ALIASES.items():
                self.assertEqual((self.output / (prefix + alias + ".ics")).read_bytes(),
                                 (self.output / (prefix + target + ".ics")).read_bytes())
        self.assertEqual(ics.read((self.output / "current-quarter-calendar.ics").read_bytes().decode()), [])
        (self.output / "current-grades.ics").write_bytes((self.output / "current-faculty.ics").read_bytes())
        self.assertEqual(self.run_build("--only-latest"), 0)
        self.assertEqual(ics.read((self.output / "current-grades.ics").read_bytes().decode()), [])

    def test_only_latest_retains_archive_links_and_files(self):
        self.assertEqual(self.run_build(), 0)
        old = (self.output / "neu-undergrad-2025-2026-all.ics").read_bytes()
        self.assertEqual(self.run_build("--only-latest"), 0)
        self.assertEqual(old, (self.output / "neu-undergrad-2025-2026-all.ics").read_bytes())
        self.assertIn('href="neu-undergrad-2025-2026-all.ics"', (self.output / "index.html").read_text())

    def test_invalid_folding_in_existing_variant_is_repaired(self):
        self.assertEqual(self.run_build(), 0)
        path = self.output / "current-undergrad-deadlines.ics"
        original = path.read_bytes()
        path.write_bytes(original.replace(b"\r\n ", b""))
        with self.assertRaises(ValueError):
            ics.read(path.read_bytes().decode())
        self.assertEqual(self.run_build(), 0)
        self.assertEqual(path.read_bytes(), original)

    def test_failure_in_any_year_publishes_nothing_and_reports_error(self):
        self.assertEqual(self.run_build(), 0)
        before = snapshot(self.output)
        source = self.root / "sources"
        shutil.copytree(FIXTURES, source)
        for failing_year in ("2025-2026", "2026-2027"):
            with self.subTest(year=failing_year):
                path = source / (failing_year + ".pdf")
                original = path.read_bytes()
                path.write_bytes(b"broken")
                self.assertEqual(self.run_build(source=source), 1)
                self.assertEqual(before, snapshot(self.output))
                report = json.loads(self.report.read_text())
                self.assertEqual(report["status"], "failed")
                self.assertEqual(report["years"][failing_year]["status"], "failed")
                path.write_bytes(original)

    def test_render_failure_publishes_nothing(self):
        self.assertEqual(self.run_build(), 0)
        before = snapshot(self.output)
        with mock.patch.object(build, "render_feeds", side_effect=RuntimeError("render failed")):
            self.assertEqual(self.run_build(), 1)
        self.assertEqual(before, snapshot(self.output))

    def test_removed_feed_names_require_a_compatibility_alias(self):
        self.assertEqual(self.run_build(), 0)
        (self.output / "current-retired-name.ics").write_bytes((self.output / "current.ics").read_bytes())
        before = snapshot(self.output)
        self.assertEqual(self.run_build(), 1)
        self.assertEqual(before, snapshot(self.output))
        self.assertIn("would become stale", json.loads(self.report.read_text())["error"])

    def test_dry_run_writes_report_without_creating_feeds(self):
        self.assertEqual(self.run_build("--dry-run"), 0)
        self.assertFalse(self.output.exists())
        self.assertEqual(json.loads(self.report.read_text())["status"], "dry-run")

    def test_current_year_cannot_move_backwards(self):
        self.assertEqual(self.run_build(), 0)
        before = snapshot(self.output)
        source = self.root / "older"
        source.mkdir()
        shutil.copy(FIXTURES / "2025-2026.pdf", source / "2025-2026.pdf")
        self.assertEqual(self.run_build(source=source), 1)
        self.assertEqual(before, snapshot(self.output))
        self.assertIn("Refusing to move current feeds", json.loads(self.report.read_text())["error"])

    def test_failed_discovery_has_report_and_no_side_effect(self):
        with mock.patch.object(build.discover, "discover", side_effect=RuntimeError("source down")):
            with contextlib.redirect_stderr(io.StringIO()):
                result = build.main(["--output-dir", str(self.output), "--report", str(self.report)])
        self.assertEqual(result, 1)
        self.assertFalse(self.output.exists())
        self.assertEqual(json.loads(self.report.read_text())["error"], "source down")

    def test_invalid_report_locations_are_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as context:
            build.main(["--output-dir", str(self.output), "--report", str(self.output / "index.html")])
        self.assertEqual(context.exception.code, 2)

    def test_log_file_and_interrupt(self):
        log_file = self.root / "build.log"
        with mock.patch.object(build, "rebuild", side_effect=KeyboardInterrupt):
            self.assertEqual(self.run_build("--log-file", str(log_file)), 130)
        self.assertIn("Build interrupted", log_file.read_text())
        self.assertEqual(json.loads(self.report.read_text())["error"], "Interrupted")

    def test_index_links_work_without_javascript(self):
        self.assertEqual(self.run_build("--only-latest"), 0)
        html = (self.output / "index.html").read_text()
        self.assertIn('href="current-undergrad.ics"', html)
        self.assertIn('scope="col"', html)
        self.assertIn('scope="row"', html)
        self.assertIn(":focus-visible", html)
