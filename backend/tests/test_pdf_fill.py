"""services/pdf_fill – {{marker}} in AcroForm-Feldwerten füllen (PDF-Gegenstück
zu docx_fill). Baut eine minimale AcroForm-PDF als Fixture (kein externes File)."""
from pypdf import PdfReader
import io

from backend.services import pdf_fill, template_format


def _acroform_pdf(fields: list[tuple[str, str]]) -> bytes:
    """Minimale AcroForm-PDF mit Textfeldern (name, value). Zusammengesetzt inkl.
    xref, damit pypdf sie ohne Rekonstruktion liest."""
    n = len(fields)
    refs = " ".join(f"{4 + i} 0 R" for i in range(n))
    parts = {
        1: f"<< /Type /Catalog /Pages 2 0 R /AcroForm << /Fields [{refs}] /NeedAppearances true >> >>",
        2: "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Annots [{refs}] >>",
    }
    for i, (nm, val) in enumerate(fields):
        v = val.replace("(", r"\(").replace(")", r"\)")
        y = 350 - i * 40
        parts[4 + i] = (f"<< /Type /Annot /Subtype /Widget /FT /Tx /T ({nm}) "
                        f"/V ({v}) /Rect [50 {y} 250 {y + 30}] /P 3 0 R >>")
    order = [1, 2, 3] + [4 + i for i in range(n)]
    out = b"%PDF-1.4\n"
    off: dict[int, int] = {}
    for oid in order:
        off[oid] = len(out)
        out += f"{oid} 0 obj\n{parts[oid]}\nendobj\n".encode("latin1")
    xref_pos = len(out)
    mx = max(order)
    out += f"xref\n0 {mx + 1}\n".encode() + b"0000000000 65535 f \n"
    for oid in range(1, mx + 1):
        out += f"{off[oid]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {mx + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF".encode()
    return out


def _values(pdf: bytes) -> dict:
    return {k: v.get("/V") for k, v in (PdfReader(io.BytesIO(pdf)).get_fields() or {}).items()}


def test_detect_pdf_vs_docx():
    assert template_format.detect(b"%PDF-1.7\n...") == "pdf"
    assert template_format.detect(b"PK\x03\x04....") == "docx"
    assert template_format.detect(b"") == "docx"


def test_find_placeholders_in_field_values():
    pdf = _acroform_pdf([("f1", "{{firma}}"), ("f2", "{{vorname}} {{nachname}}"),
                         ("f3", "ohne marker")])
    assert pdf_fill.find_placeholders(pdf) == ["firma", "vorname", "nachname"]


def test_fill_substitutes_and_leaves_unmarked_fields():
    pdf = _acroform_pdf([("f1", "{{firma}}"), ("f2", "{{vorname}} {{nachname}}"),
                         ("f3", "ohne marker")])
    out = pdf_fill.fill_pdf(pdf, {"firma": "ACME", "vorname": "Max", "nachname": "Muster"})
    vals = _values(out)
    assert vals["f1"] == "ACME"
    assert vals["f2"] == "Max Muster"
    assert vals["f3"] == "ohne marker"                 # kein Marker → unverändert
    assert template_format.detect(out) == "pdf"


def test_fill_unbound_marker_becomes_gap():
    pdf = _acroform_pdf([("f1", "{{firma}}")])
    out = pdf_fill.fill_pdf(pdf, {})                    # firma nicht belegt
    assert _values(out)["f1"] == pdf_fill.GAP
