/** Screen 4 — Workspace. The core extraction screen: source viewer (left) + editable
 * output panel with a cell inspector (right). Full-height flex layout, not a padded page.
 * Mirrors wireframe scrExtract + OUTPUT + SELINFO verbatim, data-driven from useStatement. */
import { useEffect, useRef, useState, type MouseEvent } from "react";
import { useNavigate } from "react-router-dom";

import { ConfidencePill, NoteChip, Segmented, StatusIcon } from "../components/ui";
import { EmptyState } from "../components/EmptyState";
import { color, confStyle, font, layout, radius, shadow, fmtIN, fmtPlain, parseAccounting } from "../theme";
import type { Basis, StatementKey, StatementResponse, StatementRow } from "../types";
import { useStatement, useEditLineItem, useProjectLoaded } from "../lib/queries";
import { useUI } from "../store";
import { useT } from "../i18n";
import { SCREENS } from "./config";

/* ---- toolbar display-only field chip (e.g. currency, which is source-derived) ---- */
function ToolChip({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        fontSize: 12,
        color: color.sec,
        border: `1px solid ${color.cardBorder}`,
        borderRadius: radius.control,
        padding: "6px 11px",
      }}
    >
      <span style={{ color: color.muted }}>{label}</span>
      <span style={{ fontWeight: 600 }}>{value}</span>
    </div>
  );
}

/* ---- click-to-source chip on a value: drives the source viewer (left paper) to the
 * matching line, mirroring the SourceChip affordance used on the extraction screen. ---- */
function SourceChip({ onClick }: { onClick: (e: MouseEvent) => void }) {
  return (
    <span
      onClick={onClick}
      role="button"
      title="View in source document"
      style={{
        fontFamily: font.mono,
        fontSize: 10,
        color: color.indigo,
        background: color.indigoTint2,
        borderRadius: 5,
        padding: "1px 5px",
        whiteSpace: "nowrap",
        cursor: "pointer",
      }}
    >
      ⤢
    </span>
  );
}

/* ---- left source-viewer "paper" row ---- */
function PaperRow({ row, selected, pickTick }: { row: StatementRow; selected: boolean; pickTick: number }) {
  const ref = useRef<HTMLDivElement>(null);
  // Scroll the source paper to this line whenever it becomes selected, and re-scroll on
  // every explicit source pick (pickTick) even if the same row is already selected.
  useEffect(() => {
    if (selected) ref.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [selected, pickTick]);
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
      ref={ref}
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

/* ---- right output-panel row ---- */
function OutputRow({
  row,
  sel,
  unitScale,
  onSelect,
  onEdit,
  onOpenNote,
  onPickSource,
}: {
  row: StatementRow;
  sel: string;
  unitScale: number;
  onSelect: (id: string) => void;
  onEdit: (id: string) => void;
  onOpenNote: (ref: string) => void;
  onPickSource: (id: string) => void;
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
  // Presentation-only magnitude: divide the raw stored value before formatting.
  const scaled = (n: number | null): number | null => (n == null ? null : n / unitScale);
  const v1 = showV ? fmtIN(scaled(row.v1)) : "";
  const v2 = showV ? fmtIN(scaled(row.v2)) : "";
  const note = row.note ?? row.note2;
  const showChip = isItem && row.v1 != null;

  return (
    <div
      onClick={() => onSelect(row.id)}
      style={{
        display: "grid",
        gridTemplateColumns: layout.gridCols,
        alignItems: "center",
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
      <div style={{ textAlign: "center" }}>
        {note ? (
          <NoteChip onClick={(e) => { e?.stopPropagation(); onOpenNote(note!); }}>{note}</NoteChip>
        ) : null}
      </div>
      {isItem ? (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 6, minWidth: 0 }}>
          {showChip && (
            <SourceChip
              onClick={(e) => {
                e.stopPropagation();
                onPickSource(row.id);
              }}
            />
          )}
          <span
            onClick={(e) => {
              e.stopPropagation();
              onEdit(row.id);
            }}
            title="Click to edit value"
            style={{
              textAlign: "right",
              fontFamily: font.mono,
              fontSize: 12,
              fontWeight: vwt,
              color: vfg,
              cursor: "text",
              borderBottom: `1px dashed ${selected ? color.indigo : "transparent"}`,
            }}
          >
            {v1}
          </span>
        </div>
      ) : (
        <span style={{ textAlign: "right", fontFamily: font.mono, fontSize: 12, fontWeight: vwt, color: vfg }}>
          {v1}
        </span>
      )}
      <span style={{ textAlign: "right", fontFamily: font.mono, fontSize: 12, color: color.muted }}>{v2}</span>
      <div style={{ textAlign: "right" }}>
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
  const { locale, dataset, setDataset, statement, setStatement, sel, selRow, selForEdit, editing, startEdit, cancelEdit, stopEditing, setNote } =
    useUI();
  // Presentation-only display magnitude (does not touch stored/raw values). 1 = as reported.
  const [unitScale, setUnitScale] = useState(1);
  // Bumped on every source-chip click so the source viewer re-scrolls even for the
  // already-selected row. Selecting a line also drives the source viewer via `sel`.
  const [pickTick, setPickTick] = useState(0);
  const pickSource = (id: string) => {
    selRow(id);
    setPickTick((n) => n + 1);
  };
  // Open a note reference: select it and jump to the All Notes screen.
  const openNote = (ref: string) => {
    const n = parseInt(ref, 10);
    if (!Number.isNaN(n)) {
      setNote(n);
      navigate(SCREENS.notes.path);
    }
  };
  const loaded = useProjectLoaded();
  const { data, isPending } = useStatement(statement, dataset, locale);
  const editMut = useEditLineItem();

  if (!loaded) return <EmptyState />;
  if (isPending || !data) {
    return <div style={{ padding: 60, textAlign: "center", color: color.muted }}>Loading…</div>;
  }

  const d: StatementResponse = data;
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
            { value: "balance_sheet", label: t("ws.stmt.balanceSheet") },
            { value: "profit_and_loss", label: t("ws.stmt.profitLoss") },
            { value: "cash_flow", label: t("ws.stmt.cashFlow") },
          ]}
          value={statement}
          onChange={setStatement}
        />
        <ToolChip label={t("ws.currency")} value={`${d.currency} ${d.currency_symbol}`} />
        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontSize: 12,
            color: color.sec,
            border: `1px solid ${color.cardBorder}`,
            borderRadius: radius.control,
            padding: "4px 9px",
          }}
        >
          <span style={{ color: color.muted }}>{t("ws.units")}</span>
          <select
            value={unitScale}
            onChange={(e) => setUnitScale(Number(e.target.value))}
            style={{
              fontSize: 12,
              fontWeight: 600,
              fontFamily: font.sans,
              color: color.ink,
              border: "none",
              background: "transparent",
              outline: "none",
              cursor: "pointer",
            }}
          >
            <option value={1}>{t("ws.units.asReported")}</option>
            <option value={1e3}>{t("ws.units.thousands")}</option>
            <option value={1e6}>{t("ws.units.millions")}</option>
            <option value={1e9}>{t("ws.units.billions")}</option>
          </select>
        </label>
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
            3 {t("ws.lowconf")}
          </span>
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
            <span style={{ fontSize: 11.5, fontWeight: 600 }}>AnnualReport_RIL_FY25.pdf</span>
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
                <PaperRow key={r.id} row={r} selected={r.id === sel} pickTick={pickTick} />
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
            <span style={{ textAlign: "center" }}>{t("col.note")}</span>
            <span style={{ textAlign: "right" }}>{d.periods[0]}</span>
            <span style={{ textAlign: "right" }}>{d.periods[1]}</span>
            <span style={{ textAlign: "right" }}>{t("col.conf")}</span>
          </div>

          {/* scroll body */}
          <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
            {d.rows.map((r) => (
              <OutputRow
                key={r.id}
                row={r}
                sel={sel}
                unitScale={unitScale}
                onSelect={selRow}
                onEdit={selForEdit}
                onOpenNote={openNote}
                onPickSource={pickSource}
              />
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
                {!editing && (
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

            {editing && selRowObj ? (
              <InspectorEditor
                key={selRowObj.id}
                row={selRowObj}
                onSave={(value, formula) => {
                  editMut.mutate({ id: selRowObj.id, value, formula });
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
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
