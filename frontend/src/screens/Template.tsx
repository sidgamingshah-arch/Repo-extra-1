/** Screen 7 — Template & Ontology. Left template tree + right node editor. */
import type { CSSProperties } from "react";

import { Card } from "../components/ui";
import { useUI } from "../store";
import { color, font, radius } from "../theme";
import type { NodeConfig } from "../types";
import { useTemplate } from "../lib/queries";

const SIGN_OPTIONS: { key: string; label: string }[] = [
  { key: "as_reported", label: "As reported (positive)" },
  { key: "expense_contra", label: "Expense / contra — negative" },
  { key: "auto", label: "Auto-detect from context" },
];

function Radio({ on }: { on: boolean }) {
  return (
    <span
      style={{
        width: 15,
        height: 15,
        borderRadius: "50%",
        border: `2px solid ${on ? color.indigo : color.dashed}`,
        background: on ? color.indigo : "#fff",
        flex: "0 0 auto",
      }}
    />
  );
}

function FieldMock({ label, value }: { label: string; value: string }) {
  return (
    <>
      <div style={{ fontSize: 11, color: color.muted, marginBottom: 4 }}>{label}</div>
      <div
        style={{
          border: `1px solid ${color.cardBorder}`,
          borderRadius: radius.controlSm,
          padding: "7px 10px",
          fontSize: 12,
          fontWeight: 500,
        }}
      >
        {value} ▾
      </div>
    </>
  );
}

/** Render the netting expression: left muted, added token indigo, subtracted token red. */
function NettingExpr({ expr }: { expr: string }) {
  // Format: "face_value = Note12.total − Note12.related_party"
  const eq = expr.indexOf("=");
  const lhs = eq >= 0 ? expr.slice(0, eq).trim() : expr;
  const rhs = eq >= 0 ? expr.slice(eq + 1).trim() : "";
  const parts = rhs.split("−");
  const added = (parts[0] ?? "").trim();
  const subtracted = (parts[1] ?? "").trim();
  const box: CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: 8,
    background: color.rowAltBg,
    border: `1px solid ${color.hairline3}`,
    borderRadius: radius.control,
    padding: "10px 12px",
    fontFamily: font.mono,
    fontSize: 11.5,
    color: color.ink,
    flexWrap: "wrap",
  };
  return (
    <div style={box}>
      <span style={{ color: color.muted }}>{lhs}</span> ={" "}
      <span style={{ color: color.indigo, fontWeight: 600 }}>{added}</span> −{" "}
      <span style={{ color: color.redFg, fontWeight: 600 }}>{subtracted}</span>
    </div>
  );
}

export default function TemplateScreen() {
  const { data } = useTemplate();
  const tplSel = useUI((s) => s.tplSel);
  const setTpl = useUI((s) => s.setTpl);

  if (!data) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: color.muted }}>
        Loading…
      </div>
    );
  }

  const { tree, node_config, template } = data;
  const cfg: NodeConfig = node_config[tplSel] ?? node_config["trade_recv"];

  return (
    <div style={{ display: "flex", height: "100%", minHeight: 0 }}>
      {/* LEFT: template tree */}
      <div
        style={{
          width: 360,
          flex: "0 0 360px",
          borderRight: `1px solid ${color.cardBorder}`,
          background: color.surface,
          display: "flex",
          flexDirection: "column",
          minHeight: 0,
        }}
      >
        <div style={{ padding: 16, flex: "0 0 auto", borderBottom: `1px solid ${color.hairline3}` }}>
          <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 3 }}>Template structure</h2>
          <div style={{ fontSize: 11.5, color: color.muted }}>
            {template.name} · {template.line_items} line items
          </div>
        </div>

        <div style={{ flex: 1, overflowY: "auto", minHeight: 0, padding: "8px 6px" }}>
          {tree.map((node) => {
            const sel = node.id === tplSel;
            const head = !!node.head;
            return (
              <div
                key={node.id}
                onClick={() => setTpl(node.id)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "7px 10px",
                  borderRadius: radius.controlSm,
                  cursor: "pointer",
                  background: sel ? color.indigoTint : "transparent",
                  marginLeft: node.lvl * 16,
                }}
              >
                <span style={{ fontSize: 10, color: color.faint, width: 10 }}>{head ? "▾" : ""}</span>
                <span
                  style={{
                    flex: 1,
                    fontSize: 12,
                    fontWeight: head ? 700 : sel ? 600 : 400,
                    color: head ? color.viewerBg : sel ? color.indigo : color.ink2,
                  }}
                >
                  {node.label}
                </span>
                {node.rule && (
                  <span
                    style={{
                      fontSize: 9.5,
                      fontWeight: 600,
                      padding: "1px 6px",
                      borderRadius: 4,
                      background: color.indigoTint2,
                      color: color.indigo,
                    }}
                  >
                    rule
                  </span>
                )}
              </div>
            );
          })}
        </div>

        <div style={{ flex: "0 0 auto", padding: "11px 14px", borderTop: `1px solid ${color.hairline3}` }}>
          <button
            style={{
              width: "100%",
              fontSize: 12,
              fontWeight: 600,
              color: color.indigo,
              background: "#fff",
              border: `1px dashed ${color.indigoBorder2}`,
              borderRadius: radius.control,
              padding: 9,
              cursor: "pointer",
            }}
          >
            + Add line item
          </button>
        </div>
      </div>

      {/* RIGHT: node editor */}
      <div style={{ flex: 1, minWidth: 0, overflowY: "auto", padding: "26px 30px" }}>
        <div style={{ maxWidth: 680 }}>
          <div style={{ fontSize: 11, color: color.muted, marginBottom: 3 }}>{cfg.breadcrumb}</div>
          <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 3 }}>{cfg.label}</h1>
          <p style={{ margin: "0 0 20px", color: color.sec2, fontSize: 12.5 }}>
            Ontology rules that tell the extractor which source descriptions map here, how to treat the sign,
            and how to net note detail against the face value.
          </p>

          {/* Description aliases */}
          <Card style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 11 }}>Description aliases</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 7 }}>
              {cfg.aliases.map((a) => (
                <span
                  key={a}
                  style={{
                    fontSize: 11.5,
                    fontWeight: 500,
                    padding: "5px 11px",
                    borderRadius: radius.pill,
                    background: color.indigoTint2,
                    color: color.indigo,
                  }}
                >
                  {a} <span style={{ opacity: 0.5, cursor: "pointer" }}>×</span>
                </span>
              ))}
              <span
                style={{
                  fontSize: 11.5,
                  padding: "5px 11px",
                  borderRadius: radius.pill,
                  border: `1px dashed ${color.dashed}`,
                  color: color.muted,
                  cursor: "pointer",
                }}
              >
                + add alias
              </span>
            </div>
          </Card>

          {/* Sign convention + Data type */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
            <Card>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 11 }}>Sign convention</div>
              {SIGN_OPTIONS.map((opt) => {
                const on = opt.key === cfg.sign;
                return (
                  <div key={opt.key} style={{ display: "flex", alignItems: "center", gap: 9, padding: "8px 0" }}>
                    <Radio on={on} />
                    <span style={{ fontSize: 12, color: on ? color.ink : color.sec2, fontWeight: on ? 600 : 400 }}>
                      {opt.label}
                    </span>
                  </div>
                );
              })}
            </Card>
            <Card>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 11 }}>Data type &amp; units</div>
              <div style={{ marginBottom: 11 }}>
                <FieldMock label="Value type" value={cfg.value_type} />
              </div>
              <FieldMock label="Aggregation" value={cfg.aggregation} />
            </Card>
          </div>

          {/* Note-to-face netting rule (flagship) */}
          <div
            style={{
              background: color.surface,
              border: `1px solid ${color.indigoBorder}`,
              borderRadius: radius.card,
              padding: 18,
              borderLeft: `3px solid ${color.indigo}`,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 9 }}>
              <span style={{ fontSize: 13, fontWeight: 600 }}>Note-to-face netting rule</span>
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 600,
                  padding: "2px 7px",
                  borderRadius: radius.pill,
                  background: color.indigoTint2,
                  color: color.indigo,
                }}
              >
                KEY
              </span>
            </div>
            <p style={{ margin: "0 0 12px", fontSize: 12, color: color.sec, lineHeight: 1.55 }}>
              {cfg.netting.explain}
            </p>
            <NettingExpr expr={cfg.netting.expr} />
          </div>
        </div>
      </div>
    </div>
  );
}
