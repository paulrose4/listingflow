"""Read-only bounded extraction. Every omission is represented as a coverage gap."""

import hashlib
import io
import json
import posixpath
import re
import warnings
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

SUPPORTED = {".xlsx", ".docx", ".pdf", ".png", ".jpg", ".jpeg"}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def xml(data):
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("DTD/entity XML is not accepted")
    return ET.fromstring(data)


def tag(element):
    return element.tag.rsplit("}", 1)[-1]


def archive(path, limits):
    z = zipfile.ZipFile(path)
    total = sum(i.file_size for i in z.infolist())
    if total > limits["expanded_bytes"] or len(z.infolist()) > 10000:
        z.close()
        raise ValueError("Archive expanded size/member limit exceeded")
    if any(i.flag_bits & 1 for i in z.infolist()):
        z.close()
        raise ValueError("Encrypted archive is unsupported")
    return z


def extract(path, target, limits):
    path, target = Path(path), Path(target)
    target.mkdir(parents=True, exist_ok=True)
    result = {"units": [], "gaps": [], "format": path.suffix.lower()}

    def unit(locator, text="", kind="text", **extra):
        item = {"locator": locator, "text": str(text), "kind": kind, **extra}
        result["units"].append(item)
        return item

    def gap(locator, reason):
        result["gaps"].append({"locator": locator, "reason": reason})

    def image(data, locator):
        from PIL import Image
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as im:
                width, height = im.size
                if width * height > limits["image_pixels"]:
                    raise ValueError("Image pixel limit exceeded")
                im.verify()
        digest = hashlib.sha256(data).hexdigest()
        dest = target / (digest + ".image")
        if not dest.exists():
            dest.write_bytes(data)
        unit(locator, kind="image", visual_path=str(dest.resolve()),
             width=width, height=height, sha256=digest)
        gap(locator, "Visual text, graphical marks and source suitability require inspection")

    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        from openpyxl import load_workbook
        from openpyxl.utils.cell import coordinate_to_tuple
        with archive(path, limits) as z:
            bounds = {}
            total_cells = 0
            for name in z.namelist():
                if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name):
                    cells = [e for e in xml(z.read(name)).iter() if tag(e) == "c"
                             and any(tag(c) in {"v", "f", "is"} for c in e)]
                    total_cells += len(cells)
                    coords = [coordinate_to_tuple(c.attrib["r"]) for c in cells]
                    bounds[name] = (max((c[0] for c in coords), default=0),
                                    max((c[1] for c in coords), default=0))
            if total_cells > limits["xml_cells"]:
                raise ValueError("Occupied-cell limit exceeded; no range was silently truncated")
            rels = {e.attrib["Id"]: e.attrib["Target"]
                    for e in xml(z.read("xl/_rels/workbook.xml.rels"))}
            sheet_xml = {}
            for e in xml(z.read("xl/workbook.xml")).iter():
                if tag(e) == "sheet":
                    rid = next(v for k, v in e.attrib.items() if k.endswith("}id"))
                    target_name = rels[rid]
                    sheet_xml[e.attrib["name"]] = (target_name.lstrip("/") if target_name.startswith("/")
                                                  else posixpath.normpath("xl/" + target_name))
            wb = load_workbook(path, read_only=True, data_only=False, keep_links=False)
            cached = load_workbook(path, read_only=True, data_only=True, keep_links=False)
            try:
                for sheet in wb:
                    rows, cols = bounds.get(sheet_xml[sheet.title], (0, 0))
                    locator = f"sheet:{sheet.title}"
                    if rows * cols > limits["grid_cells"]:
                        gap(locator, f"Occupied bounding rectangle {rows}x{cols} exceeds grid limit; not read")
                        continue
                    unit(locator, kind="sheet", rows=rows, columns=cols, visibility=sheet.sheet_state)
                    if not rows:
                        continue
                    values = cached[sheet.title].iter_rows(max_row=rows, max_col=cols)
                    for row, cache_row in zip(sheet.iter_rows(max_row=rows, max_col=cols), values):
                        for cell, cv in zip(row, cache_row):
                            if cell.value is None:
                                continue
                            loc = f"{locator}!{cell.coordinate}"
                            if cell.data_type == "f":
                                unit(loc, "" if cv.value is None else cv.value, formula=cell.value,
                                     cached_value=cv.value, number_format=cell.number_format, cell_type="formula")
                                gap(loc, "Formula cache may be missing/stale; formulas and external links never executed")
                            else:
                                value = cell.value
                                shown = (str(int(value)).zfill(len(cell.number_format))
                                         if isinstance(value, (int, float)) and not isinstance(value, bool)
                                         and float(value).is_integer() and re.fullmatch(r"0+", cell.number_format)
                                         else str(value))
                                unit(loc, shown, raw_value=value if isinstance(value, (str, int, float, bool)) else str(value),
                                     number_format=cell.number_format, cell_type=cell.data_type)
            finally:
                wb.close()
                cached.close()
            for name in z.namelist():
                if name.startswith("xl/media/"):
                    try:
                        image(z.read(name), f"embedded:{name}")
                    except Exception as exc:
                        gap(f"embedded:{name}", f"Image extraction failed: {exc}")
                if re.fullmatch(r"xl/drawings/drawing\d+\.xml", name):
                    unit(f"drawing:{name}", z.read(name).decode("utf-8"), kind="image_placement")
                if re.fullmatch(r"xl/(drawings|worksheets)/_rels/.*\.rels", name):
                    unit(f"relationships:{name}", z.read(name).decode("utf-8"), kind="image_placement")
                if "externalLink" in name or name.endswith("vbaProject.bin"):
                    gap(name, "External content/macros are not executed or followed")
    elif suffix == ".docx":
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
        with archive(path, limits) as z:
            for name in z.namelist():
                if name.endswith(".xml"):
                    xml(z.read(name))
            doc = Document(path)

            def blocks(parent, prefix):
                for index, block in enumerate(parent.iter_inner_content(), 1):
                    loc = f"{prefix}/{index}"
                    if isinstance(block, Paragraph):
                        if block.text:
                            unit(loc, block.text)
                    elif isinstance(block, Table):
                        for r, row in enumerate(block.rows, 1):
                            for c, cell in enumerate(row.cells, 1):
                                blocks(cell, f"{loc}/table/R{r}C{c}")

            blocks(doc, "body")
            for name in z.namelist():
                if re.fullmatch(r"word/(header\d+|footer\d+|footnotes|endnotes|comments)\.xml", name):
                    root = xml(z.read(name))
                    for index, p in enumerate((e for e in root.iter() if tag(e) == "p"), 1):
                        text = "".join(e.text or "" for e in p.iter() if tag(e) == "t")
                        if text:
                            unit(f"{name}/paragraph:{index}", text, kind="auxiliary")
                if name.startswith("word/media/"):
                    try:
                        image(z.read(name), f"embedded:{name}")
                    except Exception as exc:
                        gap(f"embedded:{name}", f"Image extraction failed: {exc}")
                if name == "word/_rels/document.xml.rels":
                    unit(f"relationships:{name}", z.read(name).decode("utf-8"), kind="image_placement")
            docxml = xml(z.read("word/document.xml"))
            for index, e in enumerate(docxml.iter(), 1):
                if tag(e) in {"blip", "imagedata"}:
                    unit(f"body/xml-node:{index}", json.dumps(e.attrib), kind="image_placement")
                if tag(e) in {"txbxContent", "ins", "del", "altChunk", "object"}:
                    gap(f"body/xml-node:{index}", f"{tag(e)} needs visual/version interpretation")
    elif suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(path, strict=False)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDF is unsupported")
        if len(reader.pages) > limits["pdf_pages"]:
            raise ValueError("PDF page limit exceeded; no pages silently omitted")
        for index, page in enumerate(reader.pages, 1):
            loc = f"page:{index}"
            unit(loc, page.extract_text() or "", kind="pdf_page")
            gap(loc, "Page graphics/layout and text completeness need visual inspection or justified exclusion")
    elif suffix in {".png", ".jpg", ".jpeg"}:
        image(path.read_bytes(), "image:1")
    else:
        raise ValueError(f"Unsupported file type: {suffix}")
    result["status"] = "PARTIAL" if result["gaps"] else "SUCCESS"
    return result


def render_pdf(path, page, dest, max_pixels=40000000):
    import pypdfium2 as pdfium
    with pdfium.PdfDocument(str(path)) as doc:
        if page < 1 or page > len(doc):
            raise ValueError("Page number outside document")
        pdfpage = doc[page - 1]
        try:
            width, height = pdfpage.get_size()
            scale = min(2.0, (max_pixels / max(width * height, 1)) ** 0.5)
            bitmap = pdfpage.render(scale=scale)
            try:
                bitmap.to_pil().save(str(dest), format="PNG")
            finally:
                bitmap.close()
        finally:
            pdfpage.close()


if __name__ == "__main__":
    import sys
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    try:
        payload = extract(request["path"], request["target"], request["limits"])
    except Exception as error:
        payload = {"status": "FAILED", "units": [], "gaps": [
            {"locator": "file", "reason": f"{type(error).__name__}: {error}"}]}
    Path(sys.argv[2]).write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
