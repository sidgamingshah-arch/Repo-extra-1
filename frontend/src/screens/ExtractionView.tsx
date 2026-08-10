/** Extracted data for one uploaded document — real line items with click-to-source
 * provenance. Clicking a PDF value opens a Source panel that renders that page and
 * highlights the value's bounding box. Mapping is against the seeded reference ontology.
 * Distinct from the demo-driven workspace: this reads a live extraction run. */
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Card } from "../components/ui";
import { ExcelSourcePanel, PagedSource, toPicked, type Picked } from "../components/SourceViewer";
import { useT } from "../i18n";
import { useDocumentAnalysis, useExtraction, useOntologies, useTemplates } from "../lib/queries";
import { useUI } from "../store";
import { SCREENS } from "./config";
import { color, font } from "../theme";
import type { ExtractionRow, Locale } from "../types";

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
          const conf = v.confidence;
          // A value that participates in a failed check (balance / note tie) is flagged so a
          // doubtful number reads at a glance — per value, not just per row.
          const low = conf && (conf.flags.length > 0 || conf.overall < 0.75);
          const confTip = conf
            ? `confidence ${Math.round(conf.overall * 100)}%${conf.flags.length ? " · " + conf.flags.join(", ") : ""}`
            : "";
          const p = v.provenance;
          // The figure itself is the click-to-source link — click the number to jump to it in
          // the page image. A light page/cell ref sits beside it (no heavy chip).
          const ref = p
            ? p.source_kind === "spreadsheet" && p.sheet
              ? `${p.sheet}!${p.cell ?? ""}`
              : `p.${p.page_index + 1}`
            : null;
          const clickable = !!picked;
          return (
            <span
              key={i}
              onClick={clickable ? () => onPick(picked!) : undefined}
              role={clickable ? "button" : undefined}
              title={[confTip, clickable ? "click to show in source" : ""].filter(Boolean).join(" · ") || undefined}
              style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline",
                       gap: 8, cursor: clickable ? "pointer" : "default" }}
            >
              <span style={{ fontSize: 11.5, fontFamily: font.mono, color: low ? color.amberFg : color.ink,
                             borderBottom: clickable ? `1px dashed ${color.indigoBorder2}` : undefined }}>
                {v.value ?? "—"}{low ? " ⚠" : ""}
              </span>
              {ref && (
                <span style={{ fontFamily: font.mono, fontSize: 10, color: clickable ? color.indigo : color.muted2,
                               whiteSpace: "nowrap" }}>
                  {ref}{p?.bbox ? " ⤢" : ""}
                </span>
              )}
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

/** Localized heading for a ratio category (backend sends the English category name). */
const CAT_KEY: Record<string, string> = {
  Liquidity: "ex.cat.liquidity", Leverage: "ex.cat.leverage", Coverage: "ex.cat.coverage",
  Efficiency: "ex.cat.efficiency", Profitability: "ex.cat.profitability",
};

/** Derived analysis (computed from the extracted values): ratios, qualitative disclosures,
 * and free-form notes — the on-screen twin of the export's Ratios/Disclosures/Notes sheets. */
function AnalysisSection({ id, locale, t }: { id: string; locale: Locale; t: (k: string) => string }) {
  const q = useDocumentAnalysis(id, locale);
  // Reserve the section's footprint with a skeleton while the (separate) analysis query loads,
  // so it fills in place instead of popping in below and pushing the layout.
  if (!q.data) {
    if (q.isError) return null;
    const bar = (w: string, h = 12) => (
      <div style={{ width: w, height: h, borderRadius: 5, background: color.rowAltBg }} />
    );
    return (
      <div style={{ marginTop: 22, display: "grid", gap: 18 }} aria-hidden>
        {[0, 1, 2].map((k) => (
          <Card key={k}>
            <div style={{ display: "grid", gap: 10 }}>
              {bar("120px", 14)}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 8 }}>
                {[0, 1, 2, 3].map((j) => (
                  <div key={j} style={{ border: `1px solid ${color.hairline3}`, borderRadius: 8,
                                        padding: "8px 10px", display: "grid", gap: 6 }}>
                    {bar("60%", 16)}{bar("80%", 10)}
                  </div>
                ))}
              </div>
            </div>
          </Card>
        ))}
      </div>
    );
  }
  const { ratios, disclosures, notes } = q.data;

  // Group ratios by category, preserving the backend's category ordering.
  const groups: { cat: string; items: typeof ratios }[] = [];
  for (const r of ratios) {
    const cat = r.category || "Profitability";
    let g = groups.find((x) => x.cat === cat);
    if (!g) { g = { cat, items: [] }; groups.push(g); }
    g.items.push(r);
  }

  return (
    <div style={{ marginTop: 22, display: "grid", gap: 18 }}>
      <Card>
        <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: 0.3, color: color.muted, marginBottom: 10 }}>
          {t("ex.ratios")}
        </div>
        {groups.map((g) => (
          <div key={g.cat} style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: 0.4, textTransform: "uppercase",
                          color: color.sec2, marginBottom: 6 }}>
              {t(CAT_KEY[g.cat] || "") || g.cat}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 8 }}>
              {g.items.map((r) => (
                <div key={r.key} title={r.formula}
                     style={{ border: `1px solid ${color.hairline3}`, borderRadius: 8, padding: "8px 10px",
                              opacity: r.available ? 1 : 0.5 }}>
                  <div style={{ fontSize: 15, fontWeight: 700, fontFamily: font.mono,
                                color: r.available ? color.ink : color.faint }}>{r.display}</div>
                  <div style={{ fontSize: 10.5, color: color.sec2 }}>{r.label}</div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </Card>

      <Card>
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

      <Card>
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

/** Known canonical-key prefixes → statement labels for the filter dropdown. */
const STMT_LABELS: Record<string, string> = {
  bs: "Balance sheet", pl: "Profit & loss", cf: "Cash flow", eq: "Changes in equity",
};

export default function ExtractionView() {
  const { id } = useParams();
  const nav = useNavigate();
  const t = useT();
  const outputLocale = useUI((s) => s.locale);
  const [picked, setPicked] = useState<Picked | null>(null);
  const [stmt, setStmt] = useState<string>("all");   // statement filter (by canonical prefix)

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

      {data && (() => {
        const res = data.result;
        const u = res.units;
        // Statement filter options: the canonical-key prefixes actually present, plus
        // All / Unmapped. Prefix-based so it tracks whatever template the run used.
        const prefixes = Array.from(
          new Set(res.rows.map((r) => r.canonical_key?.split("_")[0]).filter(Boolean) as string[]),
        );
        const shown = res.rows.filter((r) =>
          stmt === "all" ? true
            : stmt === "unmapped" ? !r.canonical_key
              : r.canonical_key?.startsWith(`${stmt}_`));
        return (
        <>
          <div style={{ marginBottom: 14 }}>
            <h1 style={{ fontSize: 20, fontWeight: 600, margin: "0 0 4px" }}>
              {res.entity || t("ex.title")}
            </h1>
            <p style={{ margin: 0, color: color.sec2, fontSize: 12.5 }}>
              <span style={{ fontFamily: font.mono }}>{res.filename}</span>
              {"  ·  "}{res.format.toUpperCase()}
              {"  ·  "}{res.line_item_count} {t("ex.count")}
              {u?.currency && <>{"  ·  "}<b>{u.currency}</b></>}
              {u?.units_label && <>{"  ·  "}{t("ex.inUnits")} {u.units_label}</>}
            </p>
          </div>

          {/* Statement filter */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
            <span style={{ fontSize: 11, color: color.muted }}>{t("ex.statement")}</span>
            <select value={stmt} onChange={(e) => setStmt(e.target.value)}
                    style={{ fontSize: 12, padding: "5px 9px", borderRadius: 7,
                             border: `1px solid ${color.controlBorder}`, background: "#fff", color: color.ink }}>
              <option value="all">{t("ex.allStatements")}</option>
              {prefixes.map((p) => (
                <option key={p} value={p}>{STMT_LABELS[p] || p.toUpperCase()}</option>
              ))}
              <option value="unmapped">{t("ex.unmapped")}</option>
            </select>
            <span style={{ fontSize: 11, color: color.muted2 }}>{shown.length} / {res.rows.length}</span>
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
                {shown.length === 0 && (
                  <div style={{ padding: "18px 14px", fontSize: 12.5, color: color.muted }}>{t("ex.empty")}</div>
                )}
                {shown.map((row, i) => (
                  <RowLine key={i} row={row} t={t} onPick={setPicked} />
                ))}
              </Card>
            </div>
            {res.format === "pdf" && id && (
              <PagedSource documentId={id} pageCount={res.page_count ?? 1}
                           picked={picked?.kind === "pdf" ? picked : null} t={t} />
            )}
            {(res.format === "xlsx" || res.format === "xls") && id && (
              <ExcelSourcePanel documentId={id} picked={picked?.kind === "xlsx" ? picked : null} t={t} />
            )}
          </div>
          {id && <AnalysisSection id={id} locale={outputLocale} t={t} />}
        </>
        );
      })()}
    </div>
  );
}
