/** Extracted data for one uploaded document — real line items with click-to-source
 * provenance. Clicking a PDF value opens a Source panel that renders that page and
 * highlights the value's bounding box. Mapping runs against the rulebook in force for the
 * selected template, or whichever one the reader pins here instead (see RulebookPicker).
 * Distinct from the demo-driven workspace: this reads a live extraction run. */
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Card } from "../components/ui";
import { ExcelSourcePanel, PagedSource, toPicked, type Picked } from "../components/SourceViewer";
import { useT } from "../i18n";
import {
  ontologyInForce, useDocumentAnalysis, useExtraction, useOntologies, useTemplates,
} from "../lib/queries";
import { useUI } from "../store";
import { SCREENS } from "./config";
import { color, font } from "../theme";
import type { ExtractionRow, Locale, OntologyRef } from "../types";

const GRID = "1.8fr 56px 1.3fr 1.1fr";

/** Digit grouping follows the FILING, not the app: Indian filings group as 12,68,100 while
 *  IFRS/HKFRS filings group as 1,268,100. Rendering an HK filing with Indian grouping would
 *  misrepresent the printed figure, so the source currency selects the convention. */
function groupingLocale(currency: string | undefined): string {
  return currency === "INR" ? "en-IN" : "en-US";
}

/** Format an extracted figure for reading: grouped digits, negatives in parentheses (the
 *  accounting convention used elsewhere in the app). Anything non-numeric is passed through
 *  unchanged rather than coerced — a caption that failed to parse must not become "0". */
function fmtFigure(raw: string | null, loc: string): string {
  if (raw == null || raw === "") return "—";
  const n = Number(raw);
  if (!Number.isFinite(n)) return raw;
  const abs = Math.abs(n).toLocaleString(loc, { maximumFractionDigits: 2 });
  return n < 0 ? `(${abs})` : abs;
}

function RowLine({ row, t, onPick, loc }: {
  row: ExtractionRow; t: (k: string) => string; onPick: (p: Picked) => void; loc: string;
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
              title={[v.value != null ? `as printed: ${v.value}` : "", confTip,
                       clickable ? "click to show in source" : ""]
                       .filter(Boolean).join(" · ") || undefined}
              style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline",
                       gap: 8, cursor: clickable ? "pointer" : "default" }}
            >
              <span style={{ fontSize: 11.5, fontFamily: font.mono, color: low ? color.amberFg : color.ink,
                             borderBottom: clickable ? `1px dashed ${color.indigoBorder2}` : undefined }}>
                {fmtFigure(v.value, loc)}{low ? " ⚠" : ""}
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

/** Which rulebook a run reads the filing against, and why.
 *
 *  Until this existed the answer was a property of the configuration: whichever rulebook declared
 *  itself the successor won, and nobody could pin an older one, or read one filing against two of
 *  them to see what changed. The default is still the rulebook in force — computed by the ONE
 *  shared rule (see `ontologyInForce`), not a local copy of it — and the note says which that is
 *  and on what grounds, because "in force" is a claim the screen has to be able to back up.
 *
 *  Choosing is not cosmetic: `ontology_version_id` travels with the POST that starts the run, so
 *  the pick decides the rules the mapper reasons with. Each choice is its own cached run, which is
 *  what makes comparing two of them on one filing a matter of switching back and forth.
 */
function RulebookPicker({ rows, inForce, chosen, onChoose, templateKey, t }: {
  rows: OntologyRef[]; inForce: OntologyRef | undefined; chosen: OntologyRef | undefined;
  onChoose: (id: string) => void; templateKey: string | undefined; t: (k: string) => string;
}) {
  const pinned = !!chosen && !!inForce && chosen.id !== inForce.id;
  // Newest-looking first, and stable: same key together, highest version on top.
  const sorted = [...rows].sort((a, b) => (a.ontology_key === b.ontology_key
    ? b.version - a.version
    : a.ontology_key.localeCompare(b.ontology_key)));

  const why = !chosen ? t("tp.rb.none")
    : pinned ? t("tp.rb.whyPinned")
        .replace("{key}", inForce?.ontology_key ?? "").replace("{v}", String(inForce?.version ?? ""))
    : chosen.supersedes ? t("tp.rb.whySupersedes").replace("{old}", chosen.supersedes)
    : t("tp.rb.whyVersion").replace("{tpl}", chosen.target_template_key);

  return (
    <div data-testid="ex-rulebook"
         style={{ display: "flex", alignItems: "baseline", gap: 9, flexWrap: "wrap",
                  marginBottom: 12 }}>
      <span style={{ fontSize: 11, color: color.muted }}>{t("tp.rb.label")}</span>
      <select
        data-testid="ex-rulebook-pick"
        value={chosen?.id ?? ""}
        onChange={(e) => onChoose(e.target.value)}
        style={{ fontSize: 12, fontWeight: 600, padding: "5px 9px", borderRadius: 7,
                 border: `1px solid ${color.controlBorder}`, background: "#fff", color: color.ink,
                 maxWidth: 420 }}
      >
        {!chosen && <option value="">{t("tp.rb.none")}</option>}
        {sorted.map((o) => (
          <option key={o.id} value={o.id}>
            {`${o.ontology_key} · v${o.version}`}
            {o.id === inForce?.id ? ` — ${t("tp.rb.inForce")}` : ""}
            {o.superseded ? ` — ${t("tp.rb.superseded")}` : ""}
            {templateKey && o.target_template_key !== templateKey
              ? ` — ${t("tp.rb.otherTemplate").replace("{tpl}", o.target_template_key)}` : ""}
          </option>
        ))}
      </select>
      <span data-testid="ex-rulebook-why"
            style={{ fontSize: 11, color: pinned ? color.amberFg : color.muted2, maxWidth: 620,
                     lineHeight: 1.5 }}>
        {pinned ? `${t("tp.rb.pinned")} — ${why}` : why}
      </span>
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
  // The rulebook a run DEFAULTS to: the one in force for the template the analyst selected on the
  // Upload screen; failing that the shipped HK reference rulebook, then whatever exists. "In
  // force" is one shared rule (see ontologyInForce) — the copy that used to live here compared
  // versions, which cannot rank two different rulebooks that target the same template.
  const inForce =
    ontologyInForce(ontQ.data, (o) => o.target_template_key === selectedTemplateKey) ||
    ontologyInForce(ontQ.data, (o) => o.ontology_key === "hkfrs_hk_china_v1") ||
    ontologyInForce(ontQ.data);
  // …and the one the reader PINNED, which outranks it. Empty means "follow whatever is in force",
  // so publishing a new rulebook moves an unpinned reader forward rather than freezing them.
  const [pinnedId, setPinnedId] = useState("");
  const ont = (pinnedId ? ontQ.data?.find((o) => o.id === pinnedId) : undefined) ?? inForce;
  const tpl = ont ? tplQ.data?.find((tt) => tt.template_key === ont.target_template_key) : undefined;
  const { data, isPending, isError, error } = useExtraction(id, ont?.id, tpl?.id, ready);

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto", padding: "22px 30px 60px" }}>
      <button onClick={() => nav(SCREENS.upload.path)}
              style={{ fontSize: 12, color: color.indigo, background: "none", border: "none", cursor: "pointer", padding: 0, marginBottom: 12 }}>
        {t("ex.back")}
      </button>

      {/* Above the results, and present while one is still running: which rulebook governs this
          run is a decision, so it belongs where the run is, not only in a file on the server. */}
      {ontQ.data && ontQ.data.length > 0 && (
        <RulebookPicker
          rows={ontQ.data} inForce={inForce} chosen={ont} onChoose={setPinnedId}
          templateKey={selectedTemplateKey ?? tpl?.template_key} t={t}
        />
      )}

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

          {/* How mapping ran. A deterministic-only run (no LLM configured) is materially
              weaker at resolving captions by meaning, so it is stated rather than implied. */}
          {res.mapping && res.mapping.strategy !== "llm_description" && (
            <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap",
                          background: color.amberBg, border: `1px solid ${color.amberFg}33`,
                          borderRadius: 8, padding: "8px 11px", marginBottom: 12 }}>
              <b style={{ fontSize: 11.5, color: color.amberFg }}>{t("ex.detMapping")}</b>
              <span style={{ fontSize: 11.5, color: color.sec2 }}>{t("ex.detMappingHint")}</span>
              {res.mapping.reason && (
                <span style={{ fontFamily: font.mono, fontSize: 10.5, color: color.muted }}>
                  ({res.mapping.reason})
                </span>
              )}
            </div>
          )}

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
                  <RowLine key={i} row={row} t={t} onPick={setPicked}
                           loc={groupingLocale(u?.currency)} />
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
