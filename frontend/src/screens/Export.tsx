/** Screen 8: Export — deliver the extracted, reviewed and reconciled dataset. */
import { useExportOptions } from "../lib/queries";
import { downloadExport } from "../lib/api";
import { useUI } from "../store";
import { color, font, radius } from "../theme";
import { Card } from "../components/ui";

/** One selectable format card (Excel / JSON). */
function FormatCard({
  glyph,
  label,
  sub,
  selected,
  onClick,
}: {
  glyph: string;
  label: string;
  sub: string;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <div
      onClick={onClick}
      style={{
        flex: 1,
        border: `1.5px solid ${selected ? color.indigo : color.cardBorder}`,
        background: selected ? color.indigoTint : color.surface,
        borderRadius: 10,
        padding: 15,
        cursor: "pointer",
        textAlign: "center",
      }}
    >
      <div style={{ fontSize: 22, marginBottom: 5 }}>{glyph}</div>
      <div style={{ fontSize: 12.5, fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 10.5, color: color.muted }}>{sub}</div>
    </div>
  );
}

/** A single include-checklist row. Presentational: reflects option.on. */
function IncludeRow({ label, on }: { label: string; on: boolean }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0" }}>
      <span
        style={{
          width: 17,
          height: 17,
          borderRadius: 5,
          background: on ? color.indigo : color.surface,
          border: `1.5px solid ${on ? color.indigo : color.dashed}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "#fff",
          fontSize: 11,
        }}
      >
        {on ? "✓" : ""}
      </span>
      <span style={{ fontSize: 12.5, color: color.ink2 }}>{label}</span>
    </div>
  );
}

/** A labeled presentation field mock. */
function PresField({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ flex: 1 }}>
      <div style={{ fontSize: 11, color: color.muted, marginBottom: 4 }}>{label}</div>
      <div
        style={{
          border: `1px solid ${color.cardBorder}`,
          borderRadius: 7,
          padding: "7px 10px",
          fontSize: 12,
          fontWeight: 500,
        }}
      >
        {value}
      </div>
    </div>
  );
}

const EXCEL_HEAD = ["", "Line item", "FY25", "Note", "Conf."];
const EXCEL_ROWS: string[][] = [
  ["1", "Property, plant and equipment", "4,23,180", "N3", "96%"],
  ["2", "Trade receivables", "84,500", "N12", "78%"],
  ["3", "Cash and cash equivalents", "39,100", "N13", "96%"],
  ["4", "Total current assets", "3,30,800", "", "ƒ"],
  ["5", "TOTAL ASSETS", "12,68,100", "", "ƒ"],
];
const GRID_COLS = "30px 1fr 80px 46px 62px";

const JSON_TEXT = `{
  "entity": "Reliance Industries Ltd",
  "period": "FY2024-25",
  "dataset": "consolidated",
  "units": "INR_crore",
  "balance_sheet": [
    {
      "item": "Trade receivables",
      "value": 84500,
      "note_ref": "12",
      "confidence": 0.78,
      "sign": "positive",
      "formula": "Note12.total - Note12.3",
      "source": { "page": 142, "note_page": 171 }
    }
  ]
}`;

function ExcelPreview() {
  return (
    <div style={{ fontFamily: font.mono, fontSize: 11 }}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: GRID_COLS,
          background: color.excelGreen,
          color: "#fff",
          fontWeight: 600,
        }}
      >
        {EXCEL_HEAD.map((h, i) => (
          <div
            key={i}
            style={{
              padding: "6px 8px",
              borderRight: "1px solid #1a5c37",
              textAlign: i > 1 ? "right" : "left",
            }}
          >
            {h}
          </div>
        ))}
      </div>
      {EXCEL_ROWS.map((row, ri) => {
        const isTotal = row[0] === "5";
        return (
          <div
            key={ri}
            style={{
              display: "grid",
              gridTemplateColumns: GRID_COLS,
              background: ri % 2 ? "#f6f8f6" : "#fff",
              borderBottom: "1px solid #e6ebe6",
            }}
          >
            {row.map((c, ci) => (
              <div
                key={ci}
                style={{
                  padding: "6px 8px",
                  borderRight: "1px solid #eef1ee",
                  textAlign: ci > 1 ? "right" : "left",
                  fontWeight: isTotal ? 700 : 400,
                  color: ci === 4 ? color.amberFg : "#333",
                }}
              >
                {c}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}

function JsonPreview() {
  return (
    <pre
      style={{
        margin: 0,
        padding: "14px 16px",
        fontFamily: font.mono,
        fontSize: 11,
        lineHeight: 1.6,
        color: color.ink,
        whiteSpace: "pre-wrap",
      }}
    >
      {JSON_TEXT}
    </pre>
  );
}

export default function ExportScreen() {
  const { data, isPending } = useExportOptions();
  const exportFmt = useUI((s) => s.exportFmt);
  const setFmt = useUI((s) => s.setFmt);
  const isExcel = exportFmt === "excel";

  if (isPending || !data) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: color.muted }}>Loading…</div>
    );
  }

  return (
    <div style={{ maxWidth: 1120, margin: "0 auto", padding: "26px 30px 60px" }}>
      <div style={{ marginBottom: 18 }}>
        <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 5 }}>Export</h1>
        <p style={{ margin: 0, color: color.sec2 }}>
          Deliver the extracted, reviewed and reconciled dataset. 12 items still open in
          review — they will be flagged in the output.
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1.25fr", gap: 18 }}>
        {/* LEFT */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <Card>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 12 }}>Format</div>
            <div style={{ display: "flex", gap: 11 }}>
              <FormatCard
                glyph="▦"
                label="Excel"
                sub="formatted .xlsx"
                selected={isExcel}
                onClick={() => setFmt("excel")}
              />
              <FormatCard
                glyph="{ }"
                label="JSON"
                sub="structured tree"
                selected={!isExcel}
                onClick={() => setFmt("json")}
              />
            </div>
          </Card>

          <Card>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 11 }}>Include</div>
            {data.options.map((o) => (
              <IncludeRow key={o.key} label={o.label} on={o.on} />
            ))}
          </Card>

          <Card>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 11 }}>Presentation</div>
            <div style={{ display: "flex", gap: 10 }}>
              <PresField label="Dataset" value="Both ▾" />
              <PresField label="Currency" value="INR ₹ ▾" />
              <PresField label="Units" value="Crore ▾" />
            </div>
          </Card>
        </div>

        {/* RIGHT — preview */}
        <Card pad={0} style={{ display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "12px 16px",
              borderBottom: `1px solid ${color.hairline3}`,
            }}
          >
            <span style={{ fontSize: 12.5, fontWeight: 600 }}>
              Preview — {isExcel ? "spread.xlsx" : "extract.json"}
            </span>
            <span style={{ fontSize: 11, color: color.muted }}>Consolidated · ₹ Crore</span>
          </div>
          <div style={{ flex: 1, overflow: "auto", background: isExcel ? "#fff" : "#fbfcfd" }}>
            {isExcel ? <ExcelPreview /> : <JsonPreview />}
          </div>
          <div
            style={{
              padding: "13px 16px",
              borderTop: `1px solid ${color.hairline3}`,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <span style={{ fontSize: 11.5, color: color.muted }}>
              148 line items · 48 notes · 12 flagged
            </span>
            <button
              onClick={() =>
                downloadExport({
                  format: exportFmt,
                  basis: "consolidated",
                  currency: "INR",
                  units: "crore",
                  include: {},
                })
              }
              style={{
                fontSize: 13,
                fontWeight: 600,
                color: "#fff",
                background: color.indigo,
                border: "none",
                borderRadius: 9,
                padding: "10px 22px",
                cursor: "pointer",
              }}
            >
              Download {isExcel ? ".xlsx" : ".json"}
            </button>
          </div>
        </Card>
      </div>
    </div>
  );
}
