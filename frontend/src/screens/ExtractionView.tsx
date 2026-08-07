/** Extracted data for one uploaded document — its real line items with click-to-source
 * provenance (sheet!cell for Excel, page + bbox for PDF). Distinct from the demo-driven
 * workspace: this reads a live extraction run over the uploaded file. */
import { useNavigate, useParams } from "react-router-dom";

import { Card } from "../components/ui";
import { useT } from "../i18n";
import { useExtraction } from "../lib/queries";
import { SCREENS } from "./config";
import { color, font } from "../theme";
import type { ExtractionProvenance, ExtractionRow } from "../types";

/** A compact, click-to-source provenance chip. */
function SourceChip({ p }: { p: ExtractionProvenance | null }) {
  if (!p) return <span style={{ color: color.faint }}>—</span>;
  const label =
    p.source_kind === "spreadsheet" && p.sheet
      ? `${p.sheet}!${p.cell ?? ""}`
      : `p.${p.page_index + 1}${p.bbox ? " ⤢" : ""}`;
  return (
    <span
      title={p.text_snippet ?? undefined}
      style={{
        fontFamily: font.mono, fontSize: 10.5, color: color.indigo,
        background: color.indigoTint2, borderRadius: 5, padding: "2px 6px", whiteSpace: "nowrap",
      }}
    >
      {label}
    </span>
  );
}

const GRID = "1.8fr 56px 1.3fr 1.1fr";

function RowLine({ row, t }: { row: ExtractionRow; t: (k: string) => string }) {
  const flagged = row.flags?.includes("low_mapping_confidence");
  return (
    <div
      style={{
        display: "grid", gridTemplateColumns: GRID, gap: 10, padding: "9px 14px",
        alignItems: "center", borderBottom: `1px solid ${color.hairline2}`,
      }}
    >
      <span style={{ fontSize: 12.5, color: color.ink }}>{row.source_label}</span>
      <span style={{ fontSize: 11, fontFamily: font.mono, color: color.muted }}>{row.note ?? ""}</span>
      <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {row.values.map((v, i) => (
          <span key={i} style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
            <span style={{ fontSize: 11.5, fontFamily: font.mono, color: color.ink }}>{v.value ?? "—"}</span>
            <SourceChip p={v.provenance} />
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

export default function ExtractionView() {
  const { id } = useParams();
  const nav = useNavigate();
  const t = useT();
  const { data, isPending, isError, error } = useExtraction(id);

  return (
    <div style={{ maxWidth: 1080, margin: "0 auto", padding: "22px 30px 60px" }}>
      <button
        onClick={() => nav(SCREENS.upload.path)}
        style={{ fontSize: 12, color: color.indigo, background: "none", border: "none", cursor: "pointer", padding: 0, marginBottom: 12 }}
      >
        {t("ex.back")}
      </button>

      {isPending && (
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
          <Card pad={0} style={{ overflow: "hidden" }}>
            <div
              style={{
                display: "grid", gridTemplateColumns: GRID, gap: 10, padding: "10px 14px",
                background: color.rowAltBg, borderBottom: `1px solid ${color.hairline2}`,
                fontSize: 10, fontWeight: 600, letterSpacing: 0.3, color: color.muted,
              }}
            >
              <span>{t("ex.col.lineitem")}</span>
              <span>{t("ex.col.note")}</span>
              <span>{t("ex.col.value")} · {t("ex.col.source")}</span>
              <span>{t("ex.col.mapping")}</span>
            </div>
            {data.result.rows.length === 0 && (
              <div style={{ padding: "18px 14px", fontSize: 12.5, color: color.muted }}>{t("ex.empty")}</div>
            )}
            {data.result.rows.map((row, i) => (
              <RowLine key={i} row={row} t={t} />
            ))}
          </Card>
        </>
      )}
    </div>
  );
}
