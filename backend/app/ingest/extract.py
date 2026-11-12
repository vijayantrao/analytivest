"""Turn an uploaded document of (almost) any format into per-page text.

Supported: PDF (text and scanned; OCR for image-only pages), DOCX, XLSX, HTML, plain text/CSV/Markdown,
RTF, EPUB/XPS and other formats MuPDF opens, images (PNG/JPEG/TIFF/BMP/GIF/WebP via OCR), ZIP archives
containing one of these, and, as a last resort, legacy binaries such as .doc (printable-text recovery).

Everything runs locally with free libraries; nothing is sent to an external service.
For PDFs, table rows are rebuilt from word coordinates so numbers stay on the same line as their
labels, which the RHP parser relies on.
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser

log = logging.getLogger("stockiq.extract")

MAX_BYTES = 120 * 1024 * 1024
MAX_OCR_PAGES = 40
PSEUDO_PAGE_CHARS = 4000
# ZIP-based files (DOCX, XLSX, EPUB, ZIP) are checked before unpacking, so a small "zip bomb" cannot
# expand into gigabytes of memory.
MAX_UNZIPPED_BYTES = 600 * 1024 * 1024
MAX_ZIP_MEMBERS = 20000
MAX_COMPRESSION_RATIO = 150


@dataclass
class ExtractedDoc:
    pages: list[str]
    kind: str
    filename: str
    size: int
    ocr_pages: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return sum(len(p) for p in self.pages)

    def meta(self) -> dict:
        return {"filename": self.filename, "kind": self.kind, "size": self.size, "pages": len(self.pages),
                "ocr_pages": self.ocr_pages, "chars": self.char_count, "warnings": self.warnings}


class ExtractionError(Exception):
    pass


# ---------------- OCR (optional) ----------------
_ocr_engine = None
_ocr_error: str | None = None


OCR_DPI = 150  # tested: long lines with ₹ glyphs are read more reliably at 150 than at 200-300 dpi


def _ocr():
    global _ocr_engine, _ocr_error
    if _ocr_engine is None and _ocr_error is None:
        try:
            from rapidocr import RapidOCR  # PP-OCR v4/v5 models, offline
            _ocr_engine = ("v3", RapidOCR())
        except Exception as e1:  # missing package, or DLL load failure (e.g. Windows long paths)
            try:
                from rapidocr_onnxruntime import RapidOCR as LegacyOCR
                _ocr_engine = ("legacy", LegacyOCR())
            except Exception as e2:
                _ocr_error = f"{type(e1).__name__}: {e1}; legacy engine: {type(e2).__name__}: {e2}"
                log.warning("OCR unavailable: %s", _ocr_error)
    return _ocr_engine


def ocr_status() -> dict:
    return {"available": _ocr() is not None, "error": _ocr_error}


def clean_ocr_text(text: str) -> str:
    """Fix common OCR confusions inside numbers (letter O for zero, l/I for one)."""
    def fix(m):
        return m.group(0).replace("O", "0").replace("o", "0").replace("l", "1").replace("I", "1")
    return re.sub(r"(?<![A-Za-z])\d[\d,.OolI]*[\dOo](?![A-Za-z])", fix, text)


def _ocr_png(png: bytes) -> str:
    eng = _ocr()
    if eng is None:
        return ""
    kind, engine = eng
    if kind == "v3":
        r = engine(png)
        if r.txts is None or r.boxes is None:
            return ""
        items = [([tuple(p) for p in b], t) for b, t in zip(r.boxes.tolist(), r.txts)]
    else:
        res, _ = engine(png)
        items = [(b, t) for b, t, _s in (res or [])]
    if not items:
        return ""
    # Group boxes into visual rows by vertical centre, tolerant to small skew; then order each row by x.
    boxes = []
    for pts, t in items:
        ys, xs = [p[1] for p in pts], [p[0] for p in pts]
        boxes.append(((min(ys) + max(ys)) / 2, max(ys) - min(ys), min(xs), t))
    boxes.sort(key=lambda b: b[0])
    rows: list[list] = []
    for b in boxes:
        if rows and abs(b[0] - rows[-1][0][0]) < 0.5 * max(b[1], rows[-1][0][1]):
            rows[-1].append(b)
        else:
            rows.append([b])
    return clean_ocr_text("\n".join("  ".join(t for *_, t in sorted(r, key=lambda b: b[2])) for r in rows))


# ---------------- helpers ----------------
def _pseudo_pages(text: str) -> list[str]:
    text = text.replace("\r\n", "\n")
    if len(text) <= PSEUDO_PAGE_CHARS:
        return [text]
    pages, buf = [], []
    size = 0
    for line in text.split("\n"):
        buf.append(line)
        size += len(line) + 1
        if size >= PSEUDO_PAGE_CHARS:
            pages.append("\n".join(buf))
            buf, size = [], 0
    if buf:
        pages.append("\n".join(buf))
    return pages


def _rows_from_words(page) -> str:
    """Rebuild visual lines from word boxes so table cells on one row share a line."""
    words = page.get_text("words")  # x0, y0, x1, y1, word, block, line, wno
    if not words:
        return ""
    words.sort(key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    rows, cur, cur_y = [], [], None
    for w in words:
        yc = (w[1] + w[3]) / 2
        if cur_y is not None and abs(yc - cur_y) > 3.0:
            rows.append(cur)
            cur, cur_y = [], None
        cur.append(w)
        cur_y = yc if cur_y is None else (cur_y * (len(cur) - 1) + yc) / len(cur)
    if cur:
        rows.append(cur)
    out = []
    for r in rows:
        r.sort(key=lambda w: w[0])
        parts, last_x1 = [], None
        height = max(1.0, sorted(w[3] - w[1] for w in r)[len(r) // 2])
        for w in r:
            # A gap wider than ~0.6 of the text height is a column break, not a word space
            if last_x1 is not None and w[0] - last_x1 > 0.6 * height:
                parts.append("  ")  # visible column gap
            elif parts:
                parts.append(" ")
            parts.append(w[4])
            last_x1 = w[2]
        out.append("".join(parts))
    return "\n".join(out)


def _from_mupdf(data: bytes, filetype: str | None, filename: str, kind: str) -> ExtractedDoc:
    import pymupdf
    try:
        doc = pymupdf.open(stream=data, filetype=filetype) if filetype else pymupdf.open(stream=data)
    except Exception as e:
        raise ExtractionError(f"Could not open the file as {kind.upper()}: {e}") from e
    if doc.needs_pass:
        raise ExtractionError("The document is password-protected. Remove the password and upload again.")
    pages, ocr_used, skipped = [], 0, 0
    for page in doc:
        text = _rows_from_words(page)
        if len(text.strip()) < 40 and (page.get_images() or kind == "image"):
            if ocr_used < MAX_OCR_PAGES and _ocr() is not None:
                text = _ocr_png(page.get_pixmap(dpi=OCR_DPI).tobytes("png"))
                ocr_used += 1
            else:
                skipped += 1
        pages.append(text)
    out = ExtractedDoc(pages=pages, kind=kind, filename=filename, size=len(data), ocr_pages=ocr_used)
    if skipped:
        if _ocr() is None:
            out.warnings.append(f"{skipped} page(s) are images without a text layer and OCR is unavailable "
                                f"on this installation ({_ocr_error}).")
        else:
            out.warnings.append(f"{skipped} image-only page(s) beyond the first {MAX_OCR_PAGES} were not OCR'd.")
    if ocr_used:
        out.warnings.append(f"{ocr_used} page(s) were read with OCR; OCR can misread digits, so check those figures.")
    return out


class _HTMLText(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section"}

    def __init__(self):
        super().__init__()
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in ("td", "th"):
            self.out.append("  ")
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def _html_to_text(s: str) -> str:
    p = _HTMLText()
    p.feed(s)
    text = "".join(p.out)
    return re.sub(r"[ \t]*\n[ \t\n]*", "\n", text)


def _rtf_to_text(s: str) -> str:
    s = re.sub(r"\\par[d]?", "\n", s)
    s = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes.fromhex(m.group(1)).decode("cp1252", "replace"), s)
    s = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", s)
    return re.sub(r"[{}]", "", s)


def _decode_text(data: bytes) -> str | None:
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16", "replace")
    for enc in ("utf-8", "cp1252"):
        try:
            s = data.decode(enc)
        except UnicodeDecodeError:
            continue
        sample = s[:20000]
        printable = sum(1 for c in sample if c.isprintable() or c in "\n\r\t")
        if sample and printable / len(sample) > 0.95:
            return s
    return None


def _recover_strings(data: bytes) -> str:
    """Last resort for unknown binaries (e.g. legacy .doc): printable UTF-16LE and ASCII runs."""
    u16 = re.findall(rb"(?:[\x20-\x7e]\x00){5,}", data)
    a8 = re.findall(rb"[\x20-\x7e\r\n\t]{6,}", data)
    parts = [m.decode("utf-16le", "ignore") for m in u16] + [m.decode("ascii", "ignore") for m in a8]
    return "\n".join(p.strip() for p in parts if re.search(r"[A-Za-z]{3,}", p))


def check_archive(data: bytes) -> None:
    """Refuse ZIP containers whose declared contents are implausibly large or compressed."""
    if data[:4] != b"PK\x03\x04":
        return
    try:
        infos = zipfile.ZipFile(io.BytesIO(data)).infolist()
    except zipfile.BadZipFile as e:
        raise ExtractionError(f"Corrupt ZIP-based file: {e}") from e
    if len(infos) > MAX_ZIP_MEMBERS:
        raise ExtractionError("The file contains too many parts to be a normal document.")
    if sum(i.file_size for i in infos) > MAX_UNZIPPED_BYTES:
        raise ExtractionError(f"The file unpacks to more than {MAX_UNZIPPED_BYTES // (1024 * 1024)} MB.")
    for i in infos:
        if i.file_size > 10 * 1024 * 1024 and i.file_size > MAX_COMPRESSION_RATIO * max(i.compress_size, 1):
            raise ExtractionError(f"{i.filename} is compressed suspiciously tightly (possible zip bomb).")


# ---------------- entry point ----------------
def extract_text(data: bytes, filename: str = "upload", _depth: int = 0) -> ExtractedDoc:
    if not data:
        raise ExtractionError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise ExtractionError(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    name = (filename or "upload").lower()
    head = data[:16]

    if head.startswith(b"%PDF"):
        return _from_mupdf(data, "pdf", filename, "pdf")

    if head.startswith(b"PK\x03\x04"):
        if _depth > 1:
            raise ExtractionError("Archives nested inside archives are not supported.")
        check_archive(data)
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as e:
            raise ExtractionError(f"Corrupt ZIP-based file: {e}") from e
        names = z.namelist()
        if "word/document.xml" in names:
            import docx
            d = docx.Document(io.BytesIO(data))
            lines = [p.text for p in d.paragraphs]
            for t in d.tables:
                for row in t.rows:
                    lines.append("  ".join(c.text.strip() for c in row.cells))
            return ExtractedDoc(pages=_pseudo_pages("\n".join(lines)), kind="docx", filename=filename, size=len(data))
        if any(n.startswith("xl/") for n in names):
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            pages = []
            for ws in wb.worksheets:
                rows = ["  ".join("" if v is None else str(v) for v in r) for r in ws.iter_rows(values_only=True)]
                pages.extend(_pseudo_pages(f"[Sheet {ws.title}]\n" + "\n".join(rows)))
            return ExtractedDoc(pages=pages, kind="xlsx", filename=filename, size=len(data))
        if "mimetype" in names and b"epub" in z.read("mimetype"):
            return _from_mupdf(data, "epub", filename, "epub")
        # An archive holding the real document: use the largest member we can read.
        members = sorted((i for i in z.infolist() if not i.is_dir()), key=lambda i: -i.file_size)
        for m in members:
            if m.filename.lower().endswith((".pdf", ".docx", ".htm", ".html", ".txt", ".xlsx", ".rtf")):
                inner = extract_text(z.read(m), m.filename, _depth + 1)
                inner.warnings.insert(0, f"Read {m.filename} from the ZIP archive.")
                return inner
        raise ExtractionError("The ZIP archive does not contain a readable document (PDF, DOCX, HTML, TXT, XLSX).")

    if head.startswith(b"{\\rtf"):
        text = _rtf_to_text(data.decode("cp1252", "replace"))
        return ExtractedDoc(pages=_pseudo_pages(text), kind="rtf", filename=filename, size=len(data))

    image_sigs = (b"\x89PNG", b"\xff\xd8\xff", b"II*\x00", b"MM\x00*", b"GIF8", b"BM")
    if head.startswith(image_sigs) or (head[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        doc = _from_mupdf(data, None, filename, "image")
        if not doc.char_count:
            raise ExtractionError("This is an image and no text could be read from it"
                                  + (f" (OCR unavailable: {_ocr_error})" if _ocr() is None else "") + ".")
        return doc

    text = _decode_text(data)
    if text is not None:
        lowered = text[:5000].lower()
        if "<html" in lowered or "<body" in lowered or "<table" in lowered or name.endswith((".htm", ".html")):
            return ExtractedDoc(pages=_pseudo_pages(_html_to_text(text)), kind="html", filename=filename, size=len(data))
        return ExtractedDoc(pages=_pseudo_pages(text), kind="text", filename=filename, size=len(data))

    # Other formats MuPDF understands (XPS, OXPS, MOBI, FB2, CBZ, SVG...)
    try:
        doc = _from_mupdf(data, None, filename, "document")
        if doc.char_count > 200:
            return doc
    except ExtractionError:
        pass

    recovered = _recover_strings(data)
    if len(recovered) > 800 and len(re.findall(r"[A-Za-z]{3,}", recovered)) >= 100:
        out = ExtractedDoc(pages=_pseudo_pages(recovered), kind="binary-recovered", filename=filename, size=len(data))
        out.warnings.append("Unrecognised or legacy binary format (e.g. .doc): text was recovered heuristically and "
                            "tables may be scrambled. Saving the document as PDF or DOCX gives much better results.")
        return out
    raise ExtractionError("Could not read text from this file. Upload the PDF of the RHP/DRHP (as published on the "
                          "SEBI/NSE/BSE website) or a DOCX/HTML/TXT version.")
