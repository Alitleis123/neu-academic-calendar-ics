import hashlib
import json
import unittest
from unittest import mock

from helpers import FIXTURES, pdf_bytes, text_pdf

from neucal import parse, pdf
from neucal.validate import check


class TestPDF(unittest.TestCase):
    def test_timezone_inside_string_is_not_an_operator(self):
        data = text_pdf(b"Faculty grade deadline at 2:00 p.m. ET for School of Law")
        self.assertEqual(pdf.to_lines(data), ["Faculty grade deadline at 2:00 p.m. ET for School of Law"])

    def test_uncompressed_and_compressed_text_and_wraps(self):
        for compress in (False, True):
            data = pdf_bytes([b"BT /F1 12 Tf 14 TL 50 700 Td (I Am Here for) Tj T* (full-semester) Tj ET"],
                             compress=compress)
            self.assertEqual(" ".join(pdf.to_lines(data)), "I Am Here for full-semester")

    def test_literal_escapes_and_hex_strings(self):
        data = pdf_bytes([rb"BT /F1 12 Tf 14 TL 50 700 Td (A \(B\) \134n \101) Tj T* <436166e9> Tj ET"])
        self.assertEqual(pdf.to_lines(data), [r"A (B) \n A", "Café"])

    def test_page_tree_order_not_stream_order(self):
        contents = [b"BT /F1 12 Tf (first) Tj ET", b"BT /F1 12 Tf (second) Tj ET"]
        self.assertEqual(pdf.to_lines(pdf_bytes(contents, reverse=True)), ["second", "first"])

    def test_invalid_truncated_and_encrypted(self):
        for data in (b"", b"<html>error</html>", text_pdf(b"valid")[:-10],
                     b"%PDF-1.4\nmalformed\n%%EOF", pdf_bytes([b"BT (x) Tj ET"], encrypted=True)):
            with self.subTest(data=data[:30]), self.assertRaises(pdf.PdfError):
                pdf.to_lines(data)

    def test_one_blank_page_does_not_silently_disappear(self):
        data = pdf_bytes([b"BT /F1 12 Tf (visible) Tj ET", b"q Q"])
        with self.assertRaisesRegex(pdf.PdfError, "Page 2 has no text"):
            pdf.to_lines(data)

    def test_resource_limits(self):
        data = text_pdf(b"Some text")
        for limit in ("MAX_PAGES", "MAX_PAGE_BYTES", "MAX_TEXT_CHARS", "MAX_DOWNLOAD_BYTES"):
            with self.subTest(limit=limit), mock.patch.object(pdf, limit, 1), self.assertRaises(pdf.PdfError):
                pdf.to_lines(data if limit != "MAX_PAGES" else pdf_bytes([b"x", b"x"]))

    def test_decompression_limit(self):
        data = pdf_bytes([b" " * (pdf.MAX_PAGE_BYTES + 1)], compress=True)
        with self.assertRaises(pdf.PdfError):
            pdf.to_lines(data)


class TestSourceFixtures(unittest.TestCase):
    def test_source_checksums_and_complete_counts(self):
        metadata = json.loads((FIXTURES / "sources.json").read_text())
        for year, row_count, event_count, ug_count, spans in (
            ("2025-2026", 269, 259, 120, 10), ("2026-2027", 164, 159, 121, 5)
        ):
            with self.subTest(year=year):
                raw = (FIXTURES / (year + ".pdf")).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), metadata[year]["sha256"])
                events, stats = parse.build(pdf.to_lines(raw))
                check(events, year)
                self.assertEqual(stats["parsed"], row_count)
                self.assertEqual(len(events), event_count)
                self.assertEqual(stats["audiences"]["undergrad"], ug_count)
                self.assertEqual(stats["collapsed"], spans)
                self.assertEqual(stats["categories"]["classes"], 30)
                self.assertEqual(stats["categories"]["exams"], 3)

    def test_all_39_grade_descriptions_keep_timezone(self):
        grade_events = []
        for year in ("2025-2026", "2026-2027"):
            events, _ = parse.build(pdf.to_lines((FIXTURES / (year + ".pdf")).read_bytes()))
            grade_events.extend(event for event in events if event.category == "grades")
        self.assertEqual(len(grade_events), 39)
        self.assertTrue(all(event.title.endswith("at 2:00 p.m. ET") for event in grade_events))
        law = [event for event in grade_events if event.audience == "law"]
        self.assertEqual(len(law), 6)

    def test_quarter_spans_and_summer_endpoints(self):
        events, _ = parse.build(pdf.to_lines((FIXTURES / "2025-2026.pdf").read_bytes()))
        spans = {event.title: event for event in events if event.end > event.start}
        self.assertEqual(len([title for title in spans if title.startswith("QTR:")]), 5)
        self.assertEqual(str(spans["QTR: Winter Final Exam Period"].end.date()), "2026-03-29")
        self.assertEqual(str(spans["QTR: Summer Final Exam Period"].end.date()), "2026-08-30")
        self.assertEqual(str(spans["QTR: Fall Break"].end.date()), "2025-11-30")
