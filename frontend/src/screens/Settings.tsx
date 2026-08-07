/** Settings (admin) — surfaces backend configuration on the frontend and lets an admin
 * edit the runtime-mutable pieces: interface localization, the reviewer sign-off step,
 * and the LLM configuration (provider / model / endpoint / params). The API key is never
 * entered or shown here — only the name of the env var it is read from. Everything else
 * is config.toml / env driven and shown read-only. */
import { useEffect, useState } from "react";

import { Card, ScreenHeader, Toggle } from "../components/ui";
import { useT } from "../i18n";
import { useCan } from "../lib/rbac";
import { usePatchSettings, useSettings } from "../lib/queries";
import { color, font, radius } from "../theme";
import type { AppSettings, LlmConfigPatch } from "../types";

/** Read-only key/value row. */
function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 16, padding: "7px 0", borderBottom: `1px solid ${color.hairline}` }}>
      <span style={{ fontSize: 12, color: color.muted }}>{label}</span>
      <span style={{ fontSize: 12, fontWeight: 600, color: color.ink, fontFamily: font.mono, textAlign: "right" }}>{value}</span>
    </div>
  );
}

function SectionCard({ title, children, note }: { title: string; children: React.ReactNode; note?: string }) {
  return (
    <Card style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>{title}</div>
        {note && <span style={{ fontSize: 10, color: color.muted2 }}>{note}</span>}
      </div>
      {children}
    </Card>
  );
}

/** A clickable toggle row bound to a boolean setting. */
function ToggleRow({
  on, onToggle, canEdit, saving, title, help,
}: {
  on: boolean; onToggle: () => void; canEdit: boolean; saving: boolean; title: React.ReactNode; help: string;
}) {
  const t = useT();
  return (
    <div
      onClick={() => canEdit && !saving && onToggle()}
      style={{
        display: "flex", alignItems: "flex-start", gap: 12, padding: "10px 12px", borderRadius: 9,
        background: color.rowAltBg, cursor: canEdit ? "pointer" : "default", opacity: canEdit ? 1 : 0.7,
        marginBottom: 8,
      }}
    >
      <div style={{ marginTop: 2 }}><Toggle on={on} /></div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 12.5, fontWeight: 600, color: color.ink }}>
          {title}{" "}
          <span style={{ fontSize: 10.5, fontWeight: 600, color: on ? color.greenFg : color.muted }}>
            · {saving ? t("st.saving") : on ? t("st.on") : t("st.off")}
          </span>
        </div>
        <div style={{ fontSize: 11.5, color: color.sec2, lineHeight: 1.55, marginTop: 4 }}>{help}</div>
      </div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%", fontSize: 12, fontFamily: font.mono, color: color.ink,
  border: `1px solid ${color.controlBorder}`, borderRadius: 7, padding: "7px 9px",
  background: "#fff", boxSizing: "border-box",
};

/** One labeled editable field in the LLM config form. */
function Field({
  label, children,
}: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <span style={{ fontSize: 11, color: color.muted }}>{label}</span>
      {children}
    </label>
  );
}

const PROVIDERS = ["anthropic", "openai", "openai_compatible", "local", "stub"];

/** Editable LLM configuration (admin). The API key stays in the environment — only its
 * env-var name is editable; we surface whether the key is currently populated. */
function LlmConfigCard({ s, canEdit }: { s: AppSettings; canEdit: boolean }) {
  const t = useT();
  const patch = usePatchSettings();
  const [form, setForm] = useState<LlmConfigPatch>({});
  // Re-sync the form from server state whenever it changes (e.g. after save).
  useEffect(() => {
    setForm({
      provider: s.llm.provider, model: s.llm.model, base_url: s.llm.base_url,
      temperature: s.llm.temperature, max_tokens: s.llm.max_tokens,
      timeout_seconds: s.llm.timeout_seconds, api_key_env: s.llm.api_key_env,
    });
  }, [s.llm.provider, s.llm.model, s.llm.base_url, s.llm.temperature, s.llm.max_tokens, s.llm.timeout_seconds, s.llm.api_key_env]);

  const set = (k: keyof LlmConfigPatch, v: string | number) => setForm((f) => ({ ...f, [k]: v }));

  if (!canEdit) {
    return (
      <SectionCard title={t("st.llm")} note={t("st.readOnly")}>
        <Row label={t("st.provider")} value={s.llm.provider} />
        <Row label={t("st.model")} value={s.llm.model} />
        <Row label={t("st.temperature")} value={s.llm.temperature} />
        <Row label={t("st.maxTokens")} value={s.llm.max_tokens} />
        <Row label={t("st.timeout")} value={s.llm.timeout_seconds} />
        <Row label={t("st.baseUrl")} value={s.llm.base_url || "(provider default)"} />
        <Row label={t("st.apiKey")} value={<KeyStatus s={s} t={t} />} />
      </SectionCard>
    );
  }

  return (
    <SectionCard title={t("st.llm")} note={t("st.editable")}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <Field label={t("st.provider")}>
          <select value={form.provider} onChange={(e) => set("provider", e.target.value)} style={inputStyle}>
            {PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </Field>
        <Field label={t("st.model")}>
          <input value={form.model ?? ""} onChange={(e) => set("model", e.target.value)} style={inputStyle} />
        </Field>
        <Field label={t("st.baseUrl")}>
          <input value={form.base_url ?? ""} placeholder="(provider default)"
                 onChange={(e) => set("base_url", e.target.value)} style={inputStyle} />
        </Field>
        <Field label={t("st.apiKeyEnv")}>
          <input value={form.api_key_env ?? ""} onChange={(e) => set("api_key_env", e.target.value)} style={inputStyle} />
        </Field>
        <Field label={t("st.temperature")}>
          <input type="number" step="0.1" value={form.temperature ?? 0}
                 onChange={(e) => set("temperature", Number(e.target.value))} style={inputStyle} />
        </Field>
        <Field label={t("st.maxTokens")}>
          <input type="number" value={form.max_tokens ?? 0}
                 onChange={(e) => set("max_tokens", Number(e.target.value))} style={inputStyle} />
        </Field>
        <Field label={t("st.timeout")}>
          <input type="number" value={form.timeout_seconds ?? 0}
                 onChange={(e) => set("timeout_seconds", Number(e.target.value))} style={inputStyle} />
        </Field>
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 13 }}>
        <span style={{ fontSize: 11.5 }}><KeyStatus s={s} t={t} /></span>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {patch.isSuccess && !patch.isPending && (
            <span style={{ fontSize: 11, color: color.greenFg, fontWeight: 600 }}>✓ {t("st.saved")}</span>
          )}
          <button
            onClick={() => patch.mutate({ llm: form })}
            disabled={patch.isPending}
            style={{
              fontSize: 12, fontWeight: 600, color: "#fff",
              background: patch.isPending ? color.faint : color.indigo,
              border: "none", borderRadius: 8, padding: "8px 16px",
              cursor: patch.isPending ? "default" : "pointer",
            }}
          >
            {patch.isPending ? t("st.saving") : t("st.save")}
          </button>
        </div>
      </div>
      <div style={{ fontSize: 10.5, color: color.muted2, marginTop: 8, lineHeight: 1.5 }}>
        {t("st.keyNote")}
      </div>
    </SectionCard>
  );
}

function KeyStatus({ s, t }: { s: AppSettings; t: (k: string) => string }) {
  return (
    <span style={{ color: s.llm.key_configured ? color.greenFg : color.amberFg, fontWeight: 600 }}>
      {s.llm.key_configured ? t("st.keyConfigured") : t("st.keyMissing")}{" "}
      <span style={{ color: color.muted, fontWeight: 400 }}>({t("st.keyFrom")} {s.llm.api_key_env})</span>
    </span>
  );
}

export default function SettingsScreen() {
  const t = useT();
  const { data, isPending } = useSettings();
  const patch = usePatchSettings();
  const canEdit = useCan("config:settings");

  if (isPending || !data) {
    return <div style={{ padding: 60, textAlign: "center", color: color.muted }}>Loading…</div>;
  }
  const s: AppSettings = data;
  const readOnlyNote = t("st.readOnly");

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "26px 30px 60px" }}>
      <ScreenHeader title={t("st.title")} subtitle={t("st.subhead")} />

      {/* Workflow & interface — the editable feature flags */}
      <SectionCard title={t("st.features")}>
        <ToggleRow
          on={s.features.ui_localization}
          onToggle={() => patch.mutate({ ui_localization: !s.features.ui_localization })}
          canEdit={canEdit}
          saving={patch.isPending}
          title={t("st.localizeUI")}
          help={t("st.localizeUIHelp")}
        />
        <ToggleRow
          on={s.features.review_required}
          onToggle={() => patch.mutate({ review_required: !s.features.review_required })}
          canEdit={canEdit}
          saving={patch.isPending}
          title={t("st.reviewRequired")}
          help={t("st.reviewRequiredHelp")}
        />
        {!canEdit && <div style={{ fontSize: 11, color: color.muted, marginTop: 4 }}>{t("st.adminOnly")}</div>}
        <div style={{ marginTop: 12 }}>
          <Row label={t("st.supportedLangs")} value={s.features.supported_locales.join(" · ")} />
          <Row label={t("st.defaultOutput")} value={s.features.default_output_locale} />
        </div>
      </SectionCard>

      {/* LLM — editable for admins */}
      <LlmConfigCard s={s} canEdit={canEdit} />

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        {/* OCR */}
        <SectionCard title={t("st.ocr")} note={readOnlyNote}>
          <Row label={t("st.engine")} value={s.ocr.engine} />
          <Row label={t("st.languages")} value={s.ocr.languages.join(" · ")} />
          <Row label={t("st.dpi")} value={s.ocr.dpi} />
        </SectionCard>

        {/* Embeddings */}
        <SectionCard title={t("st.embeddings")} note={readOnlyNote}>
          <Row label={t("st.provider")} value={s.embeddings.provider} />
          <Row label={t("st.model")} value={s.embeddings.model} />
        </SectionCard>
      </div>

      {/* Extraction & reconciliation */}
      <SectionCard title={t("st.extraction")} note={readOnlyNote}>
        <Row label={t("st.fuzzyAccept")} value={s.extraction.fuzzy_accept} />
        <Row label={t("st.fuzzyCandidate")} value={s.extraction.fuzzy_candidate} />
        <Row label={t("st.embeddingAccept")} value={s.extraction.embedding_accept} />
        <Row label={t("st.mappingMargin")} value={s.extraction.mapping_margin} />
        <Row label={t("st.autoAccept")} value={s.extraction.auto_accept_confidence} />
        <Row label={t("st.reconAbs")} value={s.extraction.recon_abs_tolerance} />
        <Row label={t("st.reconRel")} value={s.extraction.recon_rel_tolerance} />
      </SectionCard>

      {/* Access & session */}
      <SectionCard title={t("st.access")} note={readOnlyNote}>
        <Row label={t("st.roleHeader")} value={s.auth.allow_role_header ? t("st.on") : t("st.off")} />
        <Row label={t("st.demoMode")} value={s.auth.demo_mode ? t("st.on") : t("st.off")} />
        <Row label={t("st.sessionTtl")} value={s.auth.session_ttl_minutes} />
      </SectionCard>
    </div>
  );
}
