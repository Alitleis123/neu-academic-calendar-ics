import datetime as dt
import io
import unittest
import urllib.error
from email.message import Message
from unittest import mock

from neucal import discover

PAGE = discover.INDEX_PAGES[0]
PDF_URL = "https://registrar.northeastern.edu/uploads/2026-2027-Academic-Calendar.pdf"
HTML = '<a href="/uploads/2026-2027-Academic-Calendar.pdf">Calendar</a>'


class Response(io.BytesIO):
    def __init__(self, data=b"%PDF-test", *, url=PDF_URL, length=None, content_type="application/pdf", status=200):
        super().__init__(data)
        self.url = url
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        if length is not None:
            self.headers["Content-Length"] = str(length)

    def geturl(self):
        return self.url


class TestDiscovery(unittest.TestCase):
    def test_links_handle_variants_and_ignore_nonanchors(self):
        html = '''<!-- /uploads/2029-2030-Academic-Calendar.pdf -->
        <script>"/uploads/2028-2029-Academic-Calendar.pdf"</script>
        <A HREF='/wp-content/uploads/2026/09/2026-2027-Academic-Calendar.PDF?v=2&amp;x=3#p1'>new</A>
        <a href='//registrar.northeastern.edu/uploads/2025-2026-Academic-Calendar.pdf'>old</a>
        <a href='/uploads/2024-2025-Academic-Calendar.pdf'>unsupported</a>'''
        result = discover.links(html, PAGE)
        self.assertEqual(set(result), {"2025-2026", "2026-2027"})
        self.assertTrue(result["2026-2027"].endswith(".PDF?v=2&x=3"))

    def test_revision_suffix_and_relative_path(self):
        result = discover.links('<a href="2026-2027-Academic-Calendar-revised.pdf">x</a>', PAGE)
        self.assertEqual(result["2026-2027"], PAGE + "2026-2027-Academic-Calendar-revised.pdf")

    def test_ambiguous_and_invalid_links_fail(self):
        invalid = [
            HTML + HTML.replace("/uploads/", "/elsewhere/"),
            HTML.replace("2026-2027", "2026-2028"),
            HTML.replace("/uploads/", "https://evil.example/"),
        ]
        for html in invalid:
            with self.subTest(html=html), self.assertRaises((ValueError, discover.SourceError)):
                discover.links(html, PAGE)

    def test_current_page_is_required(self):
        with mock.patch.object(discover, "fetch", side_effect=discover.SourceError("offline")) as fetch:
            with self.assertRaisesRegex(discover.SourceError, "Discovery failed"):
                discover.discover()
            self.assertEqual(fetch.call_count, 1)

    def test_archive_failure_is_visible(self):
        with mock.patch.object(discover, "fetch", side_effect=[HTML.encode(), discover.SourceError("offline")]):
            with self.assertRaisesRegex(discover.SourceError, "offline"):
                discover.discover()

    def test_only_latest_does_not_need_archive(self):
        with mock.patch.object(discover, "fetch", return_value=HTML.encode()) as fetch:
            self.assertEqual(discover.discover(only_latest=True), {"2026-2027": PDF_URL})
            fetch.assert_called_once_with(PAGE)

    def test_authoritative_link_wins_with_warning(self):
        with mock.patch.object(discover, "fetch", side_effect=[HTML.encode(), HTML.replace("/uploads/", "/old/").encode()]):
            with self.assertLogs("neucal.discover", "WARNING"):
                self.assertEqual(discover.discover()["2026-2027"], PDF_URL)

    def test_no_supported_links_and_invalid_encoding_fail(self):
        for data in (b"<html>no links</html>", b"\xff\xfe"):
            with mock.patch.object(discover, "fetch", return_value=data), self.assertRaises(discover.SourceError):
                discover.discover()

    def test_years(self):
        self.assertEqual(discover.latest({"2025-2026": "x", "2026-2027": "y"}), "2026-2027")
        with self.assertRaises(discover.SourceError):
            discover.latest({})
        for year in ("2027-2026", "2025-2027", "oops", "0000-0001", "9999-10000"):
            with self.subTest(year=year), self.assertRaises(ValueError):
                discover.year_start(year)


class TestFetch(unittest.TestCase):
    def setUp(self):
        self.opener = mock.Mock()
        self.build_opener = mock.patch.object(discover.urllib.request, "build_opener", return_value=self.opener)
        self.build_opener.start()
        self.addCleanup(self.build_opener.stop)
        self.sleep = mock.patch.object(discover.time, "sleep")
        self.sleeper = self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def test_valid_pdf_and_html(self):
        self.opener.open.return_value = Response(length=9)
        self.assertEqual(discover.fetch(PDF_URL), b"%PDF-test")
        request = self.opener.open.call_args.args[0]
        self.assertEqual(request.get_header("User-agent"), discover.USER_AGENT)
        self.opener.open.return_value = Response(b"<html/>", url=PAGE, content_type="text/html")
        self.assertEqual(discover.fetch(PAGE), b"<html/>")

    def test_retries_transient_failure(self):
        self.opener.open.side_effect = [TimeoutError("timeout"), Response()]
        with self.assertLogs("neucal.discover", "WARNING"):
            self.assertEqual(discover.fetch(PDF_URL), b"%PDF-test")
        self.sleeper.assert_called_once_with(1)

    def test_download_has_a_total_time_budget(self):
        self.opener.open.return_value = Response()
        with mock.patch.object(discover.time, "monotonic", side_effect=[0, 31]):
            with self.assertRaisesRegex(discover.SourceError, "Download exceeded"):
                discover.fetch(PDF_URL, attempts=1, timeout=30)

    def test_retry_after_and_exhaustion(self):
        headers = Message()
        headers["Retry-After"] = "999"
        def unavailable(*args, **kwargs):
            raise urllib.error.HTTPError(PDF_URL, 429, "slow down", headers, None)
        self.opener.open.side_effect = unavailable
        with self.assertLogs("neucal.discover", "WARNING"), self.assertRaisesRegex(discover.SourceError, "after 3 attempts"):
            discover.fetch(PDF_URL)
        self.assertEqual(self.sleeper.call_args_list, [mock.call(20), mock.call(20)])

    def test_404_does_not_retry(self):
        self.opener.open.side_effect = urllib.error.HTTPError(PDF_URL, 404, "missing", {}, None)
        with self.assertRaisesRegex(discover.SourceError, "404"):
            discover.fetch(PDF_URL)
        self.sleeper.assert_not_called()

    def test_bad_responses_fail(self):
        for response in (
            Response(b"<html>blocked</html>"), Response(b""), Response(length=30_000_000),
            Response(length="bad"), Response(url="http://registrar.northeastern.edu/x.pdf"),
            Response(b"json", url=PAGE, content_type="application/json"), Response(status=206),
        ):
            self.opener.open.return_value = response
            with self.subTest(response=response), self.assertRaises(discover.SourceError):
                discover.fetch(PDF_URL if response.url != PAGE else PAGE)

    def test_size_without_length_and_truncated_transfer(self):
        self.opener.open.return_value = Response()
        with self.assertRaisesRegex(discover.SourceError, "exceeds"):
            discover.fetch(PDF_URL, max_bytes=5)
        self.opener.open.side_effect = [Response(length=100), Response()]
        with self.assertLogs("neucal.discover", "WARNING"):
            self.assertEqual(discover.fetch(PDF_URL), b"%PDF-test")

    def test_untrusted_urls_and_invalid_options(self):
        for url in ("file:///etc/passwd", "http://registrar.northeastern.edu/x", "https://evil.example/x",
                    "https://user@registrar.northeastern.edu/x", "https://registrar.northeastern.edu:bad/x"):
            with self.subTest(url=url), self.assertRaises(discover.SourceError):
                discover.fetch(url)
        with self.assertRaises(ValueError):
            discover.fetch(PDF_URL, attempts=0)
        self.opener.open.assert_not_called()

    def test_redirect_is_checked_before_contacting_host(self):
        with self.assertRaises(discover.SourceError):
            discover._RegistrarRedirect().redirect_request(None, None, 302, "", {}, "https://evil.example/x")

    def test_retry_date_and_bad_value(self):
        future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=1)
        self.assertEqual(discover._retry_delay(future.strftime("%a, %d %b %Y %H:%M:%S GMT"), 1), 20)
        self.assertEqual(discover._retry_delay("bad", 3), 4)
