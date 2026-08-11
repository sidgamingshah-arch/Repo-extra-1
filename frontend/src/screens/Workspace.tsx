/** Screen 4 — Workspace. The core extraction screen: source viewer (left) + editable
 * output panel with a cell inspector (right). Full-height flex layout, not a padded page.
 * Mirrors wireframe scrExtract + OUTPUT + SELINFO verbatim, data-driven from useStatement. */
import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { useNavigate } from "react-router-dom";

import { ConfidencePill, NoteChip, Segmented, StatusIcon } from "../components/ui";
import { EmptyState } from "../components/EmptyState";
import { ExcelGrid, PageStack, toPicked, type Picked } from "../components/SourceViewer";
import { color, confStyle, font, layout, radius, shadow, fmtIN, fmtPlain, parseAccounting } from "../theme";
import { DERIVED_STATEMENTS } from "../types";
import type { Basis, FxRateResolution, StatementColumn, StatementKey, StatementResponse, StatementRow } from "../types";
import { ApiError } from "../lib/api";
import { useDocumentStatement, useEditDocumentLineItem, useFxRateResolution, useRevertDocumentLineItem, useStatement, useEditLineItem, useProjectLoaded } from "../lib/queries";
import { useUI } from "../store";
import { useT } from "../i18n";
import { SCREENS } from "./config";

/* Very light vertical column divider for the output grid (subtle table gridlines). */
const COL_DIVIDER = "rgba(37,45,60,0.07)";
const colDiv: CSSProperties = { borderLeft: `1px solid ${COL_DIVIDER}` };

/* ---- toolbar labelled <select> chip (interactive; e.g. statement / units / currency) ---- */
function ToolSelect<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <label
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        fontSize: 12,
        color: color.sec,
        border: `1px solid ${color.cardBorder}`,
        borderRadius: radius.control,
        padding: "5px 9px 5px 11px",
      }}
    >
      <span style={{ color: color.muted }}>{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
        style={{
          fontSize: 12,
          fontWeight: 600,
          fontFamily: font.sans,
          color: color.ink,
          border: "none",
          outline: "none",
          background: "transparent",
          cursor: "pointer",
        }}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

/* ---- left source-viewer "paper" row ---- */
function PaperRow({ row, selected }: { row: StatementRow; selected: boolean }) {
  const k = row.kind;
  const isHead = k === "section" || k === "total";
  const isBold = isHead || k === "subtotal";
  const wt = isBold ? 700 : k === "subhead" ? 600 : 400;
  const fg = isHead ? "#111" : k === "subhead" ? "#333" : "#444";
  const showV = k === "item" || k === "subtotal" || k === "total";
  const v1 = showV ? fmtIN(row.v1) : "";
  const v2 = showV ? fmtIN(row.v2) : "";
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 78px 78px",
        gap: 4,
        padding: selected ? "3px 6px" : "2px 0",
        background: selected ? color.indigoTint2 : "transparent",
        borderRadius: selected ? 4 : 0,
        margin: selected ? "2px -6px" : 0,
        position: "relative",
      }}
    >
      {selected && (
        <span
          style={{
            position: "absolute",
            left: -10,
            top: 0,
            bottom: 0,
            width: 3,
            background: color.indigo,
            borderRadius: 2,
          }}
        />
      )}
      <span style={{ fontWeight: wt, color: fg, paddingLeft: k === "item" ? 14 : 0 }}>
        {row.source_label ?? row.label}
      </span>
      <span style={{ textAlign: "right", fontFamily: font.mono, fontWeight: wt, color: fg }}>{v1}</span>
      <span style={{ textAlign: "right", fontFamily: font.mono, color: "#888" }}>{v2}</span>
    </div>
  );
}

/* Units presentation (display only; the raw value is untouched for editing/formulas). Values
 * are stored AS REPORTED, i.e. already in the source's magnitude (`srcScale`, e.g. 1000 for a
 * statement stated "in thousands"). Converting to a target magnitude therefore scales by
 * srcScale/target — never a naive divide, which would double-scale an already-scaled figure. */
type UnitTarget = "as_reported" | "thousands" | "millions" | "billions";
const TARGET_SCALE: Record<Exclude<UnitTarget, "as_reported">, number> = {
  thousands: 1e3,
  millions: 1e6,
  billions: 1e9,
};

/* Currencies offered for presentation. Rates come from the admin-maintained FX master
 * (/fx-rates) — never typed here and never guessed — so a re-currencied figure is always
 * shown with the rate, its as-of date, and a "derived" marker when the master only held the
 * opposite direction. When the master has no rate for the pair we do NOT convert: presenting
 * source figures under a target-currency label is the failure mode this replaces.
 * The document's own currency stays the default (no conversion at all). */
const CURRENCIES = ["USD", "EUR", "GBP", "INR", "CNY", "HKD", "JPY", "SGD", "AUD", "CAD"];

/** The master's answer, but only when it actually carries a rate for the pair being shown.
 * Returning the resolved variant (or null) rather than the whole union makes the "no rate
 * configured" answer structurally unusable as a multiplier — the caller cannot accidentally
 * convert with it. */
type ResolvedFx = Extract<FxRateResolution, { resolved: true }>;
function appliedRate(res: FxRateResolution | undefined, converting: boolean): ResolvedFx | null {
  return converting && res !== undefined && res.resolved ? res : null;
}

/* A derived (inverted) rate is a repeating decimal carried at full precision — 20 digits of
 * it would swamp the caption. Show 6 significant digits there; the multiplier itself still
 * uses the full value the master returned, and the caption's tooltip carries it verbatim. */
function fmtRate(rate: string): string {
  const n = Number(rate);
  if (!Number.isFinite(n) || n === 0) return rate;
  return Number(n.toPrecision(6)).toString();
}

/** A rejected edit, in words the analyst can act on. The server's own `detail` is preferred —
 *  it names the concept, the basis or the bad formula — and only falls back to the status code
 *  when there is nothing better, because "something went wrong" is what silence already said. */
function editErrorText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.detail) return err.detail;
    // A structured detail (e.g. {"error":"bad_formula","message":…}) travels in the body text.
    const m = /"message"\s*:\s*"([^"]+)"/.exec(err.message);
    if (m) return m[1];
    if (err.status === 403) return "Your role cannot edit extracted values.";
    if (err.status === 404) return "This line is not part of the extraction or its template.";
    return `The server refused the edit (${err.status}).`;
  }
  return err instanceof Error ? err.message : "The edit could not be saved.";
}

/* Accounting formatter with an explicit decimal count (fmtIN forces 0dp). */
function fmtDec(n: number, dp: number): string {
  const s = Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp });
  return n < 0 ? `(${s})` : s;
}

function presentValue(raw: number | null, srcScale: number, target: UnitTarget): string {
  if (raw == null) return "";
  if (target === "as_reported") return fmtIN(raw);
  const scaled = raw * (srcScale / TARGET_SCALE[target]);
  // 0dp for large magnitudes, else 2dp — and never collapse a genuinely nonzero figure to 0.
  let dp = Math.abs(scaled) >= 1000 ? 0 : 2;
  while (scaled !== 0 && Number(scaled.toFixed(dp)) === 0 && dp < 6) dp += 2;
  return fmtDec(scaled, dp);
}

/* ---- matrix statement grid (equity components as columns, movements as rows) ----
 *
 * A statement of changes in equity is not a two-column comparative: its columns are equity
 * components (issued capital, each reserve, retained profits, non-controlling interests, total
 * equity) and its rows are movements through the year. There can be a dozen or more columns, so
 * the table scrolls horizontally with the caption column pinned — the caption is what makes any
 * cell readable, and losing it while scrolling makes the figures meaningless. */
function MatrixGrid({
  columns,
  rows,
  sel,
  present,
  linkable,
  onSelect,
}: {
  columns: StatementColumn[];
  rows: StatementRow[];
  sel: string;
  present: (raw: number | null) => string;
  linkable: boolean;
  onSelect: (id: string) => void;
}) {
  const LABEL_W = 300;
  const CELL_W = 118;
  const cell: CSSProperties = {
    ...colDiv,
    width: CELL_W,
    flex: "0 0 auto",
    padding: "0 10px",
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-end",
    fontFamily: font.mono,
    fontSize: 11.5,
  };
  const pinned: CSSProperties = {
    width: LABEL_W,
    flex: "0 0 auto",
    position: "sticky",
    left: 0,
    zIndex: 1,
    padding: "0 12px",
    display: "flex",
    alignItems: "center",
  };

  return (
    <div style={{ flex: 1, overflow: "auto", minHeight: 0 }}>
      <div style={{ display: "inline-block", minWidth: "100%" }}>
        {/* column header */}
        <div
          style={{
            display: "flex",
            height: 46,
            position: "sticky",
            top: 0,
            zIndex: 2,
            background: "#f7f8fa",
            borderBottom: `1px solid ${color.cardBorder}`,
          }}
        >
          <div style={{ ...pinned, background: "#f7f8fa", fontSize: 11, fontWeight: 700,
                        color: color.sec2, textTransform: "uppercase", letterSpacing: 0.3 }}>
            Movement
          </div>
          {columns.map((c) => (
            <div
              key={c.key}
              title={c.label}
              style={{ ...cell, alignItems: "flex-end", paddingBottom: 6, fontFamily: font.sans,
                       fontSize: 10.5, fontWeight: 700, color: color.sec2, textAlign: "right",
                       lineHeight: 1.25 }}
            >
              <span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis",
                             whiteSpace: "normal", maxHeight: 28 }}>
                {c.label}
              </span>
            </div>
          ))}
        </div>

        {rows.map((r) => {
          const isBalance = r.kind === "subtotal" || r.kind === "total";
          const selected = r.id === sel;
          const jump = linkable && !!r.source && toPicked(r.source, r.label) !== null;
          const bg = selected ? color.indigoTint3 : isBalance ? color.rowAltBg : color.surface;
          return (
            <div
              key={r.id}
              onClick={() => onSelect(r.id)}
              title={jump ? "Click to show this row in the source document" : undefined}
              style={{
                display: "flex",
                height: 34,
                borderBottom: `1px solid ${color.hairline}`,
                background: bg,
                cursor: "pointer",
              }}
            >
              <div style={{ ...pinned, background: bg }}>
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: isBalance ? 600 : 400,
                    color: color.ink,
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    borderBottom: jump ? `1px dashed ${selected ? color.indigo : color.dashed}` : "none",
                  }}
                >
                  {r.label}
                </span>
              </div>
              {columns.map((c) => {
                const v = r.cells?.[c.key] ?? null;
                return (
                  <div
                    key={c.key}
                    style={{
                      ...cell,
                      fontWeight: isBalance ? 600 : 400,
                      // An empty cell is meaningful here: the movement did not touch that
                      // component. Showing a dash rather than nothing says so.
                      color: v === null ? color.faint : color.ink,
                    }}
                  >
                    {v === null ? "–" : present(v)}
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ---- where a displayed figure came from ----
 *
 * A calculated line shows the figure its components come to, not the one printed on the page, so
 * the grid has to say which it is looking at. Silence here would make a computed subtotal
 * indistinguishable from an extracted one — and it is the difference between a number the
 * document asserts and a number this spread asserts. */
type Origin = NonNullable<StatementRow["origin"]>;
const ORIGIN_CHIP: Record<Origin, { label: string; bg: string; fg: string; help: string }> = {
  extracted: { label: "", bg: "", fg: "", help: "" },      // the ordinary case: no chip
  calculated: { label: "ƒ", bg: color.indigoTint2, fg: color.indigo,
                help: "Computed from this line's components, not read off the page" },
  manual: { label: "✎", bg: color.amberBg, fg: color.amberFg,
            help: "A value entered by hand, which overrides both the document and the components" },
  reported_uncomputed: { label: "!", bg: color.redBg, fg: color.redFg,
                         help: "Printed in the document but not verifiable — none of this line's "
                               + "components were extracted" },
};

function OriginChip({ origin }: { origin?: Origin }) {
  if (!origin || origin === "extracted") return null;
  const c = ORIGIN_CHIP[origin];
  return (
    <span
      title={c.help}
      data-testid={`origin-${origin}`}
      style={{ fontSize: 9.5, fontWeight: 700, lineHeight: 1, padding: "3px 5px",
               borderRadius: 4, background: c.bg, color: c.fg, fontFamily: font.mono,
               flex: "0 0 auto" }}
    >
      {c.label}
    </span>
  );
}

/* ---- right output-panel row ---- */
function OutputRow({
  row,
  sel,
  present,
  linkable,
  editing,
  onSelect,
  onEditCell,
  onCommitCell,
  onOpenNote,
}: {
  row: StatementRow;
  sel: string;
  present: (raw: number | null) => string;
  linkable: boolean;   // real doc whose value resolves to a source location
  /** Which cell of THIS row is currently open for typing, if any. */
  editing: "current" | "prior" | null;
  /** Selecting a row also drives the source viewer — to the period whose figure was clicked. */
  onSelect: (id: string, period?: "current" | "prior") => void;
  onEditCell: (id: string, period: "current" | "prior" | null) => void;
  onCommitCell: (row: StatementRow, period: "current" | "prior", raw: string) => void;
  onOpenNote: (ref: string) => void;
}) {
  const k = row.kind;
  const isSection = k === "section";
  const isSub = k === "subhead";
  const isSt = k === "subtotal";
  const isTot = k === "total";
  const isItem = k === "item";
  const selected = row.id === sel;

  let bg: string = color.surface;
  if (isSection) bg = "#f2f4f8";
  else if (isSt) bg = color.rowAltBg;
  else if (isTot) bg = color.indigoTint2;
  if (selected && isItem) bg = color.indigoTint3;

  const ind = isSection ? 0 : isSub ? 4 : row.level ? 26 : 14;
  const h = isSection ? 32 : 34;
  const wt = isSection || isTot ? 700 : isSub || isSt ? 600 : 400;
  const fg = isSection ? color.viewerBg : isSub ? color.sec2 : color.ink;
  const vwt = isSt || isTot ? 600 : selected ? 600 : 400;
  const vfg = isTot ? color.indigo : color.ink;
  const showV = isItem || isSt || isTot;
  // A row that carries its own formatted figures (a KPI's 1.35× / 12.4% / 45 days) renders them
  // verbatim: they are not amounts, so the currency/magnitude presentation must not touch them.
  const v1 = showV ? (row.display1 ?? present(row.v1)) : "";
  const v2 = showV ? (row.display2 ?? present(row.v2)) : "";
  // One NOTE column, but keep BOTH references when a row cites different notes per period
  // (e.g. note "10" current, "10a" prior) — collapsing to one would drop the second linkage.
  const noteRefs = [row.note, row.note2 && row.note2 !== row.note ? row.note2 : null].filter(
    (n): n is string => !!n,
  );
  // The value itself is the hyperlink: clicking a figure selects the row and drives the live
  // viewer to THAT figure's page+bbox (or cell). Each period is decorated independently — last
  // year's number is printed in its own column, often on its own page, and a reviewer checks it
  // just as much as this year's, so linking only the current column left half the grid dead.
  const links1 = linkable && isItem && !!row.source && toPicked(row.source, row.label) !== null;
  const links2 = linkable && isItem && !!row.source2 && toPicked(row.source2, row.label) !== null;
  const canEdit = row.editable !== false && (isItem || isSt || isTot);

  /** One figure cell. A single click follows it to the page it was printed on; a double click
   *  opens it for typing IN PLACE. Editing a figure two hundred pixels below the figure — which
   *  is what a bottom bar is — makes the analyst hold the number in their head to check the one
   *  they typed. */
  function valueCell(period: "current" | "prior", text: string, links: boolean,
                     weight: number, fg: string) {
    const raw = period === "current" ? row.v1 : row.v2;
    const isOpen = editing === period;
    const note = row.comments?.[period]?.text;
    if (isOpen) {
      return (
        <span style={{ ...colDiv, display: "flex", alignItems: "center", padding: "0 2px" }}
              onClick={(e) => e.stopPropagation()}>
          <input
            autoFocus
            defaultValue={fmtPlain(raw)}
            data-testid={`cell-input-${period}`}
            onBlur={(e) => onCommitCell(row, period, e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") onCommitCell(row, period, e.currentTarget.value);
              if (e.key === "Escape") { e.preventDefault(); onEditCell(row.id, null); }
            }}
            style={{ width: "100%", fontFamily: font.mono, fontSize: 12, textAlign: "right",
                     border: `1px solid ${color.indigo}`, borderRadius: 4, padding: "3px 5px",
                     outline: "none", boxShadow: shadow.focusRing }}
          />
        </span>
      );
    }
    return (
      <span
        data-testid={showV ? `${period === "current" ? "v1" : "v2"}-${row.id}` : undefined}
        onClick={showV ? (e) => { e.stopPropagation(); onSelect(row.id, period); } : undefined}
        onDoubleClick={canEdit ? (e) => { e.stopPropagation(); onEditCell(row.id, period); }
                               : undefined}
        title={[links ? (period === "current"
                          ? "Click to show this figure in the source document"
                          : "Click to show last year's figure in the source document") : "",
                canEdit ? "Double-click to edit" : "",
                note ? `Note: ${note}` : ""].filter(Boolean).join(" · ") || undefined}
        style={{ ...colDiv, display: "flex", alignItems: "center", justifyContent: "flex-end",
                 gap: 4, fontFamily: font.mono, fontSize: 12, fontWeight: weight,
                 color: selected && links ? color.indigo : fg,
                 cursor: links || canEdit ? "pointer" : "default" }}
      >
        {/* A figure carrying a reason why it was overridden says so where the figure is. */}
        {note && <span style={{ color: color.amberFg, fontSize: 10 }}>✎</span>}
        <span
          style={links
            ? { borderBottom: `1px dashed ${selected ? color.indigo : color.dashed}` }
            : undefined}
        >
          {text}
        </span>
      </span>
    );
  }

  return (
    <div
      onClick={() => onSelect(row.id)}
      style={{
        display: "grid",
        gridTemplateColumns: layout.gridCols,
        alignItems: "stretch",
        padding: "0 16px",
        height: h,
        borderBottom: `1px solid ${color.hairline}`,
        cursor: "pointer",
        background: bg,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 7, paddingLeft: ind, minWidth: 0 }}>
        {isSection && <span style={{ fontSize: 9, color: color.faint }}>▾</span>}
        <span
          style={{
            fontSize: 12.5,
            fontWeight: wt,
            color: fg,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {row.label}
        </span>
        <OriginChip origin={row.origin} />
        <StatusIcon status={row.status} />
      </div>
      <div style={{ ...colDiv, display: "flex", alignItems: "center", justifyContent: "center",
                    gap: 4, flexWrap: "wrap" }}>
        {noteRefs.map((n) => (
          <NoteChip key={n} onClick={(e) => { e?.stopPropagation(); onOpenNote(n); }}>{n}</NoteChip>
        ))}
      </div>
      {valueCell("current", v1, links1, vwt, vfg)}
      {valueCell("prior", v2, links2, isSt || isTot ? 600 : 400, color.muted)}
      <div style={{ ...colDiv, display: "flex", alignItems: "center", justifyContent: "flex-end" }}>
        {row.confidence ? <ConfidencePill cat={row.confidence.cat} /> : null}
      </div>
    </div>
  );
}

/* ---- the selected row's detail, beside the grid ----
 *
 * Everything that explains one figure, next to that figure: where it came from, the arithmetic if
 * it was computed, every component with its own page, the reason it was overridden if it was, and
 * the actions. Editing happens in the cell itself (double-click); this panel is for the parts of
 * an explanation that do not fit in a cell. */
function RowDetail({
  row,
  periods,
  present,
  linkable,
  canEdit,
  saving,
  error,
  onClose,
  onEditCell,
  onSaveComment,
  onSaveFormula,
  onRevert,
  onPickContribution,
}: {
  row: StatementRow;
  periods: string[];
  present: (raw: number | null) => string;
  linkable: boolean;
  canEdit: boolean;
  saving: boolean;
  error: string | null;
  onClose: () => void;
  onEditCell: (cell: { id: string; period: "current" | "prior" } | null) => void;
  onSaveComment: (row: StatementRow, period: "current" | "prior", text: string) => void;
  onSaveFormula: (row: StatementRow, period: "current" | "prior", formula: string) => void;
  onRevert: () => void;
  onPickContribution: (picked: Picked | null) => void;
}) {
  const [period, setPeriod] = useState<"current" | "prior">("current");
  const existing = row.comments?.[period]?.text ?? "";
  const [note, setNote] = useState(existing);
  const [formula, setFormula] = useState(row.formula ?? "");
  useEffect(() => { setNote(row.comments?.[period]?.text ?? ""); }, [row.id, period, row.comments]);
  useEffect(() => { setFormula(row.formula ?? ""); }, [row.id, row.formula]);

  // The panel talks about ONE period, so it uses that period's origin, not the row summary.
  const origin = (period === "current" ? row.origin1 : row.origin2) ?? row.origin ?? "extracted";
  const chip = ORIGIN_CHIP[origin];
  const cs = row.confidence ? confStyle(row.confidence.cat) : null;
  const reported = period === "current" ? row.reported1 : row.reported2;
  const shown = period === "current" ? row.v1 : row.v2;
  const computed = period === "current" ? row.calculated1 : row.calculated2;
  // A calculated line's divergence from the printed figure is the finding this panel exists to
  // state. The printed figure is never the line's value, but silence about it would hide the
  // disagreement entirely.
  const diverges = origin === "calculated" && reported != null && shown != null
    && Math.abs(shown - reported) > 0.5;

  const sectionTitle: CSSProperties = {
    fontSize: 10, fontWeight: 700, letterSpacing: 0.4, textTransform: "uppercase",
    color: color.muted, marginBottom: 6,
  };

  return (
    <div
      data-testid="row-detail"
      style={{
        width: 340, flex: "0 0 340px", borderLeft: `1px solid ${color.cardBorder}`,
        background: "#fbfcfd", display: "flex", flexDirection: "column", minHeight: 0,
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "12px 14px 10px",
                    borderBottom: `1px solid ${color.hairline}` }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: color.ink, lineHeight: 1.35 }}>
            {row.label}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 5,
                        flexWrap: "wrap" }}>
            {origin !== "extracted" && (
              <span title={chip.help}
                    style={{ fontSize: 10, fontWeight: 600, padding: "2px 7px",
                             borderRadius: radius.pill, background: chip.bg, color: chip.fg }}>
                {origin === "calculated" ? "calculated"
                  : origin === "manual" ? "manual override" : "printed, unverified"}
              </span>
            )}
            {cs && row.confidence && (
              <span style={{ fontSize: 10, fontWeight: 600, padding: "2px 7px",
                             borderRadius: radius.pill, background: cs.bg, color: cs.fg }}>
                {row.confidence.pct}%
              </span>
            )}
            {row.inspector?.src && (
              <span style={{ fontSize: 10.5, fontFamily: font.mono, color: color.muted }}>
                {row.inspector.src}
              </span>
            )}
          </div>
        </div>
        <button
          onClick={onClose}
          data-testid="row-detail-close"
          style={{ border: "none", background: "transparent", cursor: "pointer",
                   color: color.muted, fontSize: 15, lineHeight: 1, padding: 2 }}
        >
          ×
        </button>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "12px 14px", minHeight: 0 }}>
        {/* which period the panel is talking about */}
        <div style={{ display: "flex", gap: 4, marginBottom: 12 }}>
          {(["current", "prior"] as const).map((p, i) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              data-testid={`detail-period-${p}`}
              style={{ flex: 1, fontSize: 11, fontWeight: 600, padding: "6px 8px",
                       borderRadius: radius.controlSm, cursor: "pointer",
                       border: `1px solid ${period === p ? color.indigo : color.controlBorder}`,
                       background: period === p ? color.indigoTint2 : "#fff",
                       color: period === p ? color.indigo : color.sec2 }}
            >
              {periods[i] || (p === "current" ? "Current" : "Prior")}
            </button>
          ))}
        </div>

        <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 4 }}>
          <span style={{ fontFamily: font.mono, fontSize: 20, fontWeight: 600, color: color.ink }}>
            {(period === "current" ? row.display1 : row.display2) ?? present(shown)}
          </span>
          {canEdit && (
            <button
              onClick={() => onEditCell({ id: row.id, period })}
              data-testid="edit-value"
              style={{ fontSize: 11, fontWeight: 600, color: color.indigo, background: "#fff",
                       border: `1px solid ${color.indigoBorder2}`, borderRadius: radius.controlSm,
                       padding: "4px 9px", cursor: "pointer" }}
            >
              ✎ Edit
            </button>
          )}
          {row.status === "edited" && (
            <button
              onClick={onRevert}
              style={{ fontSize: 11, fontWeight: 600, color: color.sec2, background: "#fff",
                       border: `1px solid ${color.controlBorder}`, borderRadius: radius.controlSm,
                       padding: "4px 9px", cursor: "pointer" }}
            >
              ↺ Revert
            </button>
          )}
        </div>

        {/* the arithmetic — read-only for a computed line (its formula IS the template's rollup),
            typeable for an ordinary one, where a formula referencing other lines drives the value */}
        {origin === "calculated" && (row.arithmetic || row.formula) ? (
          <div style={{ marginTop: 10 }}>
            <div style={sectionTitle}>Computed as</div>
            <div style={{ fontFamily: font.mono, fontSize: 11, color: color.sec,
                          background: "#fff", border: `1px solid ${color.controlBorder}`,
                          borderRadius: radius.control, padding: "7px 9px", lineHeight: 1.6,
                          wordBreak: "break-word" }}>
              {row.arithmetic ?? row.formula}
            </div>
          </div>
        ) : canEdit ? (
          <div style={{ marginTop: 10 }}>
            <div style={sectionTitle}>Formula</div>
            <div style={{ display: "flex", gap: 6 }}>
              <input
                value={formula}
                spellCheck={false}
                data-testid="detail-formula"
                placeholder="=bs_current_assets__cash + …"
                onChange={(e) => setFormula(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") onSaveFormula(row, period, formula); }}
                style={{ flex: 1, minWidth: 0, fontFamily: font.mono, fontSize: 11,
                         color: color.ink, border: `1px solid ${color.controlBorder}`,
                         borderRadius: radius.control, padding: "7px 9px", outline: "none" }}
              />
              <button
                onClick={() => onSaveFormula(row, period, formula)}
                disabled={saving || formula === (row.formula ?? "")}
                data-testid="detail-formula-save"
                style={{ fontSize: 11, fontWeight: 600, whiteSpace: "nowrap",
                         color: formula === (row.formula ?? "") ? color.muted : color.indigo,
                         background: "#fff",
                         border: `1px solid ${formula === (row.formula ?? "")
                                              ? color.controlBorder : color.indigoBorder2}`,
                         borderRadius: radius.controlSm, padding: "5px 9px",
                         cursor: formula === (row.formula ?? "") ? "default" : "pointer" }}
              >
                ƒx Apply
              </button>
            </div>
            <div style={{ fontSize: 10.5, color: color.muted, marginTop: 4, lineHeight: 1.5 }}>
              References other line items by canonical key; the result becomes this figure.
            </div>
          </div>
        ) : (row.arithmetic || row.formula) ? (
          <div style={{ marginTop: 10 }}>
            <div style={sectionTitle}>{row.arithmetic ? "Made up of" : "Formula"}</div>
            <div style={{ fontFamily: font.mono, fontSize: 11, color: color.sec,
                          wordBreak: "break-word" }}>{row.arithmetic ?? row.formula}</div>
          </div>
        ) : null}

        {/* what the document printed, when that is a DIFFERENT number from the one shown */}
        {diverges && (
          <div
            data-testid="reported-divergence"
            style={{ marginTop: 10, padding: "8px 10px", background: color.amberBg,
                     borderRadius: radius.control, fontSize: 11.5, color: color.amberFg,
                     lineHeight: 1.55 }}
          >
            <strong style={{ fontWeight: 600 }}>The document printed {present(reported)}.</strong>{" "}
            This line shows what its components come to. The difference
            ({present((shown ?? 0) - (reported ?? 0))}) is in the review queue.
          </div>
        )}
        {origin === "manual" && computed != null && (
          <div style={{ marginTop: 10, fontSize: 11.5, color: color.sec, lineHeight: 1.55 }}>
            The components come to {present(computed)}; the value above was entered by hand.
          </div>
        )}
        {row.inspector?.note && !diverges && (
          <div style={{ marginTop: 10, fontSize: 11.5, color: color.sec2, lineHeight: 1.55 }}>
            {row.inspector.note}
          </div>
        )}

        {/* every line that went into the figure, each clickable through to its page */}
        {row.contributions?.length ? (
          <div style={{ marginTop: 14 }}>
            <div style={sectionTitle}>Made up of</div>
            <div style={{ border: `1px solid ${color.controlBorder}`, borderRadius: radius.control,
                          background: "#fff", overflow: "hidden" }}>
              {row.contributions.map((c, i) => {
                const prov = period === "current" ? c.source : c.source2;
                const jump = linkable ? toPicked(prov ?? null, c.label) : null;
                const v = period === "current" ? c.v1 : c.v2;
                return (
                  <div
                    key={`${c.label}-${i}`}
                    onClick={() => jump && onPickContribution(jump)}
                    title={jump ? `Show ${period === "current" ? c.src : c.src2} in the document`
                                : undefined}
                    style={{ display: "flex", alignItems: "baseline", gap: 6, padding: "6px 9px",
                             borderTop: i === 0 ? "none" : `1px solid ${color.hairline}`,
                             cursor: jump ? "pointer" : "default" }}
                  >
                    <span style={{ fontSize: 11, color: color.ink, flex: 1, minWidth: 0,
                                   textDecoration: jump ? "underline dotted" : "none" }}>
                      {c.label}
                    </span>
                    {c.residual && (
                      <span style={{ fontSize: 9, fontWeight: 600, padding: "1px 5px",
                                     borderRadius: radius.pill, background: color.amberBg,
                                     color: color.amberFg }}>
                        {v == null ? "absent" : "routed"}
                      </span>
                    )}
                    <span style={{ fontFamily: font.mono, fontSize: 10, color: color.muted }}>
                      {(period === "current" ? c.src : c.src2) || ""}
                    </span>
                    <span style={{ fontFamily: font.mono, fontSize: 11, fontWeight: 600,
                                   color: color.ink, minWidth: 66, textAlign: "right" }}>
                      {v == null ? "—" : present(v)}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}

        {/* the reason, for a figure that was overridden */}
        {canEdit && (
          <div style={{ marginTop: 14 }}>
            <div style={sectionTitle}>Note on this figure</div>
            <textarea
              value={note}
              data-testid="detail-comment"
              onChange={(e) => setNote(e.target.value)}
              placeholder="Why was this figure changed? Saved with the edit and carried into the export."
              rows={3}
              style={{ width: "100%", boxSizing: "border-box", fontSize: 11.5,
                       fontFamily: font.sans, color: color.ink, resize: "vertical",
                       border: `1px solid ${color.controlBorder}`, borderRadius: radius.control,
                       padding: "7px 9px", outline: "none", lineHeight: 1.5 }}
            />
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
              <button
                onClick={() => onSaveComment(row, period, note)}
                disabled={saving || note === existing}
                data-testid="detail-comment-save"
                style={{ fontSize: 11, fontWeight: 600,
                         color: note === existing ? color.muted : "#fff",
                         background: note === existing ? "#fff" : color.indigo,
                         border: note === existing ? `1px solid ${color.controlBorder}` : "none",
                         borderRadius: radius.controlSm, padding: "5px 11px",
                         cursor: note === existing ? "default" : "pointer" }}
              >
                {saving ? "Saving…" : "Save note"}
              </button>
              {row.comments?.[period]?.by && (
                <span style={{ fontSize: 10.5, color: color.muted }}>
                  {row.comments[period].by}
                  {row.comments[period].at ? ` · ${row.comments[period].at.slice(0, 10)}` : ""}
                </span>
              )}
            </div>
          </div>
        )}

        {error && (
          <div
            data-testid="edit-error"
            style={{ marginTop: 12, padding: "8px 10px", background: color.redBg,
                     borderRadius: radius.control, fontSize: 11.5, color: color.redFg,
                     lineHeight: 1.5 }}
          >
            <strong style={{ fontWeight: 600 }}>Not saved.</strong> {error}
          </div>
        )}
      </div>
    </div>
  );
}

export default function WorkspaceScreen() {
  const navigate = useNavigate();
  const t = useT();
  const { locale, dataset, setDataset, statement, setStatement, sel, selRow, setNote } = useUI();
  // Units presentation is display-only (raw values stay intact for editing/formulas).
  const [unitTarget, setUnitTarget] = useState<UnitTarget>("as_reported");
  // Currency presentation: "" = the document's own currency (no conversion). A different target
  // is converted at the rate the FX master resolves for the pair — there is no manual entry.
  const [targetCcy, setTargetCcy] = useState<string>("");
  // Open a note reference: select it and jump to the All Notes screen.
  const openNote = (ref: string) => {
    const n = parseInt(ref, 10);
    if (!Number.isNaN(n)) {
      setNote(n);
      navigate(SCREENS.notes.path);
    }
  };
  const activeDocumentId = useUI((s) => s.activeDocumentId);
  const usingReal = !!activeDocumentId;
  const loaded = useProjectLoaded();
  // KPIs and the additional-items remainder are derived from a REAL extraction; there is no demo
  // data behind them, so the demo workspace falls back to the balance sheet rather than asking
  // for a view the demo endpoint cannot serve.
  const derived = DERIVED_STATEMENTS.includes(statement);
  const effectiveStatement: StatementKey = !usingReal && derived ? "balance_sheet" : statement;
  const realQ = useDocumentStatement(activeDocumentId ?? undefined, effectiveStatement, dataset,
                                     locale);
  const demoQ = useStatement(effectiveStatement, dataset, locale, !usingReal);
  const data = usingReal ? realQ.data : demoQ.data;
  const isPending = usingReal ? realQ.isPending : demoQ.isPending;
  const editMut = useEditLineItem();
  const realEditMut = useEditDocumentLineItem(activeDocumentId ?? undefined);
  const realRevertMut = useRevertDocumentLineItem(activeDocumentId ?? undefined);
  // The value's source location for the live viewer — set when a row is selected (real docs).
  const [picked, setPicked] = useState<Picked | null>(null);
  // Why the last save was refused, shown in the detail panel. Null while nothing was rejected.
  const [editError, setEditError] = useState<string | null>(null);
  // Which cell is open for typing. Editing happens IN the cell — a bottom bar put the input a
  // long way from the figure it was changing.
  const [editCell, setEditCell] = useState<{ id: string; period: "current" | "prior" } | null>(null);
  // A highlight belongs to one statement/basis; clear it when either changes so the viewer
  // never keeps pointing at a page/cell from the statement the user just navigated away from.
  useEffect(() => { setPicked(null); }, [statement, dataset]);
  // The FX lookup is resolved here, above the loading/empty early-returns, because hooks
  // cannot be called conditionally. `converting` is false until a real target is picked, so
  // the query stays disabled and no request goes out in the default (no conversion) case.
  const srcCcy = data?.currency || "";
  // A "raw" view (the KPIs) has no currency and no magnitude — its figures are ratios. A target
  // currency left selected from a statement must not follow the analyst into it and raise "no
  // rate for ? → USD" about numbers that were never in a currency.
  const rawView = data?.presentation === "raw";
  // `wantConvert` is the user's request; `converting` is whether it is even askable — a document
  // whose own currency was never determined has no pair to look up, so we say "not converted"
  // instead of firing a lookup for "? → USD".
  const wantConvert = !rawView && !!targetCcy && targetCcy !== srcCcy;
  const converting = wantConvert && !!srcCcy;
  const fxQ = useFxRateResolution(converting ? srcCcy : undefined, converting ? targetCcy : undefined);

  if (!usingReal && !loaded) return <EmptyState />;
  if (usingReal && realQ.isError) return <EmptyState />;   // uploaded but not extracted yet
  if (isPending || !data) {
    return <div style={{ padding: 60, textAlign: "center", color: color.muted }}>Loading…</div>;
  }

  const d: StatementResponse = data;
  // Selecting a row also drives the live source viewer: resolve the clicked figure's provenance
  // to a pick so the document scrolls to and highlights that value's page+bbox (PDF) or cell
  // (Excel). Clicking last year's number goes to last year's figure, not this year's.
  const handleSelect = (id: string, period: "current" | "prior" = "current") => {
    selRow(id);
    if (usingReal) {
      const row = d.rows.find((r) => r.id === id);
      const prov = period === "prior" ? (row?.source2 ?? null) : (row?.source ?? null);
      // Set (or clear, when the figure has no resolvable source) the live-viewer highlight so a
      // row without provenance never leaves a stale highlight from a previously clicked row.
      setPicked(toPicked(prov, row?.label ?? ""));
    }
  };
  // Units presentation: convert relative to the source's own magnitude (default 1 = ones).
  const srcScale = d.units_scale_factor ?? 1;
  // The master's answer, and only when it actually holds a rate for this pair. A pending or
  // failed lookup leaves `appliedFx` null, which means the panel stays in the SOURCE currency
  // rather than briefly showing unconverted figures under the target's label.
  const fxRes = fxQ.data;
  const appliedFx = appliedRate(fxRes, converting);
  const fxPending = converting && fxQ.isPending;
  const fxUnavailable = wantConvert && !appliedFx && !fxPending;
  // A failed lookup and a missing rate both stop the conversion, but they are different facts:
  // only the latter is something an administrator fixes by adding a rate.
  const fxLookupFailed = converting && fxQ.isError;
  // Currency conversion is applied before unit scaling; identity (rate 1) when not converting.
  // Raw values are never mutated. The multiplier is a JS number only because this whole
  // presentation path already is (toLocaleString) — the exact decimal arithmetic, including
  // the reciprocal of an inverted rate, is done server-side in Decimal.
  const fx = appliedFx ? Number(appliedFx.rate) : 1;
  // On a raw view the only amounts left are a KPI's own inputs, shown in the inspector. Those are
  // statement figures AS REPORTED — the KPI response declares no magnitude, so scaling them by
  // the statements' selection (÷1000 against a scale of 1) would misstate them.
  const present = (raw: number | null) =>
    rawView ? fmtIN(raw) : presentValue(raw == null ? null : raw * fx, srcScale, unitTarget);
  // A single, unambiguous caption for the whole output panel: the active magnitude, plus the
  // conversion when re-currencied — with the rate, the date it is AS OF, and a derived marker
  // naming the stored pair we inverted. Figures are never silently transformed.
  // A raw view (the KPIs) is in no magnitude at all: the selector is hidden and `present` does
  // not scale, so captioning it with a leftover "millions" would describe figures that are not in
  // millions.
  const activeUnits = rawView ? ""
    : unitTarget === "as_reported" ? d.units : t(`ws.units.${unitTarget}`).toLowerCase();
  const fxCaption = appliedFx
    ? `${srcCcy || "?"} → ${targetCcy} @ ${fmtRate(appliedFx.rate)} · ${t("ws.asOf")} ${appliedFx.as_of}`
      + (appliedFx.derived ? ` · ${t("ws.derived")} (${appliedFx.path.join(" → ")})` : "")
    : fxPending
      ? t("ws.rateLoading")
      // Not converting: name the currency the figures ARE in, so the panel is never ambiguous.
      : fxUnavailable ? `${srcCcy || "?"} (${t("ws.sourceCcy")})` : "";
  const unitsCaption = [
    activeUnits ? `${t("ws.figuresIn")} ${activeUnits}` : "",
    fxCaption,
  ].filter(Boolean).join("  ·  ");
  const lowConfCount = d.rows.filter((r) => r.confidence?.cat === "low").length;
  // A matrix statement (changes in equity) has NAMED component columns from the document
  // instead of the fixed current/prior pair, so it renders through MatrixGrid.
  const isMatrix = d.layout === "matrix";
  const selRowObj = d.rows.find((r) => r.id === sel) ?? d.rows.find((r) => r.inspector);
  const insp = selRowObj?.inspector;
  const isEdited = selRowObj?.status === "edited";
  const cs = selRowObj?.confidence ? confStyle(selRowObj.confidence.cat) : confStyle("med");
  // Not every row is a figure someone can correct. A KPI is computed (fix its inputs instead), a
  // line mapped to no concept has no address to save against, and an equity movement is a
  // component grid. Offering a control that cannot work is how "editing doesn't work" starts.
  const canEditSel = !!selRowObj && selRowObj.editable !== false
    && (selRowObj.kind === "item" || selRowObj.kind === "subtotal" || selRowObj.kind === "total");
  const saving = realEditMut.isPending || editMut.isPending;
  // The detail panel is open whenever a row is selected. `editing` (the old bottom-bar mode) is
  // still honoured so the "Edit value" affordance can open a cell from elsewhere.
  const detailOpen = !!sel;

  /** Write ONE figure. Returns true when the server took it; on refusal the reason is shown and
   *  the cell stays open, because a rejected edit that closes silently is indistinguishable from
   *  a saved one. */
  const writeFigure = async (row: StatementRow, period: "current" | "prior",
                             value: number | null, comment: string) => {
    try {
      if (usingReal) {
        await realEditMut.mutateAsync({ key: row.id, value, formula: row.formula ?? "",
                                        basis: dataset, period, comment });
      } else if (period === "current") {
        await editMut.mutateAsync({ id: row.id, value, formula: row.formula ?? "" });
      } else {
        throw new Error("The sample project only supports editing the current period. "
                        + "Upload a document to edit both.");
      }
      setEditError(null);
      return true;
    } catch (err) {
      setEditError(editErrorText(err));
      return false;
    }
  };

  /** Commit an in-cell edit. The row's existing note for that period is resent, so correcting a
   *  figure does not silently drop the reason already recorded against it. */
  const commitCell = async (row: StatementRow, period: "current" | "prior", raw: string) => {
    const before = period === "current" ? row.v1 : row.v2;
    const next = parseAccounting(raw);
    if (next === before) { setEditCell(null); return; }        // nothing typed
    const ok = await writeFigure(row, period, next, row.comments?.[period]?.text ?? "");
    if (ok) setEditCell(null);
  };

  /** Save a note against a figure, leaving the figure itself alone. */
  const saveComment = async (row: StatementRow, period: "current" | "prior", text: string) => {
    await writeFigure(row, period, period === "current" ? row.v1 : row.v2, text);
  };

  /** Apply a formula to a figure. The SERVER evaluates it against the other line items and the
   *  result becomes the value, so a formula that cannot be resolved comes back as an error rather
   *  than silently leaving the old number in place. */
  const saveFormula = async (row: StatementRow, period: "current" | "prior", formula: string) => {
    const comment = row.comments?.[period]?.text ?? "";
    try {
      if (usingReal) {
        // No explicit value: the formula alone decides the figure.
        await realEditMut.mutateAsync({ key: row.id, value: null, formula,
                                        basis: dataset, period, comment });
      } else {
        await editMut.mutateAsync({ id: row.id, value: null, formula });
      }
      setEditError(null);
    } catch (err) {
      setEditError(editErrorText(err));
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* ---------------- TOOLBAR ---------------- */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "11px 18px",
          background: color.surface,
          borderBottom: `1px solid ${color.cardBorder}`,
          flex: "0 0 auto",
        }}
      >
        <Segmented<Basis>
          options={[
            { value: "consolidated", label: t("ws.consolidated") },
            { value: "standalone", label: t("ws.standalone") },
          ]}
          value={dataset}
          onChange={setDataset}
        />
        <Segmented<StatementKey>
          options={[
            { value: "balance_sheet", label: t("ws.stmt.balance_sheet") },
            { value: "profit_and_loss", label: t("ws.stmt.profit_and_loss") },
            { value: "cash_flow", label: t("ws.stmt.cash_flow") },
            { value: "changes_in_equity", label: t("ws.stmt.changes_in_equity") },
            // Derived from the extraction, so offered only when there IS one.
            ...(usingReal
              ? [{ value: "kpi" as StatementKey, label: t("ws.stmt.kpi") },
                 { value: "additional_items" as StatementKey,
                   label: t("ws.stmt.additional_items") }]
              : []),
          ]}
          value={effectiveStatement}
          onChange={setStatement}
        />
        {!rawView && (
        <ToolSelect<string>
          label={t("ws.currency")}
          value={targetCcy || srcCcy}
          options={[
            ...(srcCcy ? [{ value: srcCcy, label: `${srcCcy} (${t("ws.sourceCcy")})` }] : []),
            ...CURRENCIES.filter((c) => c !== srcCcy).map((c) => ({ value: c, label: c })),
          ]}
          onChange={(v) => setTargetCcy(v === srcCcy ? "" : v)}
        />
        )}
        {fxUnavailable && (
          <span
            title={fxRes && !fxRes.resolved ? fxRes.detail : undefined}
            style={{ fontSize: 11.5, fontWeight: 600, color: color.amberFg,
                     background: color.amberBg, padding: "5px 10px",
                     borderRadius: radius.pill, whiteSpace: "nowrap" }}
          >
            {fxLookupFailed ? t("ws.rateFailed") : t("ws.noRate")} {srcCcy || "?"} → {targetCcy}
          </span>
        )}
        {/* A ratio has no magnitude to present — offering "in thousands" over 1.35× would only
            invite a nonsense reading, so the selector is absent on a raw view rather than inert. */}
        {!rawView && (
        <ToolSelect<UnitTarget>
          label={t("ws.units")}
          value={unitTarget}
          options={[
            { value: "as_reported", label: t("ws.units.as_reported") },
            { value: "thousands", label: t("ws.units.thousands") },
            { value: "millions", label: t("ws.units.millions") },
            { value: "billions", label: t("ws.units.billions") },
          ]}
          onChange={setUnitTarget}
        />
        )}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 9 }}>
          <span
            style={{
              fontSize: 11.5,
              color: color.redFg,
              fontWeight: 600,
              background: color.redBg,
              padding: "5px 10px",
              borderRadius: radius.pill,
              cursor: "pointer",
            }}
          >
            {usingReal ? lowConfCount : 3} {t("ws.lowconf")}
          </span>
          {!usingReal && (
            <span
              style={{
                fontSize: 11.5,
                color: color.amberFg,
                fontWeight: 600,
                background: color.amberBg,
                padding: "5px 10px",
                borderRadius: radius.pill,
                cursor: "pointer",
              }}
            >
              2 {t("ws.unreconciled")}
            </span>
          )}
          <button
            onClick={() => navigate(SCREENS.export.path)}
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: "#fff",
              background: color.indigo,
              border: "none",
              borderRadius: radius.control,
              padding: "7px 14px",
              cursor: "pointer",
            }}
          >
            {t("ws.export")}
          </button>
        </div>
      </div>

      {/* ---------------- BODY ---------------- */}
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        {/* -------- LEFT: source viewer -------- */}
        <div
          style={{
            width: layout.sourceViewer,
            flex: `0 0 ${layout.sourceViewer}`,
            background: color.viewerBg,
            display: "flex",
            flexDirection: "column",
            minHeight: 0,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "8px 12px",
              background: color.viewerHeader,
              color: "#dfe3e9",
              flex: "0 0 auto",
            }}
          >
            <span style={{ fontSize: 11.5, fontWeight: 600 }}>{d.viewer.company}</span>
            <div style={{ display: "flex", gap: 4, marginLeft: 6 }}>
              {d.viewer.chips.map((c) => (
                <span
                  key={c.label}
                  style={{
                    fontSize: 10.5,
                    padding: "3px 8px",
                    borderRadius: radius.chip,
                    background: c.active ? color.indigo : "#3c4450",
                    color: c.active ? "#fff" : "#dfe3e9",
                    fontWeight: c.active ? 600 : 400,
                    cursor: "pointer",
                  }}
                >
                  {c.label}
                </span>
              ))}
            </div>
            <div
              style={{
                marginLeft: "auto",
                display: "flex",
                alignItems: "center",
                gap: 8,
                fontSize: 11,
                color: "#aab1bc",
              }}
            >
              <span style={{ cursor: "pointer" }}>−</span>
              <span>100%</span>
              <span style={{ cursor: "pointer" }}>+</span>
            </div>
          </div>
          {usingReal && d.format === "pdf" && activeDocumentId ? (
            <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 12, background: "#e9ebef" }}>
              <PageStack documentId={activeDocumentId} pageCount={d.page_count ?? 1}
                         picked={picked?.kind === "pdf" ? picked : null} maxHeight="100%" />
            </div>
          ) : usingReal && (d.format === "xlsx" || d.format === "xls") && activeDocumentId ? (
            <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 12, background: "#fff" }}>
              <ExcelGrid documentId={activeDocumentId}
                         picked={picked?.kind === "xlsx" ? picked : null} t={t} />
            </div>
          ) : (
          <div style={{ flex: 1, overflow: "auto", padding: 22, display: "flex", justifyContent: "center" }}>
            <div
              style={{
                width: "100%",
                maxWidth: 520,
                background: "#fff",
                borderRadius: 3,
                boxShadow: shadow.paper,
                padding: "34px 40px",
                fontSize: 11,
                color: "#333",
                height: "fit-content",
              }}
            >
              <div style={{ textAlign: "center", borderBottom: "2px solid #222", paddingBottom: 8, marginBottom: 4 }}>
                <div style={{ fontWeight: 700, fontSize: 13, letterSpacing: 0.3 }}>{d.viewer.company}</div>
                <div style={{ fontSize: 10, color: "#666", marginTop: 2 }}>{d.viewer.subtitle}</div>
              </div>
              <div
                style={{
                  display: "flex",
                  justifyContent: "flex-end",
                  gap: 22,
                  fontSize: 9,
                  color: "#888",
                  padding: "4px 0 6px",
                  fontFamily: font.mono,
                }}
              >
                <span>{`(${d.currency_symbol} in ${d.units.toLowerCase()})`}</span>
                <span>{d.periods[0]}</span>
                <span>{d.periods[1]}</span>
              </div>
              {d.rows.map((r) => (
                <PaperRow key={r.id} row={r} selected={r.id === sel} />
              ))}
              <div
                style={{
                  marginTop: 14,
                  padding: "9px 11px",
                  background: color.indigoTint,
                  border: `1px solid ${color.indigoBorder}`,
                  borderRadius: 6,
                  fontSize: 9.5,
                  color: color.indigo,
                  lineHeight: 1.5,
                }}
              >
                {d.viewer.callout}
              </div>
            </div>
          </div>
          )}
        </div>

        {/* -------- RIGHT: output panel + the selected row's detail beside it -------- */}
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "row",
                      background: color.surface, minHeight: 0 }}>
        <div
          style={{
            flex: 1,
            minWidth: 0,
            display: "flex",
            flexDirection: "column",
            background: color.surface,
            minHeight: 0,
          }}
        >
          {/* grid header — a matrix carries its own header inside MatrixGrid, because its
              columns come from the document rather than being the fixed current/prior pair. */}
          {!isMatrix && (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: layout.gridCols,
              padding: "9px 16px",
              background: color.rowAltBg,
              borderBottom: `1px solid #e8eaee`,
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: 0.4,
              color: color.muted,
              flex: "0 0 auto",
            }}
          >
            <span>{t("col.lineitem")}</span>
            <span style={{ textAlign: "center", ...colDiv }}>{t("col.note")}</span>
            <span style={{ textAlign: "right", ...colDiv }}>{d.periods[0] ?? ""}</span>
            <span style={{ textAlign: "right", ...colDiv }}>{d.periods[1] ?? ""}</span>
            <span style={{ textAlign: "right", ...colDiv }}>{t("col.conf")}</span>
          </div>
          )}

          {/* units caption — labels the magnitude of every figure in the panel */}
          {unitsCaption && (
            <div
              // The caption rounds the rate for legibility; the tooltip carries the exact
              // multiplier (and the rate's own provenance note) so it can still be verified.
              title={appliedFx
                ? `1 ${srcCcy} = ${appliedFx.rate} ${targetCcy}`
                  + (appliedFx.source ? ` · ${appliedFx.source}` : "")
                : undefined}
              style={{ flex: "0 0 auto", padding: "3px 16px", background: color.rowAltBg,
                       borderBottom: `1px solid ${color.hairline}`, textAlign: "right",
                       fontSize: 10, fontStyle: "italic", color: color.muted }}
            >
              {unitsCaption}
            </div>
          )}

          {/* The master holds no rate for the chosen pair, so nothing was converted. Say so
            * where the figures are, and point at who can fix it — a silent fallback here
            * would label source-currency numbers as the target currency. */}
          {fxUnavailable && (
            <div style={{ flex: "0 0 auto", padding: "6px 16px", background: color.amberBg,
                          borderBottom: `1px solid ${color.hairline}`, fontSize: 11,
                          color: color.amberFg, lineHeight: 1.5 }}>
              <strong style={{ fontWeight: 600 }}>
                {fxLookupFailed ? t("ws.rateFailed") : t("ws.noRate")} {srcCcy || "?"} → {targetCcy}.
              </strong>{" "}
              {fxLookupFailed ? t("ws.rateFailedHint") : t("ws.noRateHint")}
            </div>
          )}

          {/* scroll body */}
          {isMatrix ? (
            <MatrixGrid columns={d.columns ?? []} rows={d.rows} sel={sel} present={present}
                        linkable={usingReal} onSelect={handleSelect} />
          ) : (
            <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
              {d.rows.map((r) => (
                <OutputRow
                  key={r.id} row={r} sel={sel} present={present} linkable={usingReal}
                  editing={editCell?.id === r.id ? editCell.period : null}
                  onSelect={handleSelect}
                  onEditCell={(id, period) => setEditCell(period ? { id, period } : null)}
                  onCommitCell={commitCell}
                  onOpenNote={openNote}
                />
              ))}
            </div>
          )}

        </div>

          {/* The detail lives BESIDE the figures, not under them — the statement column shrinks to
              make room. A fixed bar at the bottom of the screen put the explanation of a number a
              long way from the number it explained. */}
          {selRowObj && detailOpen && (
            <RowDetail
              row={selRowObj}
              periods={d.periods}
              present={present}
              linkable={usingReal}
              canEdit={canEditSel}
              saving={saving}
              error={editError}
              onClose={() => { selRow(""); setEditError(null); }}
              onEditCell={setEditCell}
              onSaveComment={saveComment}
              onSaveFormula={saveFormula}
              onRevert={() => realRevertMut.mutate(selRowObj.id)}
              onPickContribution={(p) => p && setPicked(p)}
            />
          )}
        </div>
      </div>
    </div>
  );
}
