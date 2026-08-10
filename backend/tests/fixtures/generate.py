"""Synthetic fixture generators with known ground truth.

These build documents whose contents we control exactly, so extraction accuracy,
routing, and integrity checks can be asserted automatically without any real
(sensitive) financial statements. reportlab/openpyxl are dev-only dependencies.
"""
from __future__ import annotations

import io


def make_native_pdf(title: str = "Balance Sheet") -> bytes:
    """A single-page native (text-layer) PDF containing a small balance sheet."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    y = height - 72
    c.setFont("Helvetica-Bold", 14)
    c.drawString(72, y, title)
    c.setFont("Helvetica", 10)
    rows = [
        ("Cash and cash equivalents", "Note 14", "1,204"),
        ("Trade receivables", "Note 15", "3,410"),
        ("Property, plant and equipment", "Note 5", "12,800"),
        ("Total assets", "", "17,414"),
    ]
    for label, note, value in rows:
        y -= 24
        c.drawString(72, y, label)
        c.drawString(320, y, note)
        c.drawRightString(500, y, value)
    c.showPage()
    c.save()
    return buf.getvalue()


def make_dual_basis_pdf() -> bytes:
    """A native PDF whose columns are a two-level Consolidated | Standalone header, each with
    a current + prior period — for testing consolidated+standalone extraction in one pass."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _, height = A4
    y = height - 72
    c.setFont("Helvetica-Bold", 13)
    c.drawString(72, y, "Balance Sheet")
    # Two-level column header: Consolidated over cols ~300/370, Standalone over ~440/510.
    c.setFont("Helvetica-Bold", 9)
    y -= 22
    c.drawString(300, y, "Consolidated")
    c.drawString(445, y, "Standalone")
    c.setFont("Helvetica", 9)
    y -= 14
    c.drawRightString(330, y, "2025")
    c.drawRightString(400, y, "2024")
    c.drawRightString(475, y, "2025")
    c.drawRightString(545, y, "2024")
    c.setFont("Helvetica", 10)
    rows = [
        ("Trade receivables", ("3,410", "2,900", "3,100", "2,700")),
        ("Cash and cash equivalents", ("1,204", "980", "1,050", "900")),
    ]
    for label, (cc, cp, sc, sp) in rows:
        y -= 22
        c.drawString(72, y, label)
        c.drawRightString(330, y, cc)
        c.drawRightString(400, y, cp)
        c.drawRightString(475, y, sc)
        c.drawRightString(545, y, sp)
    c.showPage()
    c.save()
    return buf.getvalue()


def make_rich_pdf() -> bytes:
    """A fuller native PDF: BS totals + P&L headline + a notes page with qualitative
    disclosures — so derived ratios, the disclosure scan, and free-form notes all populate."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _, height = A4

    def rows(items, y):
        c.setFont("Helvetica", 10)
        for label, cur, pri in items:
            c.drawString(72, y, label)
            c.drawRightString(430, y, cur)
            c.drawRightString(510, y, pri)
            y -= 22
        return y

    c.setFont("Helvetica-Bold", 13); c.drawString(72, height - 60, "Balance Sheet")
    y = rows([
        ("Inventories", "2,000", "1,800"),
        ("Trade receivables", "3,410", "2,900"),
        ("Cash and cash equivalents", "1,204", "980"),
        ("Total current assets", "6,614", "5,680"),
        ("Total current liabilities", "3,300", "3,100"),
        ("Total non-current liabilities", "1,200", "1,400"),
        ("Total equity", "9,114", "7,180"),
        ("Total assets", "13,614", "11,680"),
    ], height - 90)
    c.showPage()

    c.setFont("Helvetica-Bold", 13); c.drawString(72, height - 60, "Statement of Profit or Loss")
    rows([
        ("Revenue from operations", "20,000", "18,000"),
        ("Operating profit", "3,200", "2,700"),
        ("Profit for the year", "2,400", "1,950"),
    ], height - 90)
    c.showPage()

    c.setFont("Helvetica-Bold", 12); c.drawString(72, height - 60, "Notes to the Financial Statements")
    c.setFont("Helvetica", 9)
    for i, line in enumerate([
        "The auditor has issued a qualified opinion in respect of inventory valuation.",
        "Contingent liabilities: the Group is subject to legal proceedings estimated at 500.",
        "The Company has provided financial guarantees to subsidiaries totalling 1,200.",
        "Related party transactions with associates are disclosed in note 28.",
        "Subsequent events: a dividend was declared after the reporting period.",
    ]):
        c.drawString(72, height - 90 - i * 18, line)
    c.showPage()
    c.save()
    return buf.getvalue()


def make_multipage_pdf() -> bytes:
    """A 2-page native PDF: face on page 0, notes on page 1."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    c.setFont("Helvetica-Bold", 14)
    c.drawString(72, height - 72, "Statement of Financial Position")
    c.setFont("Helvetica", 10)
    c.drawString(72, height - 100, "Cash and cash equivalents      Note 14      1,204")
    c.showPage()

    c.setFont("Helvetica-Bold", 14)
    c.drawString(72, height - 72, "Notes to the Financial Statements")
    c.setFont("Helvetica", 10)
    c.drawString(72, height - 100, "Note 14: Cash and cash equivalents")
    c.drawString(72, height - 120, "Cash on hand      204")
    c.drawString(72, height - 140, "Balances with banks      1,000")
    c.showPage()
    c.save()
    return buf.getvalue()


def make_annual_report_pdf() -> bytes:
    """A realistic HKEX/IFRS-shaped annual report: cover, an auditor's report (which mentions
    face phrases in prose), three *consolidated* face statements, then a notes section that
    opens WITHOUT a 'Notes to…' banner — straight into '1 General information' — followed by a
    numbered continuation note that also mentions 'profit or loss' in prose. Ground truth:
    the three statement pages are FACE, the auditor page is not FACE, and the two note pages
    are NOTES (so their tables are extracted, not skipped)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _, height = A4

    def page(title, body_lines, title_size=14):
        c.setFont("Helvetica-Bold", title_size)
        c.drawString(72, height - 72, title)
        c.setFont("Helvetica", 10)
        y = height - 104
        for ln in body_lines:
            c.drawString(72, y, ln); y -= 20
        c.showPage()

    # 0: cover / contents (OTHER)
    page("Annual Report 2024", ["Contents", "Corporate information", "Chairman's statement"])
    # 1: independent auditor's report — prose mentions "profit or loss" / "cash flows" but is
    #    NOT a statement face (and precedes the statements).
    page("Independent Auditor's Report", [
        "In our opinion the consolidated financial statements give a true and fair view.",
        "We audited the statement of profit or loss and the statement of cash flows.",
        "Key audit matters were addressed in forming our opinion."])
    # 2-4: the three consolidated face statements (FACE)
    page("Consolidated Statement of Profit or Loss", [
        "Revenue      Note 5      45,230",
        "Cost of sales      (28,110)",
        "Profit for the year      6,120"])
    page("Consolidated Statement of Financial Position", [
        "Property, plant and equipment      Note 12      88,400",
        "Trade receivables      Note 15      12,300",
        "Cash and cash equivalents      Note 18      9,870",
        "Total assets      143,900"])
    page("Consolidated Statement of Cash Flows", [
        "Net cash from operating activities      14,200",
        "Net cash used in investing activities      (9,100)"])
    # 5: notes section opens with a numbered heading, NO 'Notes to…' banner (exercises the
    #    'first numbered note after the face statements' start rule).
    page("1 General information", [
        "The Company is incorporated in the Cayman Islands with limited liability.",
        "Its shares are listed on The Stock Exchange of Hong Kong Limited."])
    # 6: a numbered continuation note that mentions a face phrase in prose (must stay NOTES).
    page("18 Cash and cash equivalents", [
        "Cash at banks and on hand      9,870",
        "Amounts are measured at amortised cost; see the statement of profit or loss for interest.",
        "Short-term deposits      2,400"])
    c.save()
    return buf.getvalue()


def make_xlsx() -> bytes:
    """A workbook with a negative-number format and a hidden sheet."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Balance Sheet"
    ws["A1"] = "Cash and cash equivalents"
    ws["B1"] = 1204
    ws["A2"] = "Accumulated depreciation"
    ws["B2"] = -500
    ws["B2"].number_format = "#,##0;(#,##0)"

    hidden = wb.create_sheet("Working")
    hidden.sheet_state = "hidden"
    hidden["A1"] = "scratch"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
