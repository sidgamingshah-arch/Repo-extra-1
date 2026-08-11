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
import type { Basis, FxRateResolution, StatementKey, StatementResponse, StatementRow } from "../types";
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

/* ---- right output-panel row ---- */
function OutputRow({
  row,
  sel,
  present,
  linkable,
  onSelect,
  onOpenNote,
}: {
  row: StatementRow;
  sel: string;
  present: (raw: number | null) => string;
  linkable: boolean;   // real doc whose value resolves to a source location
  onSelect: (id: string) => void;
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
  const v1 = showV ? present(row.v1) : "";
  const v2 = showV ? present(row.v2) : "";
  // One NOTE column, but keep BOTH references when a row cites different notes per period
  // (e.g. note "10" current, "10a" prior) — collapsing to one would drop the second linkage.
  const noteRefs = [row.note, row.note2 && row.note2 !== row.note ? row.note2 : null].filter(
    (n): n is string => !!n,
  );
  // The value itself is the hyperlink: clicking the row selects it and drives the live viewer
  // to the value's page+bbox (or cell). We only decorate the number as a link when the row
  // actually resolves to a source location.
  const valueLinks = linkable && isItem && !!row.source && toPicked(row.source, row.label) !== null;

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
        <StatusIcon status={row.status} />
      </div>
      <div style={{ ...colDiv, display: "flex", alignItems: "center", justifyContent: "center",
                    gap: 4, flexWrap: "wrap" }}>
        {noteRefs.map((n) => (
          <NoteChip key={n} onClick={(e) => { e?.stopPropagation(); onOpenNote(n); }}>{n}</NoteChip>
        ))}
      </div>
      {isItem ? (
        <span
          title={valueLinks ? "Click to show this figure in the source document" : undefined}
          style={{
            ...colDiv,
            display: "flex",
            alignItems: "center",
            justifyContent: "flex-end",
            fontFamily: font.mono,
            fontSize: 12,
            fontWeight: vwt,
            color: selected && valueLinks ? color.indigo : vfg,
            cursor: valueLinks ? "pointer" : "default",
          }}
        >
          <span
            style={valueLinks
              ? { borderBottom: `1px dashed ${selected ? color.indigo : color.dashed}` }
              : undefined}
          >
            {v1}
          </span>
        </span>
      ) : (
        <span style={{ ...colDiv, display: "flex", alignItems: "center", justifyContent: "flex-end",
                       fontFamily: font.mono, fontSize: 12, fontWeight: vwt, color: vfg }}>
          {v1}
        </span>
      )}
      <span style={{ ...colDiv, display: "flex", alignItems: "center", justifyContent: "flex-end",
                     fontFamily: font.mono, fontSize: 12, color: color.muted }}>{v2}</span>
      <div style={{ ...colDiv, display: "flex", alignItems: "center", justifyContent: "flex-end" }}>
        {row.confidence ? <ConfidencePill cat={row.confidence.cat} /> : null}
      </div>
    </div>
  );
}

/* ---- inspector edit-mode body (local input state, remounts per selection) ---- */
function InspectorEditor({
  row,
  onSave,
  onCancel,
}: {
  row: StatementRow;
  onSave: (value: number | null, formula: string) => void;
  onCancel: () => void;
}) {
  const initFormula = row.formula ?? row.inspector?.formula ?? "";
  const [formula, setFormula] = useState(initFormula);
  const [value, setValue] = useState(fmtPlain(row.v1));

  useEffect(() => {
    setFormula(row.formula ?? row.inspector?.formula ?? "");
    setValue(fmtPlain(row.v1));
  }, [row.id, row.formula, row.v1, row.inspector]);

  const commit = () => {
    onSave(parseAccounting(value), formula);
  };

  return (
    <>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          background: color.surface,
          border: `1px solid ${color.indigo}`,
          borderRadius: radius.control,
          padding: "8px 11px",
          boxShadow: shadow.focusRing,
        }}
      >
        <span style={{ fontFamily: font.mono, fontSize: 12, color: color.amberFg, fontWeight: 600 }}>ƒx</span>
        <input
          value={formula}
          spellCheck={false}
          onChange={(e) => setFormula(e.target.value)}
          style={{
            fontFamily: font.mono,
            fontSize: 12,
            color: color.ink,
            flex: 1,
            border: "none",
            outline: "none",
            background: "transparent",
          }}
        />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 9 }}>
        <span style={{ fontSize: 11, color: color.muted }}>Value</span>
        <input
          value={value}
          spellCheck={false}
          onChange={(e) => setValue(e.target.value)}
          style={{
            width: 120,
            fontFamily: font.mono,
            fontSize: 12,
            textAlign: "right",
            border: `1px solid ${color.controlBorder}`,
            borderRadius: 6,
            padding: "6px 9px",
            outline: "none",
          }}
        />
        <button
          onClick={commit}
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: "#fff",
            background: color.indigo,
            border: "none",
            borderRadius: radius.controlSm,
            padding: "7px 15px",
            cursor: "pointer",
          }}
        >
          Save edit
        </button>
        <button
          onClick={onCancel}
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: color.ink2,
            background: "#fff",
            border: `1px solid ${color.controlBorder}`,
            borderRadius: radius.controlSm,
            padding: "7px 13px",
            cursor: "pointer",
          }}
        >
          Cancel
        </button>
        <span style={{ fontSize: 11, color: color.muted, flex: 1 }}>
          Enter a number, or a formula referencing notes / other line items — the formula is stored with the cell.
        </span>
      </div>
    </>
  );
}

export default function WorkspaceScreen() {
  const navigate = useNavigate();
  const t = useT();
  const { locale, dataset, setDataset, statement, setStatement, sel, selRow, editing, startEdit, cancelEdit, stopEditing, setNote } =
    useUI();
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
  const editable = true;   // both the demo and the real workspace support value editing
  const loaded = useProjectLoaded();
  const realQ = useDocumentStatement(activeDocumentId ?? undefined, statement, dataset, locale);
  const demoQ = useStatement(statement, dataset, locale, !usingReal);
  const data = usingReal ? realQ.data : demoQ.data;
  const isPending = usingReal ? realQ.isPending : demoQ.isPending;
  const editMut = useEditLineItem();
  const realEditMut = useEditDocumentLineItem(activeDocumentId ?? undefined);
  const realRevertMut = useRevertDocumentLineItem(activeDocumentId ?? undefined);
  // The value's source location for the live viewer — set when a row is selected (real docs).
  const [picked, setPicked] = useState<Picked | null>(null);
  // A highlight belongs to one statement/basis; clear it when either changes so the viewer
  // never keeps pointing at a page/cell from the statement the user just navigated away from.
  useEffect(() => { setPicked(null); }, [statement, dataset]);
  // The FX lookup is resolved here, above the loading/empty early-returns, because hooks
  // cannot be called conditionally. `converting` is false until a real target is picked, so
  // the query stays disabled and no request goes out in the default (no conversion) case.
  const srcCcy = data?.currency || "";
  // `wantConvert` is the user's request; `converting` is whether it is even askable — a document
  // whose own currency was never determined has no pair to look up, so we say "not converted"
  // instead of firing a lookup for "? → USD".
  const wantConvert = !!targetCcy && targetCcy !== srcCcy;
  const converting = wantConvert && !!srcCcy;
  const fxQ = useFxRateResolution(converting ? srcCcy : undefined, converting ? targetCcy : undefined);

  if (!usingReal && !loaded) return <EmptyState />;
  if (usingReal && realQ.isError) return <EmptyState />;   // uploaded but not extracted yet
  if (isPending || !data) {
    return <div style={{ padding: 60, textAlign: "center", color: color.muted }}>Loading…</div>;
  }

  const d: StatementResponse = data;
  // Selecting a row also drives the live source viewer: resolve the row's provenance to a pick
  // so the document scrolls to and highlights the value's page+bbox (PDF) or cell (Excel).
  const handleSelect = (id: string) => {
    selRow(id);
    if (usingReal) {
      const row = d.rows.find((r) => r.id === id);
      // Set (or clear, when the row has no resolvable source) the live-viewer highlight so a
      // row without provenance never leaves a stale highlight from a previously clicked row.
      setPicked(toPicked(row?.source ?? null, row?.label ?? ""));
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
  const present = (raw: number | null) =>
    presentValue(raw == null ? null : raw * fx, srcScale, unitTarget);
  // A single, unambiguous caption for the whole output panel: the active magnitude, plus the
  // conversion when re-currencied — with the rate, the date it is AS OF, and a derived marker
  // naming the stored pair we inverted. Figures are never silently transformed.
  const activeUnits = unitTarget === "as_reported" ? d.units : t(`ws.units.${unitTarget}`).toLowerCase();
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
  const selRowObj = d.rows.find((r) => r.id === sel) ?? d.rows.find((r) => r.inspector);
  const insp = selRowObj?.inspector;
  const isEdited = selRowObj?.status === "edited";
  const cs = selRowObj?.confidence ? confStyle(selRowObj.confidence.cat) : confStyle("med");

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
          ]}
          value={statement}
          onChange={setStatement}
        />
        <ToolSelect<string>
          label={t("ws.currency")}
          value={targetCcy || srcCcy}
          options={[
            ...(srcCcy ? [{ value: srcCcy, label: `${srcCcy} (${t("ws.sourceCcy")})` }] : []),
            ...CURRENCIES.filter((c) => c !== srcCcy).map((c) => ({ value: c, label: c })),
          ]}
          onChange={(v) => setTargetCcy(v === srcCcy ? "" : v)}
        />
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

        {/* -------- RIGHT: output panel -------- */}
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
          {/* grid header */}
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
            <span style={{ textAlign: "right", ...colDiv }}>{d.periods[0]}</span>
            <span style={{ textAlign: "right", ...colDiv }}>{d.periods[1]}</span>
            <span style={{ textAlign: "right", ...colDiv }}>{t("col.conf")}</span>
          </div>

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
          <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
            {d.rows.map((r) => (
              <OutputRow key={r.id} row={r} sel={sel} present={present} linkable={usingReal}
                         onSelect={handleSelect} onOpenNote={openNote} />
            ))}
          </div>

          {/* cell inspector */}
          <div
            style={{
              flex: "0 0 auto",
              borderTop: `1px solid ${color.cardBorder}`,
              background: "#fbfcfd",
              padding: "12px 16px",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 8,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                <span style={{ fontSize: 12.5, fontWeight: 600 }}>{selRowObj?.label ?? ""}</span>
                {selRowObj?.confidence && (
                  <span
                    style={{
                      fontSize: 10.5,
                      fontWeight: 600,
                      padding: "2px 8px",
                      borderRadius: radius.pill,
                      background: cs.bg,
                      color: cs.fg,
                    }}
                  >
                    {selRowObj.confidence.pct}% confidence
                  </span>
                )}
                {insp && (
                  <span
                    style={{
                      fontSize: 10.5,
                      fontWeight: 600,
                      padding: "2px 8px",
                      borderRadius: radius.pill,
                      background: isEdited ? color.indigoTint2 : color.amberBg,
                      color: isEdited ? color.indigo : color.amberFg,
                    }}
                  >
                    {isEdited ? `Edited · ${insp.tag}` : insp.tag}
                  </span>
                )}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ fontSize: 11, color: color.muted, fontFamily: font.mono }}>
                  source: {insp?.src ?? ""}
                </span>
                {!editing && usingReal && selRowObj?.status === "edited" && (
                  <button
                    onClick={() => selRowObj && realRevertMut.mutate(selRowObj.id)}
                    style={{
                      fontSize: 11, fontWeight: 600, color: color.sec2, background: "#fff",
                      border: `1px solid ${color.controlBorder}`, borderRadius: radius.controlSm,
                      padding: "5px 11px", cursor: "pointer",
                    }}
                  >
                    ↺ Revert
                  </button>
                )}
                {!editing && editable && (
                  <button
                    onClick={startEdit}
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      color: color.indigo,
                      background: "#fff",
                      border: `1px solid ${color.indigoBorder2}`,
                      borderRadius: radius.controlSm,
                      padding: "5px 11px",
                      cursor: "pointer",
                    }}
                  >
                    ✎ Edit value
                  </button>
                )}
              </div>
            </div>

            {editing && editable && selRowObj ? (
              <InspectorEditor
                key={selRowObj.id}
                row={selRowObj}
                onSave={(value, formula) => {
                  if (usingReal) realEditMut.mutate({ key: selRowObj.id, value, formula });
                  else editMut.mutate({ id: selRowObj.id, value, formula });
                  stopEditing();
                }}
                onCancel={cancelEdit}
              />
            ) : (
              <>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    background: "#fff",
                    border: `1px solid ${color.controlBorder}`,
                    borderRadius: radius.control,
                    padding: "8px 11px",
                  }}
                >
                  <span style={{ fontFamily: font.mono, fontSize: 12, color: color.amberFg, fontWeight: 600 }}>ƒx</span>
                  <span style={{ fontFamily: font.mono, fontSize: 12, color: color.ink, flex: 1 }}>
                    {selRowObj?.formula ?? insp?.formula ?? ""}
                  </span>
                  <span style={{ fontFamily: font.mono, fontSize: 12, fontWeight: 600, color: color.indigo }}>
                    = {insp?.result ?? ""}
                  </span>
                </div>
                <div style={{ fontSize: 11, color: color.sec2, marginTop: 7, lineHeight: 1.5 }}>
                  {isEdited
                    ? "Manually edited from the front-end — the cell now carries the formula above. Original extraction confidence is retained."
                    : insp?.note ?? ""}
                </div>

                {/* A combined figure matches no single line on the page, so every line that went
                    into it is listed with its own amount and its own page — click one to jump
                    the viewer straight to where it was printed. */}
                {selRowObj?.contributions?.length ? (
                  <div
                    style={{
                      marginTop: 9,
                      border: `1px solid ${color.controlBorder}`,
                      borderRadius: radius.control,
                      background: "#fff",
                      overflow: "hidden",
                    }}
                  >
                    {selRowObj.contributions.map((c, i) => {
                      const jump = usingReal ? toPicked(c.source ?? null, c.label) : null;
                      return (
                        <div
                          key={`${c.label}-${i}`}
                          onClick={() => jump && setPicked(jump)}
                          title={jump ? `Show ${c.src} in the document` : undefined}
                          style={{
                            display: "flex",
                            alignItems: "baseline",
                            gap: 8,
                            padding: "6px 10px",
                            borderTop: i === 0 ? "none" : `1px solid ${color.cardBorder}`,
                            cursor: jump ? "pointer" : "default",
                          }}
                        >
                          <span style={{ fontFamily: font.mono, fontSize: 10.5, color: color.muted,
                                         minWidth: 14 }}>
                            {i === 0 ? "" : "+"}
                          </span>
                          <span style={{ fontSize: 11.5, color: color.ink, flex: 1,
                                         textDecoration: jump ? "underline dotted" : "none" }}>
                            {c.label}
                          </span>
                          {c.residual ? (
                            <span style={{ fontSize: 9.5, fontWeight: 600, padding: "1px 6px",
                                           borderRadius: radius.pill, background: color.amberBg,
                                           color: color.amberFg }}>
                              routed
                            </span>
                          ) : null}
                          <span style={{ fontFamily: font.mono, fontSize: 11, color: color.sec2,
                                         minWidth: 46, textAlign: "right" }}>
                            {c.src}
                          </span>
                          <span style={{ fontFamily: font.mono, fontSize: 11.5, fontWeight: 600,
                                         color: color.ink, minWidth: 92, textAlign: "right" }}>
                            {present(c.v1)}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                ) : null}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
