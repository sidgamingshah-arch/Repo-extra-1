"""Export renderers — formatted Excel (.xlsx) and JSON.

Excel is produced with openpyxl and writes native SUM formulas for subtotal/total rows
so the spreadsheet stays live, a confidence column, note references, and a separate
All-notes sheet — matching the export screen's "Include" options.
"""
from __future__ import annotations

import io
import json

from app.sample.demo import CONF_PCT

# Statement titles for the formatted export, localized like the rest of the app. Line-item
# labels come from the TEMPLATE's label_i18n, so the export is fully template-driven.
_STMT_TITLE = {
    "balance_sheet": {"en": "Balance Sheet", "zh": "资产负债表", "ar": "الميزانية العمومية",
                      "fr": "Bilan"},
    "profit_and_loss": {"en": "Profit & Loss", "zh": "利润表", "ar": "الأرباح والخسائر",
                        "fr": "Compte de résultat"},
    "cash_flow": {"en": "Cash Flow", "zh": "现金流量表", "ar": "التدفقات النقدية",
                  "fr": "Flux de trésorerie"},
}
_STMT_SHEET = {"balance_sheet": "Balance Sheet", "profit_and_loss": "Profit & Loss",
               "cash_flow": "Cash Flow"}
_BASIS_LABEL = {
    "consolidated": {"en": "Consolidated", "zh": "合并", "ar": "موحّد", "fr": "Consolidé"},
    "standalone": {"en": "Standalone", "zh": "单独", "ar": "مستقل", "fr": "Individuel"},
}
_COL = {
    "Line item": {"zh": "项目", "ar": "البند", "fr": "Poste"},
    "Note": {"zh": "附注", "ar": "إيضاح", "fr": "Note"},
    "Current": {"zh": "本期", "ar": "الحالية", "fr": "Actuel"},
    "Prior": {"zh": "上期", "ar": "السابقة", "fr": "Précédent"},
    "Conf": {"zh": "置信度", "ar": "الثقة", "fr": "Conf."},
    "Source": {"zh": "来源", "ar": "المصدر", "fr": "Source"},
}


def _col(term: str, locale: str) -> str:
    return term if locale == "en" else _COL.get(term, {}).get(locale, term)


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


# ---------------------------------------------------------------------------
# Formatted statement export — mirrors the TEMPLATE's structure (sections,
# subtotals, totals, ordering, localized labels) with consolidated + standalone
# side by side. Driven entirely by the template, so any template of the same
# schema produces the same high-quality output.
# ---------------------------------------------------------------------------
def _label(node: dict, locale: str) -> str:
    return (node.get("label_i18n") or {}).get(locale) or node.get("label") or node.get("canonical_key") or ""


def _cell_value(row: dict | None, basis: str, period: str):
    if not row:
        return None
    for v in row.get("values") or []:
        if (v.get("basis") or "consolidated") == basis and v.get("period_label") == period:
            return _num(v.get("value"))
    return None


def _num(s):
    if s is None:
        return None
    try:
        return float(str(s).replace(",", ""))
    except ValueError:
        return None


def _bases_present(rows: list[dict]) -> list[str]:
    found = {(v.get("basis") or "consolidated") for r in rows for v in (r.get("values") or [])}
    return [b for b in ("consolidated", "standalone") if b in found] or ["consolidated"]


def build_statement_workbook(rows: list[dict], template_def: dict, *, locale: str = "en",
                             filename: str = "") -> bytes:
    """A formatted, statement-shaped workbook: one sheet per statement in the template, with
    its sections / subtotals / totals, localized line labels, and consolidated + standalone
    columns side by side. Purely template-driven — the same code renders any template."""
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    by_key = {r["canonical_key"]: r for r in rows if r.get("canonical_key")}
    bases = _bases_present(rows)

    ink = "1f2937"
    section_fill = PatternFill("solid", fgColor="EEF1F6")
    total_fill = PatternFill("solid", fgColor="E7ECF5")
    band_fill = PatternFill("solid", fgColor="243044")
    thin_top = Border(top=Side(style="thin", color="9AA4B2"))
    dbl_top = Border(top=Side(style="double", color="6B7686"))
    right = Alignment(horizontal="right")
    num_fmt = "#,##0;(#,##0)"

    # Column layout: Line item | Note | [basis × (Current, Prior)] | Conf | Source
    period_cols = [(b, p) for b in bases for p in ("current", "prior")]
    n_val = len(period_cols)
    first_val = 3                                   # col C
    conf_col = first_val + n_val
    src_col = conf_col + 1
    last_col = src_col

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    statements = [s for s in template_def.get("statements", []) if s.get("type")]

    any_sheet = False
    for stmt in statements:
        stype = stmt.get("type")
        # Which of this statement's keys were actually extracted?
        stmt_keys = _statement_keys(stmt)
        if not (stmt_keys & set(by_key)):
            continue
        any_sheet = True
        ws = wb.create_sheet(_STMT_SHEET.get(stype, stype)[:31])

        ws.cell(1, 1, filename).font = Font(size=9, color="8A94A6")
        ws.cell(2, 1, _STMT_TITLE.get(stype, {}).get(locale, stype)).font = Font(bold=True, size=13, color=ink)

        # Header band (row 4: basis groups; row 5: column names).
        hb, hc = 4, 5
        ws.cell(hb, 1, filename and "" or "")
        for idx, b in enumerate(bases):
            c0 = first_val + idx * 2
            cell = ws.cell(hb, c0, _BASIS_LABEL[b][locale] if b in _BASIS_LABEL else b)
            cell.font = Font(bold=True, color="FFFFFF"); cell.alignment = Alignment(horizontal="center")
            cell.fill = band_fill
            ws.merge_cells(start_row=hb, start_column=c0, end_row=hb, end_column=c0 + 1)
            ws.cell(hb, c0 + 1).fill = band_fill
        for col, name in [(1, "Line item"), (2, "Note"), (conf_col, "Conf"), (src_col, "Source")]:
            hcell = ws.cell(hc, col, _col(name, locale)); hcell.font = Font(bold=True, size=9, color="5A6472")
        for (b, p) in period_cols:
            ci = first_val + period_cols.index((b, p))
            hcell = ws.cell(hc, ci, _col("Current" if p == "current" else "Prior", locale))
            hcell.font = Font(bold=True, size=9, color="5A6472"); hcell.alignment = right

        r = hc + 1
        r = _emit_nodes(ws, stmt.get("sections", []), by_key, period_cols, first_val, conf_col,
                        src_col, locale, r, section_fill, total_fill, thin_top, dbl_top, right,
                        num_fmt, ink)

        ws.freeze_panes = ws.cell(hc + 1, 1)
        ws.column_dimensions["A"].width = 46
        ws.column_dimensions["B"].width = 7
        for i in range(n_val):
            ws.column_dimensions[get_column_letter(first_val + i)].width = 14
        ws.column_dimensions[get_column_letter(conf_col)].width = 7
        ws.column_dimensions[get_column_letter(src_col)].width = 16

    if not any_sheet:                                # nothing extracted → a friendly stub sheet
        ws = wb.create_sheet("Extraction")
        ws.cell(1, 1, "No extracted line items for this document.")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _statement_keys(stmt: dict) -> set[str]:
    keys: set[str] = set()

    def walk(nodes):
        for n in nodes:
            if n.get("canonical_key"):
                keys.add(n["canonical_key"])
            walk(n.get("children", []))

    walk(stmt.get("sections", []))
    return keys


def _emit_nodes(ws, nodes, by_key, period_cols, first_val, conf_col, src_col, locale, r,
                section_fill, total_fill, thin_top, dbl_top, right, num_fmt, ink):
    from openpyxl.styles import Alignment, Font

    for node in nodes:
        role = node.get("role")
        key = node.get("canonical_key")
        row = by_key.get(key)
        label = _label(node, locale)

        if role == "header":
            children = node.get("children", [])
            # Skip whole sections with nothing extracted, to keep the statement readable.
            if not any(c.get("canonical_key") in by_key for c in children):
                continue
            hc = ws.cell(r, 1, label)
            hc.font = Font(bold=True, color=ink)
            for c in range(1, src_col + 1):
                ws.cell(r, c).fill = section_fill
            r += 1
            # Show extracted lines + structural subtotals/totals.
            for child in children:
                if child.get("canonical_key") in by_key or child.get("role") in ("subtotal", "total"):
                    r = _emit_nodes(ws, [child], by_key, period_cols, first_val, conf_col, src_col,
                                    locale, r, section_fill, total_fill, thin_top, dbl_top, right,
                                    num_fmt, ink)
            continue

        is_bold = role in ("subtotal", "total")
        lab = ws.cell(r, 1, label)
        lab.font = Font(bold=is_bold, color=ink)
        lab.alignment = Alignment(indent=0 if is_bold else 1)
        ws.cell(r, 2, (row or {}).get("note") or "")

        for (b, p) in period_cols:
            ci = first_val + period_cols.index((b, p))
            val = _cell_value(row, b, p)
            cell = ws.cell(r, ci, val)
            cell.number_format = num_fmt
            cell.alignment = right
            if is_bold:
                cell.font = Font(bold=True)

        if row is not None:
            conf = row.get("mapping_confidence")
            ws.cell(r, conf_col, f"{round(conf * 100)}%" if isinstance(conf, (int, float)) else "")
            vals = row.get("values") or []
            ws.cell(r, src_col, _prov_str(vals[0].get("provenance")) if vals else "")

        if role == "subtotal":
            for c in range(1, src_col + 1):
                ws.cell(r, c).border = thin_top
        elif role == "total":
            for c in range(1, src_col + 1):
                ws.cell(r, c).border = dbl_top
                ws.cell(r, c).fill = total_fill
        r += 1
    return r


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
