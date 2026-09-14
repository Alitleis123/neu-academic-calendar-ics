import datetime as dt
import sys
import pathlib
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from neucal import ics, parse


class TestParseRows(unittest.TestCase):
    def test_joins_wrapped_descriptions(self):
        rows = parse.parse_rows([
            "Date", "Event",
            "Sep 09, 2026", "First day of full-semester,", "Session A fall classes",
            "Sep 22, 2026", "Last day of add/drop period",
        ])
        self.assertEqual(rows, [
            (dt.datetime(2026, 9, 9), "First day of full-semester, Session A fall classes"),
            (dt.datetime(2026, 9, 22), "Last day of add/drop period"),
        ])

    def test_drops_headers_and_page_furniture(self):
        rows = parse.parse_rows(
            ["University-Wide Academic Calendar (2026-2027) - Fall - Page 1 of 1",
             "Date", "Event", "Sep 09, 2026", "Classes begin"])
        self.assertEqual(len(rows), 1)


class TestExclusion(unittest.TestCase):
    def test_excluded(self):
        for text, reason in [
            ("First day of first-year JD fall classes for School of Law", "law"),
            ("First day of Fall registration period for new and continuing Law students", "law"),
            ("CAN: Labour Day, no classes", "canada-campus"),
            ("CAN: Truth and Reconciliation Day, no classes (Vancouver only)", "canada-campus"),
            ("USA: Good Friday, no classes (Charlotte only)", "other-campus"),
            ("Faculty grade deadline for Session A fall classes at 2:00", "faculty"),
            ("First day of spring registration period for new graduate students", "grad-only"),
            ("First day of Fall registration period for ABSN Students", "other-program"),
        ]:
            self.assertEqual(parse.exclusion_reason(text), reason, text)

    def test_kept(self):
        for text in [
            "Last day of add/drop period for full-semester fall classes",
            "USA: Labor Day, no classes",
            "USA: Patriots Day, no classes (Boston and Portland only)",
            "First day of spring registration period for undergraduate students",
            # mentions graduate but also undergraduate -> keep
            "First day of summer registration period for continuing graduate students "
            "and undergraduate students",
        ]:
            self.assertIsNone(parse.exclusion_reason(text), text)

    def test_undergraduate_not_matched_as_graduate(self):
        self.assertIsNone(parse.exclusion_reason(
            "First day of fall registration period for continuing undergraduate students"))


class TestSpans(unittest.TestCase):
    def test_break_span_ends_day_before_resume(self):
        events = [(dt.datetime(2026, 11, 25), "First day of fall break"),
                  (dt.datetime(2026, 11, 30), "Fall classes resume")]
        singles, spans = parse.collapse_spans(events)
        self.assertEqual(singles, [])
        self.assertEqual(spans, [(dt.datetime(2026, 11, 25),
                                  dt.datetime(2026, 11, 29), "Fall Break")])

    def test_exam_span_is_inclusive(self):
        events = [(dt.datetime(2026, 12, 14), "First day of fall final exam period (if applicable)"),
                  (dt.datetime(2026, 12, 20), "Last day of fall final exam period (if applicable)")]
        _, spans = parse.collapse_spans(events)
        self.assertEqual(spans, [(dt.datetime(2026, 12, 14),
                                  dt.datetime(2026, 12, 20), "Fall Final Exam Period")])

    def test_terms_do_not_cross_match(self):
        events = [(dt.datetime(2026, 11, 25), "First day of fall break"),
                  (dt.datetime(2027, 3, 15), "Spring classes resume")]
        singles, spans = parse.collapse_spans(events)
        self.assertEqual(spans, [])
        self.assertEqual(len(singles), 2)


class TestICS(unittest.TestCase):
    def setUp(self):
        self.text = ics.render(
            [(dt.datetime(2026, 9, 9), dt.datetime(2026, 9, 9), "Classes begin, for real"),
             (dt.datetime(2026, 11, 25), dt.datetime(2026, 11, 29), "Fall Break")],
            "Test", "Desc", "test-ns", stamp=dt.datetime(2026, 1, 1))

    def test_structure_and_crlf(self):
        self.assertTrue(self.text.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertTrue(self.text.rstrip().endswith("END:VCALENDAR"))
        self.assertEqual(self.text.count("BEGIN:VEVENT"), 2)
        self.assertNotIn("\n", self.text.replace("\r\n", ""))

    def test_dtend_is_exclusive(self):
        self.assertIn("DTSTART;VALUE=DATE:20260909\r\nDTEND;VALUE=DATE:20260910", self.text)
        self.assertIn("DTSTART;VALUE=DATE:20261125\r\nDTEND;VALUE=DATE:20261130", self.text)

    def test_commas_escaped(self):
        self.assertIn(r"SUMMARY:Classes begin\, for real", self.text)

    def test_lines_folded_to_75_octets(self):
        long = ics.render([(dt.datetime(2026, 9, 9), dt.datetime(2026, 9, 9), "x" * 200)],
                          "n", "d", "ns", stamp=dt.datetime(2026, 1, 1))
        self.assertTrue(all(len(l.encode()) <= 75 for l in long.split("\r\n")))

    def test_uid_stable_across_runs(self):
        again = ics.render(
            [(dt.datetime(2026, 9, 9), dt.datetime(2026, 9, 9), "Classes begin, for real"),
             (dt.datetime(2026, 11, 25), dt.datetime(2026, 11, 29), "Fall Break")],
            "Test", "Desc", "test-ns", stamp=dt.datetime(2030, 6, 6))
        uids = lambda t: [l for l in t.split("\r\n") if l.startswith("UID:")]
        self.assertEqual(uids(self.text), uids(again))


if __name__ == "__main__":
    unittest.main()
