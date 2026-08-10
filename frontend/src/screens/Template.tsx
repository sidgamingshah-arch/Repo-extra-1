/** Screen 7 — Template & Ontology. Left template tree + right node editor. */
import type { CSSProperties } from "react";
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Card } from "../components/ui";
import { useAppLocale, useUI } from "../store";
import { color, font, radius } from "../theme";
import type { NodeConfig, TemplateResponse } from "../types";
import { useTemplateDetail, useTemplates } from "../lib/queries";
import { api } from "../lib/api";
import { useCan } from "../lib/rbac";
import { useT } from "../i18n";

/** Admin-only: create a template/ontology by importing a validated JSON definition. Persisted
 *  and versioned server-side, then selectable on Upload — the frontend authoring path (Req 4). */
function ImportTemplate() {
  const t = useT();
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    setBusy(true);
    setMsg(null);
    try {
      const def = JSON.parse(await f.text());
      const isOntology = "target_template_key" in def || "mappings" in def;
      const res = isOntology ? await api.createOntology(def) : await api.createTemplate(def);
      const key = "template_key" in res ? res.template_key : res.ontology_key;
      setMsg({ ok: true, text: t("tp.importOk").replace("{key}", key).replace("{v}", String(res.version)) });
      qc.invalidateQueries({ queryKey: ["templates"] });
      qc.invalidateQueries({ queryKey: ["ontologies"] });
    } catch (err) {
      const m = err instanceof Error ? err.message : String(err);
      setMsg({ ok: false, text: `${t("tp.importErr")} ${m}`.slice(0, 300) });
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div style={{ flex: "0 0 auto", padding: "11px 14px", borderTop: `1px solid ${color.hairline3}` }}>
      <input ref={fileRef} type="file" accept="application/json,.json" onChange={onFile} style={{ display: "none" }} />
      <button
        onClick={() => fileRef.current?.click()}
        disabled={busy}
        style={{
          width: "100%", fontSize: 12, fontWeight: 600, color: color.indigo, background: "#fff",
          border: `1px dashed ${color.indigoBorder2}`, borderRadius: radius.control, padding: 9,
          cursor: busy ? "wait" : "pointer",
        }}
      >
        {busy ? t("tp.importing") : t("tp.importTemplate")}
      </button>
      {msg && (
        <div style={{ marginTop: 8, fontSize: 11, lineHeight: 1.5,
                      color: msg.ok ? color.greenFg : color.redFg }}>
          {msg.text}
        </div>
      )}
    </div>
  );
}

const SIGN_OPTIONS: { key: string; labelKey: string }[] = [
  { key: "as_reported", labelKey: "tp.sign.asReported" },
  { key: "expense_contra", labelKey: "tp.sign.expenseContra" },
  { key: "auto", labelKey: "tp.sign.auto" },
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

/** Template-wide netting policies (LLM-gated): a target line net of the components it may
 *  include, applied per-document only when the model confirms the containment. */
function NettingRules({ rules, t }: {
  rules: NonNullable<TemplateResponse["netting_rules"]>; t: (k: string) => string;
}) {
  return (
    <Card style={{ marginTop: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>{t("tp.nettingRules")}</span>
        <span style={{ fontSize: 9.5, fontWeight: 600, padding: "2px 7px", borderRadius: radius.pill,
                       background: color.amberBg, color: color.amberFg }}>{t("tp.nettingLLM")}</span>
      </div>
      <p style={{ margin: "0 0 12px", fontSize: 11.5, color: color.sec2, lineHeight: 1.55 }}>
        {t("tp.nettingRulesHint")}
      </p>
      {rules.length === 0 ? (
        <div style={{ fontSize: 12, color: color.muted }}>{t("tp.nettingNone")}</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {rules.map((r) => (
            <div key={r.id} data-testid="netting-rule"
                 style={{ border: `1px solid ${color.hairline3}`, borderRadius: radius.control, padding: 12 }}>
              <div style={{ fontFamily: font.mono, fontSize: 11.5, color: color.ink, marginBottom: 6,
                            display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
                <span style={{ fontWeight: 600, color: color.indigo }}>{r.target_label}</span>
                <span style={{ color: color.muted }}>=</span>
                <span style={{ color: color.muted }}>{r.target_label}</span>
                {r.subtract.map((c) => (
                  <span key={c.key}><span style={{ color: color.redFg, fontWeight: 600 }}>− {c.label}</span></span>
                ))}
                {r.add.map((c) => (
                  <span key={c.key}><span style={{ color: color.greenFg, fontWeight: 600 }}>+ {c.label}</span></span>
                ))}
              </div>
              {r.label && (
                <div style={{ fontSize: 11.5, color: color.sec, lineHeight: 1.5 }}>{r.label}</div>
              )}
              {r.condition && (
                <div style={{ fontSize: 11, color: color.muted, lineHeight: 1.5, marginTop: 6 }}>
                  <b style={{ color: color.sec2 }}>{t("tp.nettingWhen")}:</b> {r.condition}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

export default function TemplateScreen() {
  const locale = useAppLocale();
  const t = useT();
  // Render the REAL configured template(s), not the demo project. Admin picks among the
  // templates that exist; the detail (tree + per-node config) comes from that template and
  // its paired ontology.
  const tplList = useTemplates();
  const [selId, setSelId] = useState<string | undefined>(undefined);
  useEffect(() => {
    if (!selId && tplList.data && tplList.data.length) setSelId(tplList.data[0].id);
  }, [selId, tplList.data]);
  const { data } = useTemplateDetail(selId, locale);
  const tplSel = useUI((s) => s.tplSel);
  const setTpl = useUI((s) => s.setTpl);
  const canEdit = useCan("config:template"); // authoring is admin-only

  // No templates configured yet → guidance (also covers the initial load).
  if (tplList.data && tplList.data.length === 0) {
    return (
      <div style={{ maxWidth: 560, margin: "60px auto", textAlign: "center", color: color.muted, padding: "0 24px" }}>
        <div style={{ fontSize: 28, marginBottom: 10 }}>◆</div>
        <h1 style={{ fontSize: 18, fontWeight: 600, color: color.ink, marginBottom: 8 }}>{t("tp.emptyTitle")}</h1>
        <p style={{ fontSize: 12.5, lineHeight: 1.6 }}>{t("tp.emptyHint")}</p>
        <div style={{ maxWidth: 320, margin: "18px auto 0" }}><ImportTemplate /></div>
      </div>
    );
  }

  if (!data) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: color.muted }}>
        Loading…
      </div>
    );
  }

  const { tree, node_config, template } = data;
  const cfg: NodeConfig | undefined =
    node_config[tplSel] ?? node_config["trade_recv"] ?? Object.values(node_config)[0];

  // Greenfield (no project loaded yet): the template tree is empty. Show guidance rather
  // than crashing on a missing node config.
  if (!tree.length || !cfg) {
    return (
      <div style={{ maxWidth: 560, margin: "60px auto", textAlign: "center", color: color.muted, padding: "0 24px" }}>
        <div style={{ fontSize: 28, marginBottom: 10 }}>◆</div>
        <h1 style={{ fontSize: 18, fontWeight: 600, color: color.ink, marginBottom: 8 }}>{t("tp.emptyTitle")}</h1>
        <p style={{ fontSize: 12.5, lineHeight: 1.6 }}>{t("tp.emptyHint")}</p>
      </div>
    );
  }

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
          <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 3 }}>{t("tp.structure")}</h2>
          <div style={{ fontSize: 11.5, color: color.muted }}>
            {template.name} · {template.line_items} {t("tp.lineItems")}
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

        {canEdit && <ImportTemplate />}
      </div>

      {/* RIGHT: node editor */}
      <div style={{ flex: 1, minWidth: 0, overflowY: "auto", padding: "26px 30px" }}>
        <div style={{ maxWidth: 680 }}>
          <div style={{ fontSize: 11, color: color.muted, marginBottom: 3 }}>{cfg.breadcrumb}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 3 }}>
            <h1 style={{ fontSize: 20, fontWeight: 600, margin: 0 }}>{cfg.label}</h1>
            {!canEdit && (
              <span style={{ fontSize: 10, fontWeight: 600, padding: "2px 8px", borderRadius: radius.pill,
                             background: color.rowAltBg, color: color.muted, border: `1px solid ${color.hairline3}` }}>
                {t("tp.viewOnly")}
              </span>
            )}
          </div>
          <p style={{ margin: "0 0 20px", color: color.sec2, fontSize: 12.5 }}>
            {canEdit ? t("tp.editorSubhead") : t("tp.viewOnlyHint")}
          </p>

          {/* Description aliases */}
          <Card style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 11 }}>{t("tp.aliases")}</div>
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
                  {a}{canEdit && <span style={{ opacity: 0.5, cursor: "pointer" }}> ×</span>}
                </span>
              ))}
              {canEdit && (
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
                  {t("tp.addAlias")}
                </span>
              )}
            </div>
          </Card>

          {/* Sign convention + Data type */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
            <Card>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 11 }}>{t("tp.signConvention")}</div>
              {SIGN_OPTIONS.map((opt) => {
                const on = opt.key === cfg.sign;
                return (
                  <div key={opt.key} style={{ display: "flex", alignItems: "center", gap: 9, padding: "8px 0" }}>
                    <Radio on={on} />
                    <span style={{ fontSize: 12, color: on ? color.ink : color.sec2, fontWeight: on ? 600 : 400 }}>
                      {t(opt.labelKey)}
                    </span>
                  </div>
                );
              })}
            </Card>
            <Card>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 11 }}>{t("tp.dataTypeUnits")}</div>
              <div style={{ marginBottom: 11 }}>
                <FieldMock label={t("tp.valueType")} value={cfg.value_type} />
              </div>
              <FieldMock label={t("tp.aggregation")} value={cfg.aggregation} />
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
              <span style={{ fontSize: 13, fontWeight: 600 }}>{t("tp.nettingRule")}</span>
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
                {t("tp.key")}
              </span>
            </div>
            <p style={{ margin: "0 0 12px", fontSize: 12, color: color.sec, lineHeight: 1.55 }}>
              {cfg.netting.explain}
            </p>
            <NettingExpr expr={cfg.netting.expr} />
          </div>

          {/* Template-wide containment-netting policies (LLM-gated). */}
          {data.netting_rules && <NettingRules rules={data.netting_rules} t={t} />}
        </div>
      </div>
    </div>
  );
}
