/** Extracted data for one uploaded document — real line items with click-to-source
 * provenance. Clicking a PDF value opens a Source panel that renders that page and
 * highlights the value's bounding box. Mapping is against the seeded reference ontology.
 * Distinct from the demo-driven workspace: this reads a live extraction run. */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Card } from "../components/ui";
import { useT } from "../i18n";
import { api } from "../lib/api";
import { useExtraction, useOntologies, useTemplates } from "../lib/queries";
import { SCREENS } from "./config";
import { color, font } from "../theme";
import type { ExtractionProvenance, ExtractionRow } from "../types";

/** A value's source location, resolved to what the Source panel needs to render it. */
interface Picked {
  page_index: number;
  bbox: { x0: number; y0: number; x1: number; y1: number };
  label: string;
}

function SourceChip({ p, onPick }: { p: ExtractionProvenance | null; onPick?: () => void }) {
  if (!p) return <span style={{ color: color.faint }}>—</span>;
  const isPdf = p.source_kind !== "spreadsheet" && !!p.bbox;
  const label =
    p.source_kind === "spreadsheet" && p.sheet
      ? `${p.sheet}!${p.cell ?? ""}`
      : `p.${p.page_index + 1}${p.bbox ? " ⤢" : ""}`;
  return (
    <span
      onClick={isPdf ? onPick : undefined}
      role={isPdf ? "button" : undefined}
      title={p.text_snippet ?? undefined}
      style={{
        fontFamily: font.mono, fontSize: 10.5, color: color.indigo,
        background: color.indigoTint2, borderRadius: 5, padding: "2px 6px", whiteSpace: "nowrap",
        cursor: isPdf ? "pointer" : "default",
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
        {row.values.map((v, i) => (
          <span key={i} style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
            <span style={{ fontSize: 11.5, fontFamily: font.mono, color: color.ink }}>{v.value ?? "—"}</span>
            <SourceChip
              p={v.provenance}
              onPick={v.provenance?.bbox
                ? () => onPick({ page_index: v.provenance!.page_index, bbox: v.provenance!.bbox!, label: row.source_label })
                : undefined}
            />
          </span>
        ))}
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

/** Renders a PDF page image (auth'd fetch → blob URL) with the picked value's bbox drawn. */
function SourcePanel({ documentId, picked, t }: { documentId: string; picked: Picked | null; t: (k: string) => string }) {
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
    <div style={{ width: 420, flex: "0 0 420px", position: "sticky", top: 0, alignSelf: "flex-start" }}>
      <div style={{ fontSize: 10.5, fontWeight: 600, letterSpacing: 0.3, color: color.muted, margin: "0 0 8px" }}>
        {t("ex.col.source").toUpperCase()}
      </div>
      <Card pad={10}>
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
      </Card>
    </div>
  );
}

export default function ExtractionView() {
  const { id } = useParams();
  const nav = useNavigate();
  const t = useT();
  const [picked, setPicked] = useState<Picked | null>(null);

  const ontQ = useOntologies();
  const tplQ = useTemplates();
  const ready = ontQ.isFetched && tplQ.isFetched;   // don't POST until the lists settle
  const ont = ontQ.data?.find((o) => o.ontology_key === "hkfrs_hk_china_v1") ?? ontQ.data?.[0];
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
              <SourcePanel documentId={id} picked={picked} t={t} />
            )}
          </div>
        </>
      )}
    </div>
  );
}
