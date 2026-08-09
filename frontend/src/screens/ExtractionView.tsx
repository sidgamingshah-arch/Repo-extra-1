/** Extracted data for one uploaded document — real line items with click-to-source
 * provenance. Clicking a PDF value opens a Source panel that renders that page and
 * highlights the value's bounding box. Mapping is against the seeded reference ontology.
 * Distinct from the demo-driven workspace: this reads a live extraction run. */
import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Card } from "../components/ui";
import { useT } from "../i18n";
import { api } from "../lib/api";
import { useCellContext, useDocumentAnalysis, useExtraction, useOntologies, useTemplates } from "../lib/queries";
import { useUI } from "../store";
import { SCREENS } from "./config";
import { color, font } from "../theme";
import type { ExtractionProvenance, ExtractionRow, Locale } from "../types";

/** A value's source location, resolved to what the Source panel needs to render it.
 *  PDF sources carry a page + bbox; spreadsheet sources carry a sheet + cell. */
type Picked =
  | { kind: "pdf"; page_index: number; bbox: { x0: number; y0: number; x1: number; y1: number }; label: string }
  | { kind: "xlsx"; sheet: string; cell: string; label: string };

/** Resolve a provenance record to a Picked, or null if it isn't click-to-source-able. */
function toPicked(p: ExtractionProvenance | null, label: string): Picked | null {
  if (!p) return null;
  if (p.source_kind === "spreadsheet" && p.sheet && p.cell)
    return { kind: "xlsx", sheet: p.sheet, cell: p.cell, label };
  if (p.bbox) return { kind: "pdf", page_index: p.page_index, bbox: p.bbox, label };
  return null;
}

function SourceChip({ p, onPick }: { p: ExtractionProvenance | null; onPick?: () => void }) {
  if (!p) return <span style={{ color: color.faint }}>—</span>;
  const clickable = !!onPick;
  const label =
    p.source_kind === "spreadsheet" && p.sheet
      ? `${p.sheet}!${p.cell ?? ""}`
      : `p.${p.page_index + 1}${p.bbox ? " ⤢" : ""}`;
  return (
    <span
      onClick={onPick}
      role={clickable ? "button" : undefined}
      title={p.text_snippet ?? undefined}
      style={{
        fontFamily: font.mono, fontSize: 10.5, color: color.indigo,
        background: color.indigoTint2, borderRadius: 5, padding: "2px 6px", whiteSpace: "nowrap",
        cursor: clickable ? "pointer" : "default",
      }}
    >
      {label}
    </span>
  );
}

const GRID = "1.8fr 56px 1.3fr 1.1fr";

function RowLine({ row, t, onPick }: {
  row: ExtractionRow; t: (k: string) => string; onPick: (p: Picked) => void;
}) {
  const flagged = row.flags?.includes("low_mapping_confidence");
  return (
    <div style={{ display: "grid", gridTemplateColumns: GRID, gap: 10, padding: "9px 14px",
                  alignItems: "center", borderBottom: `1px solid ${color.hairline2}` }}>
      <span style={{ fontSize: 12.5, color: color.ink }}>{row.source_label}</span>
      <span style={{ fontSize: 11, fontFamily: font.mono, color: color.muted }}>{row.note ?? ""}</span>
      <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {row.values.map((v, i) => {
          const picked = toPicked(v.provenance, row.source_label);
          return (
            <span key={i} style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
              <span style={{ fontSize: 11.5, fontFamily: font.mono, color: color.ink }}>{v.value ?? "—"}</span>
              <SourceChip p={v.provenance} onPick={picked ? () => onPick(picked) : undefined} />
            </span>
          );
        })}
      </span>
      <span style={{ display: "flex", flexDirection: "column" }}>
        <span style={{ fontSize: 11.5, color: row.canonical_key ? color.ink2 : color.faint }}>
          {row.canonical_key ?? t("ex.unmapped")}
          {flagged && <span style={{ color: color.amberFg, marginInlineStart: 6 }}>⚠</span>}
        </span>
        {row.mapping_method && (
          <span style={{ fontSize: 9.5, fontFamily: font.mono, color: color.muted2 }}>{row.mapping_method}</span>
        )}
      </span>
    </div>
  );
}

type PdfPick = Extract<Picked, { kind: "pdf" }>;
type XlsxPick = Extract<Picked, { kind: "xlsx" }>;

/** Shared chrome for a source panel: sticky column with a heading and a card. */
function PanelShell({ t, children }: { t: (k: string) => string; children: React.ReactNode }) {
  return (
    <div style={{ width: 420, flex: "0 0 420px", position: "sticky", top: 0, alignSelf: "flex-start" }}>
      <div style={{ fontSize: 10.5, fontWeight: 600, letterSpacing: 0.3, color: color.muted, margin: "0 0 8px" }}>
        {t("ex.col.source").toUpperCase()}
      </div>
      <Card pad={10}>{children}</Card>
    </div>
  );
}

/** Renders a PDF page image (auth'd fetch → blob URL) with the picked value's bbox drawn. */
function SourcePanel({ documentId, picked, t }: { documentId: string; picked: PdfPick | null; t: (k: string) => string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    if (!picked) return;
    let objUrl: string | null = null;
    let cancelled = false;
    setErr(false);
    api.fetchPageImage(documentId, picked.page_index)
      .then((blob) => {
        if (cancelled) return;
        objUrl = URL.createObjectURL(blob);
        setUrl(objUrl);
      })
      .catch(() => !cancelled && setErr(true));
    return () => { cancelled = true; if (objUrl) URL.revokeObjectURL(objUrl); };
  }, [documentId, picked?.page_index]);  // eslint-disable-line react-hooks/exhaustive-deps

  const b = picked?.bbox;
  return (
    <PanelShell t={t}>
      {!picked && (
        <div style={{ fontSize: 12, color: color.muted, padding: "24px 8px", textAlign: "center" }}>
          {t("ex.pickHint")}
        </div>
      )}
      {picked && err && <div style={{ fontSize: 12, color: color.redFg }}>{t("ex.failed")}</div>}
      {picked && !err && (
        <>
          <div style={{ fontSize: 11, color: color.sec2, marginBottom: 8 }}>
            {picked.label} · p.{picked.page_index + 1}
          </div>
          <div style={{ position: "relative", display: "inline-block", width: "100%",
                        border: `1px solid ${color.hairline3}`, borderRadius: 6, overflow: "hidden" }}>
            {url && <img src={url} alt="" style={{ display: "block", width: "100%" }} />}
            {url && b && (
              <div data-testid="prov-highlight" style={{
                position: "absolute",
                left: `${b.x0 * 100}%`, top: `${b.y0 * 100}%`,
                width: `${(b.x1 - b.x0) * 100}%`, height: `${(b.y1 - b.y0) * 100}%`,
                border: `2px solid ${color.amberFg}`, background: "rgba(217,164,65,0.22)",
                borderRadius: 2, boxShadow: "0 0 0 1px rgba(0,0,0,0.05)",
              }} />
            )}
          </div>
        </>
      )}
    </PanelShell>
  );
}

/** Spreadsheet click-to-source: renders a small window of cells around the value's origin
 * with the target cell highlighted — the Excel analogue of the PDF page overlay. */
function ExcelSourcePanel({ documentId, picked, t }: { documentId: string; picked: XlsxPick | null; t: (k: string) => string }) {
  const q = useCellContext(documentId, picked?.sheet, picked?.cell);
  return (
    <PanelShell t={t}>
      {!picked && (
        <div style={{ fontSize: 12, color: color.muted, padding: "24px 8px", textAlign: "center" }}>
          {t("ex.pickHint")}
        </div>
      )}
      {picked && q.isError && <div style={{ fontSize: 12, color: color.redFg }}>{t("ex.failed")}</div>}
      {picked && q.isPending && !q.isError && (
        <div style={{ fontSize: 12, color: color.muted, padding: "18px 8px" }}>{t("ex.running")}</div>
      )}
      {picked && q.data && (
        <>
          <div style={{ fontSize: 11, color: color.sec2, marginBottom: 8 }}>
            {picked.label} · <span style={{ fontFamily: font.mono }}>{q.data.sheet}!{q.data.target}</span>
          </div>
          <div style={{ overflowX: "auto", border: `1px solid ${color.hairline3}`, borderRadius: 6 }}>
            <table style={{ borderCollapse: "collapse", fontSize: 10.5, fontFamily: font.mono, width: "100%" }}>
              <thead>
                <tr>
                  <th style={cellSt(false, true)}></th>
                  {q.data.col_letters.map((c) => (
                    <th key={c} style={cellSt(false, true)}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {q.data.grid.map((line, r) => (
                  <tr key={r}>
                    <td style={cellSt(false, true)}>{q.data!.row_numbers[r]}</td>
                    {line.map((cell) => (
                      <td key={cell.ref}
                          data-testid={cell.is_target ? "cell-target" : undefined}
                          title={cell.ref}
                          style={{
                            ...cellSt(cell.is_target, false),
                            textAlign: cell.numeric ? "right" : "left",
                          }}>
                        {cell.value.length > 22 ? cell.value.slice(0, 21) + "…" : cell.value}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </PanelShell>
  );
}

function cellSt(target: boolean, header: boolean): React.CSSProperties {
  return {
    border: `1px solid ${color.hairline2}`,
    padding: "3px 6px",
    whiteSpace: "nowrap",
    maxWidth: 130,
    overflow: "hidden",
    textOverflow: "ellipsis",
    background: target ? "rgba(217,164,65,0.22)" : header ? color.rowAltBg : undefined,
    color: header ? color.muted : color.ink,
    fontWeight: target ? 700 : header ? 600 : 400,
    outline: target ? `2px solid ${color.amberFg}` : undefined,
  };
}

/** Derived analysis (computed from the extracted values): ratios, qualitative disclosures,
 * and free-form notes — the on-screen twin of the export's Ratios/Disclosures/Notes sheets. */
function AnalysisSection({ id, locale, t }: { id: string; locale: Locale; t: (k: string) => string }) {
  const q = useDocumentAnalysis(id, locale);
  if (!q.data) return null;
  const { ratios, disclosures, notes } = q.data;
  const card: React.CSSProperties = { };
  return (
    <div style={{ marginTop: 22, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
      <Card style={card}>
        <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: 0.3, color: color.muted, marginBottom: 10 }}>
          {t("ex.ratios")}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          {ratios.map((r) => (
            <div key={r.key} title={r.formula}
                 style={{ border: `1px solid ${color.hairline3}`, borderRadius: 8, padding: "8px 10px",
                          opacity: r.available ? 1 : 0.55 }}>
              <div style={{ fontSize: 15, fontWeight: 700, fontFamily: font.mono,
                            color: r.available ? color.ink : color.faint }}>{r.display}</div>
              <div style={{ fontSize: 10.5, color: color.sec2 }}>{r.label}</div>
            </div>
          ))}
        </div>
      </Card>

      <Card style={card}>
        <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: 0.3, color: color.muted, marginBottom: 10 }}>
          {t("ex.highlights")}
        </div>
        {notes.map((n, i) => (
          <div key={i} style={{ marginBottom: 9 }}>
            <div style={{ fontSize: 11.5, fontWeight: 600, color: color.ink }}>{n.title}</div>
            <div style={{ fontSize: 11.5, color: color.sec2, lineHeight: 1.5 }}>{n.text}</div>
          </div>
        ))}
      </Card>

      <Card style={{ gridColumn: "1 / -1" }}>
        <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: 0.3, color: color.muted, marginBottom: 10 }}>
          {t("ex.disclosures")}
        </div>
        {disclosures.map((d) => (
          <div key={d.key} style={{ display: "grid", gridTemplateColumns: "1.4fr 70px 2.5fr",
                                    gap: 10, alignItems: "center", padding: "6px 0",
                                    borderBottom: `1px solid ${color.hairline2}` }}>
            <span style={{ fontSize: 12, color: color.ink }}>{d.label}</span>
            <span style={{ fontSize: 10.5, fontWeight: 700,
                           color: d.present ? color.greenFg : color.faint }}>
              {d.present ? `p.${d.page}` : "—"}
            </span>
            <span style={{ fontSize: 11, color: color.muted, fontStyle: d.snippet ? "italic" : "normal",
                           whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {d.snippet || t("ex.notFound")}
            </span>
          </div>
        ))}
      </Card>
    </div>
  );
}

export default function ExtractionView() {
  const { id } = useParams();
  const nav = useNavigate();
  const t = useT();
  const outputLocale = useUI((s) => s.locale);
  const [picked, setPicked] = useState<Picked | null>(null);

  const ontQ = useOntologies();
  const tplQ = useTemplates();
  const selectedTemplateKey = useUI((s) => s.selectedTemplateKey);
  const ready = ontQ.isFetched && tplQ.isFetched;   // don't POST until the lists settle
  // Prefer the ontology targeting the template the analyst selected on the Upload screen;
  // fall back to the shipped HK reference ontology, then whatever is first.
  const ont =
    (selectedTemplateKey && ontQ.data?.find((o) => o.target_template_key === selectedTemplateKey)) ||
    ontQ.data?.find((o) => o.ontology_key === "hkfrs_hk_china_v1") ||
    ontQ.data?.[0];
  const tpl = ont ? tplQ.data?.find((tt) => tt.template_key === ont.target_template_key) : undefined;
  const { data, isPending, isError, error } = useExtraction(id, ont?.id, tpl?.id, ready);

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto", padding: "22px 30px 60px" }}>
      <button onClick={() => nav(SCREENS.upload.path)}
              style={{ fontSize: 12, color: color.indigo, background: "none", border: "none", cursor: "pointer", padding: 0, marginBottom: 12 }}>
        {t("ex.back")}
      </button>

      {(isPending || !ready) && (
        <div style={{ padding: 50, textAlign: "center", color: color.muted }}>{t("ex.running")}</div>
      )}
      {isError && (
        <div style={{ padding: "12px 14px", background: color.redBg, color: color.redFg, borderRadius: 9, fontSize: 12.5 }}>
          <b>{t("ex.failed")}.</b>{" "}
          <span style={{ fontFamily: font.mono, fontSize: 11 }}>{(error as Error)?.message}</span>
        </div>
      )}

      {data && (
        <>
          <div style={{ marginBottom: 16 }}>
            <h1 style={{ fontSize: 19, fontWeight: 600, margin: "0 0 4px" }}>{t("ex.title")}</h1>
            <p style={{ margin: 0, color: color.sec2, fontSize: 12.5 }}>
              <span style={{ fontFamily: font.mono }}>{data.result.filename}</span>
              {"  ·  "}{data.result.format.toUpperCase()}
              {"  ·  "}{data.result.line_item_count} {t("ex.count")}
            </p>
          </div>
          <div style={{ display: "flex", gap: 18, alignItems: "flex-start" }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <Card pad={0} style={{ overflow: "hidden" }}>
                <div style={{ display: "grid", gridTemplateColumns: GRID, gap: 10, padding: "10px 14px",
                              background: color.rowAltBg, borderBottom: `1px solid ${color.hairline2}`,
                              fontSize: 10, fontWeight: 600, letterSpacing: 0.3, color: color.muted }}>
                  <span>{t("ex.col.lineitem")}</span>
                  <span>{t("ex.col.note")}</span>
                  <span>{t("ex.col.value")} · {t("ex.col.source")}</span>
                  <span>{t("ex.col.mapping")}</span>
                </div>
                {data.result.rows.length === 0 && (
                  <div style={{ padding: "18px 14px", fontSize: 12.5, color: color.muted }}>{t("ex.empty")}</div>
                )}
                {data.result.rows.map((row, i) => (
                  <RowLine key={i} row={row} t={t} onPick={setPicked} />
                ))}
              </Card>
            </div>
            {data.result.format === "pdf" && id && (
              <SourcePanel documentId={id} picked={picked?.kind === "pdf" ? picked : null} t={t} />
            )}
            {(data.result.format === "xlsx" || data.result.format === "xls") && id && (
              <ExcelSourcePanel documentId={id} picked={picked?.kind === "xlsx" ? picked : null} t={t} />
            )}
          </div>
          {id && <AnalysisSection id={id} locale={outputLocale} t={t} />}
        </>
      )}
    </div>
  );
}
