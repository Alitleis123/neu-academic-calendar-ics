import datetime as dt
import sys
import pathlib
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from neucal import categorize, ics, parse, pdf


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


class TestQuarterCalendar(unittest.TestCase):
    def test_qtr_rows_excluded(self):
        self.assertEqual(
            parse.exclusion_reason("QTR: First day of full-quarter fall classes"),
            "quarter-calendar")


class TestPdfTokens(unittest.TestCase):
    def test_next_line_operator_is_matched(self):
        """T* marks a line break; a trailing \\b cannot follow '*', so it needs
        its own alternative. Missing it glued words together across wraps."""
        found = [m.group(0) for m in pdf._TOKEN.finditer(b"(for) T* (full-semester)")]
        self.assertIn(b"T*", found)

    def test_wrapped_text_gets_a_space(self):
        lines = []
        content = b"BT (I Am Here for) T* (full-semester) ET"
        import re as _re
        for obj in _re.finditer(rb"BT(.*?)ET", content, _re.S):
            parts = []
            for t in pdf._TOKEN.finditer(obj.group(1)):
                tok = t.group(0)
                parts.append(tok[1:-1].decode() if tok.startswith(b"(") else " ")
            lines.append(_re.sub(r"\s+", " ", "".join(parts)).strip())
        self.assertEqual(lines, ["I Am Here for full-semester"])


class TestAudience(unittest.TestCase):
    def test_audiences(self):
        for text, key in [
            ("First day of first-year JD fall classes for School of Law", "law"),
            ("CAN: Labour Day, no classes", "canada-campus"),
            ("QTR: First day of full-quarter fall classes", "quarter-calendar"),
            ("USA: Good Friday, no classes (Charlotte only)", "other-campus"),
            ("Faculty grade deadline for Session A fall classes at 2:00", "faculty"),
            ("First day of spring registration for new graduate students", "grad-only"),
            ("First day of Fall registration period for ABSN Students", "other-program"),
            ("Last day of add/drop period for full-semester fall classes", "undergrad"),
            ("USA: Patriots Day, no classes (Boston and Portland only)", "undergrad"),
        ]:
            self.assertEqual(parse.audience(text), key, text)

    def test_nothing_is_discarded(self):
        """Every row lands in some audience — the tree has no hole."""
        for text in ["anything at all", "CAN: x", "Faculty grade deadline for y"]:
            self.assertIn(parse.audience(text), parse.categorize.audience_keys())


class TestCategorize(unittest.TestCase):
    def test_known_categories(self):
        for title, key in [
            ("First day of I Am Here for full-semester fall classes", "attendance"),
            ("Last day of add/drop period for full-semester fall classes", "deadlines"),
            ("Last day of withdrawal period for Session A fall classes", "deadlines"),
            ("Fall Final Exam Period", "exams"),
            ("USA: Labor Day, no classes", "holidays"),
            ("Fall Break", "holidays"),
            ("First day of spring registration period for undergraduate students", "registration"),
            ("First day of full-semester fall classes", "classes"),
            ("Fall degree conferral", "admin"),
            ("Spring class schedule available", "admin"),
        ]:
            self.assertEqual(categorize.categorize(title)[0], key, title)

    def test_attendance_wins_over_classes(self):
        """'I Am Here' rows also mention classes; order must favour attendance."""
        self.assertEqual(categorize.categorize(
            "Last day of I Am Here for full-semester fall classes")[0], "attendance")

    def test_essentials_are_real_categories(self):
        for key in categorize.ESSENTIALS:
            self.assertIn(key, categorize.keys())

    def test_audience_prefix_does_not_defeat_anchors(self):
        """A 'QTR: ' / 'CAN: ' prefix sits before ^-anchored patterns."""
        self.assertEqual(categorize.categorize(
            "QTR: First day of full-quarter fall classes")[0], "classes")

    def test_grade_deadlines_have_a_category(self):
        self.assertEqual(categorize.categorize(
            "Faculty grade deadline for initial-third fall classes at 2:00")[0], "grades")

    def test_unpaired_resume_row_is_a_holiday(self):
        self.assertEqual(categorize.categorize("QTR: Fall classes resume")[0], "holidays")

    def test_ics_value_is_uppercase(self):
        self.assertEqual(categorize.categorize("Fall Break")[1], "HOLIDAY")


if __name__ == "__main__":
    unittest.main()
