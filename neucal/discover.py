"""Discover calendar links and download bounded, verified responses."""

import http.client
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

LOG = logging.getLogger(__name__)
HOST = "registrar.northeastern.edu"
INDEX_PAGES = (
    "https://registrar.northeastern.edu/article/academic-calendar/",
    "https://registrar.northeastern.edu/article/past-calendars/",
)
EARLIEST_SUPPORTED = "2025-2026"
USER_AGENT = "neu-academic-calendar-ics (+https://github.com/Alitleis123/neu-academic-calendar-ics)"
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
PDF_RE = re.compile(r"^(\d{4})-(\d{4})-Academic-Calendar(?:-[\w-]+)?\.pdf$", re.I)


class SourceError(RuntimeError):
    """A source could not be fetched or identified reliably."""


def year_start(year):
    match = re.fullmatch(r"(\d{4})-(\d{4})", year)
    if not match or int(match[2]) != int(match[1]) + 1 or not 1900 <= int(match[1]) <= 9997:
        raise ValueError("Invalid academic year {!r}; expected consecutive YYYY-YYYY".format(year))
    return int(match[1])


def _validate_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        valid = (parsed.scheme == "https" and parsed.hostname == HOST
                 and parsed.port in (None, 443) and not parsed.username
                 and not parsed.password and not any(ord(c) < 33 for c in url))
    except ValueError as exc:
        raise SourceError("Invalid source URL {!r}".format(url)) from exc
    if not valid:
        raise SourceError("Expected an HTTPS URL on {}: {!r}".format(HOST, url))
    return parsed


class _RegistrarRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _retry_delay(header, attempt):
    try:
        delay = float(header)
    except (TypeError, ValueError):
        try:
            delay = (parsedate_to_datetime(header) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            delay = 2 ** (attempt - 1)
    return max(0, min(delay, 20))


def fetch(url, *, attempts=3, timeout=30, max_bytes=MAX_DOWNLOAD_BYTES):
    """Fetch trusted HTTPS with bounded size, timeout and transient retries.

    Redirects stay on the registrar host. Permanent HTTP errors and invalid
    responses fail immediately; timeouts, truncated transfers and 429/5xx retry.
    """
    _validate_url(url)
    if attempts < 1 or timeout <= 0 or max_bytes < 1:
        raise ValueError("attempts, timeout and max_bytes must be positive")
    opener = urllib.request.build_opener(_RegistrarRedirect())
    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        retry_after = None
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                      "Accept-Encoding": "identity"})
            with opener.open(req, timeout=timeout) as response:
                _validate_url(response.geturl())
                if response.status != 200:
                    raise SourceError("Unexpected HTTP {} for {}".format(response.status, url))
                length = response.headers.get("Content-Length")
                if length is not None:
                    try:
                        length = int(length)
                    except ValueError as exc:
                        raise SourceError("Invalid Content-Length for " + url) from exc
                    if length < 0 or length > max_bytes:
                        raise SourceError("Response exceeds {} bytes: {}".format(max_bytes, url))
                chunks, size = [], 0
                while size <= max_bytes:
                    if time.monotonic() - started > timeout:
                        raise TimeoutError("Download exceeded {} seconds".format(timeout))
                    chunk = response.read1(min(65536, max_bytes + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                data = b"".join(chunks)
                if len(data) > max_bytes:
                    raise SourceError("Response exceeds {} bytes: {}".format(max_bytes, url))
                if length is not None and len(data) != length:
                    raise http.client.IncompleteRead(data, max(0, length - len(data)))
                if not data:
                    raise SourceError("Empty response from " + url)
                content_type = response.headers.get_content_type()
                is_pdf = urllib.parse.urlsplit(url).path.lower().endswith(".pdf")
                if is_pdf and not data.startswith(b"%PDF-"):
                    raise SourceError("Expected PDF bytes, received {} from {}".format(content_type, url))
                if not is_pdf and content_type not in ("text/html", "application/xhtml+xml"):
                    raise SourceError("Expected HTML, received {} from {}".format(content_type, url))
                LOG.info("Downloaded %s bytes=%d elapsed=%.2fs attempt=%d",
                         url, len(data), time.monotonic() - started, attempt)
                return data
        except urllib.error.HTTPError as exc:
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            error = "HTTP {}".format(exc.code)
            exc.close()
            if exc.code != 429 and not 500 <= exc.code < 600:
                raise SourceError("{} fetching {}".format(error, url)) from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                http.client.HTTPException, OSError) as exc:
            error = str(exc)
        if attempt == attempts:
            raise SourceError("Failed fetching {} after {} attempts: {}".format(url, attempts, error))
        delay = _retry_delay(retry_after, attempt)
        LOG.warning("Fetch failed url=%s attempt=%d/%d error=%s retry_in=%.1fs",
                    url, attempt, attempts, error, delay)
        time.sleep(delay)
    raise AssertionError("unreachable")


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self.urls.extend(value for key, value in attrs if key == "href" and value)


def links(html, page):
    """Read actual anchors, supporting relative paths, query strings and entities."""
    parser = _Links()
    parser.feed(html)
    found = {}
    for href in parser.urls:
        url = urllib.parse.urljoin(page, href.strip())
        parsed = urllib.parse.urlsplit(url)
        match = PDF_RE.fullmatch(urllib.parse.unquote(parsed.path).rsplit("/", 1)[-1])
        if not match:
            continue
        _validate_url(url)
        year = "{}-{}".format(match[1], match[2])
        year_start(year)
        if year < EARLIEST_SUPPORTED:
            continue
        url = urllib.parse.urlunsplit(parsed._replace(fragment=""))
        if year in found and found[year] != url:
            raise SourceError("Conflicting PDF links for {} on {}".format(year, page))
        found[year] = url
    return found


def discover(*, only_latest=False):
    """Return supported years, failing if a requested index cannot be read.

    The current page is authoritative. Never fall back to an archive when it
    fails, because that could move subscribers back to an older year.
    """
    found = {}
    pages = INDEX_PAGES[:1] if only_latest else INDEX_PAGES
    for page in pages:
        try:
            page_links = links(fetch(page).decode("utf-8-sig"), page)
        except (UnicodeError, ValueError, SourceError) as exc:
            raise SourceError("Discovery failed on {}: {}".format(page, exc)) from exc
        if not page_links:
            raise SourceError("No supported calendar PDFs on {}; check the page layout".format(page))
        LOG.info("Discovered %s years=%s", page, ",".join(sorted(page_links)))
        for year, url in page_links.items():
            if year in found and found[year] != url:
                LOG.warning("Archive has a different %s URL; using the current page's link", year)
            found.setdefault(year, url)
    return dict(sorted(found.items()))


def latest(found):
    if not found:
        raise SourceError("No academic calendars to select")
    return max(found, key=year_start)
