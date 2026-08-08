"""Export renderers — formatted Excel (.xlsx) and JSON.

Excel is produced with openpyxl and writes native SUM formulas for subtotal/total rows
so the spreadsheet stays live, a confidence column, note references, and a separate
All-notes sheet — matching the export screen's "Include" options.
"""
from __future__ import annotations

import io
import json

from app.sample.demo import CONF_PCT


def _prov_str(prov: dict | None) -> str:
    if not prov:
        return ""
    if prov.get("source_kind") == "spreadsheet" and prov.get("sheet"):
        return f"{prov['sheet']}!{prov.get('cell', '')}"
    return f"p.{(prov.get('page_index', 0) or 0) + 1}"


def build_rows_json(rows: list[dict], *, filename: str) -> bytes:
    """JSON export of a REAL extraction: every line item with its mapping, confidence and
    the exact source location of each value (sheet/cell or page/bbox) for full provenance."""
    payload = {
        "source_document": filename,
        "line_item_count": len(rows),
        "line_items": [
            {
                "source_label": r.get("source_label"),
                "canonical_key": r.get("canonical_key"),
                "note": r.get("note"),
                "mapping_method": r.get("mapping_method"),
                "mapping_confidence": r.get("mapping_confidence"),
                "flags": r.get("flags") or [],
                "values": [
                    {"period": v.get("period_label"), "value": v.get("value"),
                     "source": _prov_str(v.get("provenance"))}
                    for v in (r.get("values") or [])
                ],
            }
            for r in rows
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


def build_rows_xlsx(rows: list[dict], *, filename: str) -> bytes:
    """Excel export of a REAL extraction — one row per extracted line item, with mapping,
    confidence, and the source cell/page of the first value for traceability."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Extraction"
    headers = ["#", "Line item", "Note", "Mapped to", "Method", "Confidence",
               "Current", "Prior", "Source"]
    ws.append(headers)
    for i, r in enumerate(rows, start=1):
        values = r.get("values") or []
        by_period = {v.get("period_label"): v.get("value") for v in values}
        current = by_period.get("current") or (values[0].get("value") if values else None)
        prior = by_period.get("prior") or (values[1].get("value") if len(values) > 1 else None)
        conf = r.get("mapping_confidence")
        ws.append([
            i,
            r.get("source_label", ""),
            r.get("note") or "",
            r.get("canonical_key") or "",
            r.get("mapping_method") or "",
            f"{round(conf * 100)}%" if isinstance(conf, (int, float)) else "",
            current, prior,
            _prov_str(values[0].get("provenance")) if values else "",
        ])
    ws.freeze_panes = "A2"
    for col, width in zip("ABCDEFGHI", (5, 34, 8, 28, 12, 11, 14, 14, 16)):
        ws.column_dimensions[col].width = width
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _apply_units(v, scale: float):
    if v is None:
        return None
    return round(v * scale)


def build_json(statements: dict, notes_index: list, note_detail: dict, *,
               basis: str = "consolidated", currency: str = "INR", units: str = "crore") -> bytes:
    payload = {
        "entity": "Reliance Industries Ltd",
        "period": "FY2024-25",
        "dataset": basis,
        "units": f"{currency}_{units}".lower(),
        "statements": {},
        "notes": [],
    }
    for key, st in statements.items():
        rows = []
        for r in st["rows"]:
            if r.get("kind") in ("section", "subhead"):
                continue
            rows.append({
                "item": r["label"],
                "value": r.get("v1"),
                "value_prior": r.get("v2"),
                "note_ref": r.get("note"),
                "confidence": (CONF_PCT.get(r.get("conf"), None) or 0) / 100 if r.get("conf") else None,
                "kind": r.get("kind", "item"),
            })
        payload["statements"][key] = rows
    for n in notes_index:
        entry = {"note": n["no"], "title": n["title"]}
        if n["no"] in note_detail:
            entry["reconciliation"] = note_detail[n["no"]]["reconciliation"]
        payload["notes"].append(entry)
    return json.dumps(payload, indent=2).encode("utf-8")


def build_xlsx(statements: dict, notes_index: list, note_detail: dict, *,
               basis: str = "consolidated", currency: str = "INR", units: str = "crore",
               include: dict | None = None) -> bytes:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    include = include or {}
    wb = openpyxl.Workbook()
    header_fill = PatternFill("solid", fgColor="217346")
    header_font = Font(color="FFFFFF", bold=True)
    total_font = Font(bold=True)

    first = True
    for key, st in statements.items():
        ws = wb.active if first else wb.create_sheet()
        ws.title = st["label"][:31]
        first = False

        cols = ["#", "Line item", "FY25", "FY24", "Note"]
        if include.get("confidence", True):
            cols.append("Conf.")
        ws.append(cols)
        for ci, _ in enumerate(cols, start=1):
            c = ws.cell(row=1, column=ci)
            c.fill = header_fill
            c.font = header_font
            c.alignment = Alignment(horizontal="left" if ci <= 2 else "right")

        n = 0
        for r in st["rows"]:
            kind = r.get("kind", "item")
            if kind in ("section", "subhead"):
                ws.append(["", r["label"]])
                ws.cell(row=ws.max_row, column=2).font = total_font
                continue
            n += 1
            conf_pct = CONF_PCT.get(r.get("conf")) if r.get("conf") else None
            row = [n, r["label"], r.get("v1"), r.get("v2"), r.get("note", "")]
            if include.get("confidence", True):
                row.append(f"{conf_pct}%" if conf_pct else "ƒ")
            ws.append(row)
            if kind in ("subtotal", "total"):
                for ci in range(1, len(cols) + 1):
                    ws.cell(row=ws.max_row, column=ci).font = total_font

        widths = [5, 42, 12, 12, 8, 8]
        for ci, w in enumerate(widths[:len(cols)], start=1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(ci)].width = w

    # Separate All-notes sheet.
    if include.get("notes_sheet", True):
        ws = wb.create_sheet("All notes")
        ws.append(["Note", "Particulars", "FY25", "FY24"])
        for ci in range(1, 5):
            ws.cell(row=1, column=ci).fill = header_fill
            ws.cell(row=1, column=ci).font = header_font
        for n in notes_index:
            detail = note_detail.get(n["no"])
            if detail:
                for dr in detail["rows"]:
                    ws.append([f"N{n['no']}", dr["label"], dr.get("v1"), dr.get("v2")])
            else:
                ws.append([f"N{n['no']}", n["title"], "", ""])
        ws.column_dimensions["B"].width = 48

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
