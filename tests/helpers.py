import io
import pathlib

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def pdf_bytes(contents, *, compress=False, reverse=False, encrypted=False):
    """Build real PDFs so tests exercise extraction through the public boundary."""
    writer = PdfWriter()
    pages = []
    for content in contents:
        page = writer.add_blank_page(width=612, height=792)
        stream = DecodedStreamObject()
        stream.set_data(content)
        if compress:
            stream = stream.flate_encode()
        page[NameObject("/Contents")] = writer._add_object(stream)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
            NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
        })
        pages.append(page)
    if reverse:
        writer.get_object(writer._pages)["/Kids"].reverse()
    if encrypted:
        writer.encrypt("test-password")
    data = io.BytesIO()
    writer.write(data)
    return data.getvalue()


def text_pdf(text):
    return pdf_bytes([b"BT /F1 12 Tf 14 TL 50 700 Td (" + text + b") Tj ET"])
