"""Minimal PDF text extraction.

The registrar's PDFs are Flate-compressed PDF 1.4 with plain text operators, so
a dependency-free reader is enough — this avoids requiring poppler or PyPDF in
CI. It is deliberately narrow: it understands only what these files use.
"""

import base64
import re
import zlib

_OCTAL = re.compile(rb"\\([0-7]{1,3})")
# Text chunks, plus the operators that move to a new line. T* must be matched
# separately: a trailing \b cannot follow "*", which is not a word character.
_TOKEN = re.compile(rb"\((?:[^()\\]|\\.)*\)|\bT[dD]\b|T\*")
_TEXT_OBJ = re.compile(rb"BT(.*?)ET", re.S)
_STREAM = re.compile(rb"stream\r?\n")

_ESCAPES = {
    rb"\n": b"\n", rb"\r": b"\r", rb"\t": b"\t",
    rb"\(": b"(", rb"\)": b")", rb"\\": b"\\",
}


def _inflate(raw):
    for attempt in (
        lambda b: zlib.decompress(b),
        lambda b: zlib.decompress(b, -15),
        lambda b: zlib.decompress(base64.a85decode(b.strip().rstrip(b"~>"), adobe=False)),
    ):
        try:
            return attempt(raw)
        except Exception:
            continue
    return None


def _unescape(s):
    s = _OCTAL.sub(lambda m: bytes([int(m.group(1), 8)]), s)
    for k, v in _ESCAPES.items():
        s = s.replace(k, v)
    return s


def to_lines(data):
    """Extract text from a PDF as a list of lines, in page order."""
    lines = []
    for m in _STREAM.finditer(data):
        start = m.end()
        end = data.find(b"endstream", start)
        if end == -1:
            continue
        content = _inflate(data[start:end])
        if not content:
            continue
        for obj in _TEXT_OBJ.finditer(content):
            parts = []
            for t in _TOKEN.finditer(obj.group(1)):
                tok = t.group(0)
                if tok.startswith(b"("):
                    parts.append(_unescape(tok[1:-1]).decode("cp1252", "replace"))
                else:
                    parts.append(" ")          # positioning op = line break
            line = re.sub(r"\s+", " ", "".join(parts)).strip()
            if line:
                lines.append(line)
    if not lines:
        raise RuntimeError("No text extracted from PDF — format may have changed.")
    return lines
