import datetime as dt
import unittest
from unittest import mock

from icalendar import Calendar

from neucal import categorize, ics, parse

D = dt.datetime
STAMP = D(2026, 9, 1, tzinfo=dt.timezone.utc)


class TestRowEdges(unittest.TestCase):
    def test_date_variants_and_inline_description(self):
        rows = parse.parse_rows(["september 9, 2026 First day of fall classes", "SEP. 10 2026", "Fall classes continue"])
        self.assertEqual(rows, [(D(2026, 9, 9), "First day of fall classes"),
                                (D(2026, 9, 10), "Fall classes continue")])

    def test_empty_rows_and_unrecognized_dates_do_not_merge(self):
        for lines in ([], ["Date", "Event"], ["Sep 09, 2026"],
                      ["Sep 09, 2026", "Sep 10, 2026", "Some event"],
                      ["Sep 09, 2026", "Some event", "2026-09-10", "Another event"],
                      ["Feb 29, 2027", "Some event"], ["Foo 10, 2026", "Some event"],
                      ["Unexpected source layout", "Sep 09, 2026", "Some event"],
                      ["Sep 09, 2026", "bad\x00text"], ["Sep 09, 2026", "x" * 1501]):
            with self.subTest(lines=lines[:2]), self.assertRaises(parse.ParseError):
                parse.parse_rows(lines)

    def test_leap_day_and_page_break(self):
        rows = parse.parse_rows(["Feb 29, 2028", "Last day of winter classes", "Page 1 of 2",
                                 "University-Wide Academic Calendar (2027-2028)", "Date", "Event",
                                 "for this term"])
        self.assertEqual(rows, [(D(2028, 2, 29), "Last day of winter classes for this term")])

    def test_duplicate_source_rows_are_reported_and_deduplicated(self):
        with self.assertLogs("neucal.parse", "WARNING"):
            events, stats = parse.build(["Sep 09, 2026", "First day of fall classes"] * 2)
        self.assertEqual(len(events), 1)
        self.assertEqual(stats["duplicates"], 1)

    def test_scoped_span_does_not_pair_with_unscoped_marker(self):
        events = [(D(2026, 11, 1), "First day of fall break (Charlotte only)"),
                  (D(2026, 11, 5), "Fall classes resume")]
        with self.assertLogs("neucal.parse", "WARNING"):
            singles, spans = parse.collapse_spans(events)
        self.assertEqual(singles, events)
        self.assertFalse(spans)

    def test_prefixed_scoped_spans_and_out_of_order_rows(self):
        events = [(D(2026, 12, 9), "QTR: Last day of winter final exam period (if applicable)"),
                  (D(2026, 12, 3), "QTR: First day of winter final exam period (if applicable)")]
        self.assertEqual(parse.collapse_spans(events), ([], [(D(2026, 12, 3), D(2026, 12, 9),
                                                              "QTR: Winter Final Exam Period")]))

    def test_invalid_and_ambiguous_spans_fail(self):
        for rows in (
            [(D(2026, 11, 5), "First day of fall break"), (D(2026, 11, 5), "Fall classes resume")],
            [(D(2026, 11, 5), "First day of fall break"), (D(2027, 11, 10), "Fall classes resume")],
            [(D(2026, 11, 5), "First day of fall break"), (D(2026, 11, 6), "First day of fall break"),
             (D(2026, 11, 10), "Fall classes resume")],
        ):
            with self.subTest(rows=rows), self.assertRaises(parse.ParseError):
                parse.collapse_spans(rows)

    def test_title_substring_does_not_discard_a_record(self):
        rows = parse.parse_rows(["Sep 09, 2026", "First day of registration period for Academic Calendar studies"])
        self.assertEqual(len(rows), 1)


class TestClassificationEdges(unittest.TestCase):
    def test_case_whitespace_and_campus_names(self):
        cases = {
            "First day of registration period for GRADUATE students": "grad-only",
            "First day of registration period for GRADUATE and UNDERGRADUATE students": "undergrad",
            "USA: Holiday, no classes (Silicon Valley and Oakland only)": "other-campus",
            "USA: Holiday, no classes (boston and Portland only)": "undergrad",
            "USA: Holiday, no classes (Portland only)": "other-campus",
            "qtr : First day of fall classes": "quarter-calendar",
            "can : Holiday, no classes": "canada-campus",
            "USA: Faculty grade deadline for spring classes": "faculty",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(parse.audience(title), expected)

    def test_class_ends_mentioning_exams_are_classes(self):
        for qualifier in ("with", "without"):
            self.assertEqual(categorize.categorize(
                "Last day of full-semester fall classes " + qualifier + " final exams")[0], "classes")

    def test_unknown_prefix_is_not_silently_removed(self):
        self.assertEqual(categorize.categorize("XYZ: First day of full-semester fall classes")[0], "other")
        for title in ("UK: Holiday, no classes", "Holiday, no classes (London only)"):
            with self.subTest(title=title), self.assertRaises(parse.ParseError):
                parse.build(["Sep 09, 2026", title])

    def test_config_rejects_key_collisions_and_bad_bundles(self):
        categorize.validate_config()
        with mock.patch.object(categorize, "BUNDLES", categorize.BUNDLES + (categorize.BUNDLES[0],)):
            with self.assertRaises(ValueError):
                categorize.validate_config()
        with mock.patch.object(categorize, "BUNDLES", (("bad-key", "Bad", ("missing", "exams"), "Desc"),)):
            with self.assertRaises(ValueError):
                categorize.validate_config()


class TestCalendarEdges(unittest.TestCase):
    def render(self, events, **kwargs):
        return ics.render(events, kwargs.pop("name", "Test"), kwargs.pop("description", "Description"),
                          "test-ns", stamp=kwargs.pop("stamp", STAMP), **kwargs)

    def test_unicode_folding_and_metadata_escape_independent_reader(self):
        title = "é😀漢字" * 35 + ",semi;slash\\line\r\nsecond\rthird"
        event = parse.Event(D(2026, 9, 9), D(2026, 9, 12), title, "holidays", "undergrad")
        text = self.render([event], name="Name\r\nInjected:bad,;", description="A\\B;C,D\nMore")
        cal = Calendar.from_ical(text)
        self.assertEqual(str(cal["X-WR-CALNAME"]), "Name\nInjected:bad,;")
        self.assertNotIn("Injected", cal)
        self.assertEqual(str(cal["X-WR-CALDESC"]), "A\\B;C,D\nMore")
        item = cal.walk("VEVENT")[0]
        self.assertEqual(str(item["SUMMARY"]), title.replace("\r\n", "\n").replace("\r", "\n"))
        self.assertEqual(item.decoded("DTEND"), dt.date(2026, 9, 13))
        self.assertTrue(all(len(line.encode()) <= 75 for line in text.split("\r\n")))

    def test_assigned_category_overrides_title_match(self):
        text = self.render([parse.Event(D(2026, 9, 1), D(2026, 9, 1), "Final exam period", "classes", "undergrad")])
        self.assertIn("CATEGORIES:CLASS\r\n", text)

    def test_stamp_converts_to_utc(self):
        text = self.render([(D(2026, 9, 1), D(2026, 9, 1), "Holiday")],
                           stamp=D(2026, 9, 1, 20, 30, tzinfo=dt.timezone(dt.timedelta(hours=-4))))
        self.assertIn("DTSTAMP:20260902T003000Z", text)

    def test_invalid_events_and_namespace_are_rejected(self):
        good = parse.Event(D(2026, 9, 1), D(2026, 9, 1), "Holiday", "holidays", "undergrad")
        for event in (good._replace(end=D(2026, 8, 1)), good._replace(title=""),
                      good._replace(title="bad\x00text"), good._replace(start=D(2026, 9, 1, 2)),
                      good._replace(end=dt.date.max), good._replace(category="missing"),
                      good._replace(audience="missing"), good._replace(uid="bad\r\nINJECT"),
                      good._replace(sequence=-1)):
            with self.subTest(event=event), self.assertRaises(ValueError):
                self.render([event])
        with self.assertRaises(ValueError):
            ics.render([good], "name", "desc", "ns\r\nBAD", STAMP)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.render([good, good])

    def test_empty_calendar_and_date_only_values(self):
        self.assertEqual(ics.read(self.render([])), [])
        text = self.render([(dt.date(2028, 2, 29), dt.date(2028, 2, 29), "Leap day")])
        self.assertIn("DTEND;VALUE=DATE:20280301", text)

    def test_date_correction_preserves_uid_and_increments_sequence(self):
        event = parse.Event(D(2026, 9, 1), D(2026, 9, 1), "Holiday", "holidays", "undergrad")
        old = ics.read(self.render([event]))
        later = D(2026, 10, 1, tzinfo=dt.timezone.utc)
        moved = event._replace(start=D(2026, 9, 2), end=D(2026, 9, 3))
        updated = ics.reconcile([moved], old, "test-ns", later)
        self.assertEqual(updated[0].uid, old[0].uid)
        self.assertEqual(updated[0].sequence, 1)
        self.assertEqual(updated[0].modified, later)
        unchanged = ics.reconcile([moved], updated, "test-ns", D(2030, 1, 1))
        self.assertEqual(unchanged, updated)

    def test_ambiguous_title_does_not_guess_identity(self):
        events = [parse.Event(D(2026, 9, day), D(2026, 9, day), "Holiday", "holidays", "undergrad")
                  for day in (1, 2)]
        old = ics.read(self.render(events))
        moved = events[0]._replace(start=D(2026, 9, 3), end=D(2026, 9, 3))
        reconciled = ics.reconcile([moved, events[1]], old, "test-ns", STAMP)
        self.assertNotIn(reconciled[0].uid, [event.uid for event in old])
        self.assertEqual(reconciled[1].uid, old[1].uid)

    def test_validator_rejects_corrupted_content(self):
        text = self.render([(D(2026, 9, 1), D(2026, 9, 1), "Holiday")])
        for broken in (text.replace("\r\n", "\n"), text.replace("VERSION:2.0", "VERSION:3.0"),
                       text.replace("DTEND;VALUE=DATE:20260902", "DTEND;VALUE=DATE:20260901"),
                       text.replace("SUMMARY:Holiday", "SUMMARY:"), text.replace("UID:", "BAD:"),
                       text.replace("END:VEVENT", ""), text.replace("BEGIN:VEVENT", "BEGIN:VEVENT\r\nBEGIN:VEVENT"),
                       text.replace("SUMMARY:Holiday", "SUMMARY:" + "x" * 80),
                       text.replace("SUMMARY:Holiday", "SUMMARY:Holiday\r\nSUMMARY:Duplicate")):
            with self.subTest(broken=broken[:80]), self.assertRaises(ValueError):
                ics.read(broken)
