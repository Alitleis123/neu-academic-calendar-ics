"""Extract calendar text in PDF page order, rejecting incomplete documents."""

import io
import logging

from pypdf import PdfReader, apply_configuration

from .discover import MAX_DOWNLOAD_BYTES

LOG = logging.getLogger(__name__)
MAX_PAGES = 40
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 500_000


class PdfError(RuntimeError):
    """A PDF is malformed, too large, or has an unreadable page."""


@apply_configuration(
    maximum_declared_stream_length=MAX_PAGE_BYTES,
    array_based_stream_maximum_output_length=MAX_PAGE_BYTES,
    zlib_maximum_output_length=MAX_PAGE_BYTES,
    lzw_maximum_output_length=MAX_PAGE_BYTES,
    run_length_maximum_output_length=MAX_PAGE_BYTES,
    page_tree_maximum_entries=200,
    page_tree_maximum_depth=10,
    xform_maximum_invocations_per_extraction=100,
    jbig2dec_binary=None,
)
def to_lines(data):
    """Read each page with a real PDF tokenizer and font decoding.

    The timezone text 'ET' inside a PDF string must never be mistaken for the
    end-text operator, which truncated deadlines in the original regex reader.
    """
    if not data.startswith(b"%PDF-") or len(data) > MAX_DOWNLOAD_BYTES:
        raise PdfError("Expected a PDF no larger than {} bytes".format(MAX_DOWNLOAD_BYTES))
    if not data.rstrip().endswith(b"%%EOF"):
        raise PdfError("PDF is truncated: missing final %%EOF marker")
    lines = []
    chars = 0
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise PdfError("Encrypted PDFs are not supported")
        if not 1 <= len(reader.pages) <= MAX_PAGES:
            raise PdfError("Expected 1-{} pages, got {}".format(MAX_PAGES, len(reader.pages)))
        for number, page in enumerate(reader.pages, 1):
            contents = page.get_contents()
            if contents is None or len(contents.get_data()) > MAX_PAGE_BYTES:
                raise PdfError("Page {} has missing or oversized content".format(number))
            text = page.extract_text()
            if not text or not text.strip():
                raise PdfError("Page {} has no text; scanned calendars need a different parser".format(number))
            if "\ufffd" in text or "\x00" in text:
                raise PdfError("Page {} contains undecodable text".format(number))
            chars += len(text)
            if chars > MAX_TEXT_CHARS:
                raise PdfError("Extracted text exceeds {} characters".format(MAX_TEXT_CHARS))
            page_lines = [line.strip() for line in text.splitlines() if line.strip()]
            lines.extend(page_lines)
            LOG.debug("Extracted PDF page=%d lines=%d chars=%d", number, len(page_lines), len(text))
    except PdfError:
        raise
    except Exception as exc:
        raise PdfError("PDF extraction failed: {}".format(exc)) from exc
    LOG.info("Extracted PDF pages=%d lines=%d chars=%d", len(reader.pages), len(lines), chars)
    return lines
