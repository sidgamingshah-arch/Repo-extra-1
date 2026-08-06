/** Settings (admin) — surfaces the backend configuration (config.toml / environment)
 * on the frontend, and lets an admin flip the one runtime-mutable flag: whether the
 * whole interface is localized (vs only the extracted financial output). Everything
 * else is shown read-only. */
import { Card, ScreenHeader, Toggle } from "../components/ui";
import { useT } from "../i18n";
import { useCan } from "../lib/rbac";
import { usePatchSettings, useSettings } from "../lib/queries";
import { color, font } from "../theme";
import type { AppSettings } from "../types";

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

      {/* Interface & languages — the one editable section */}
      <SectionCard title={t("st.features")}>
        <div
          onClick={() => canEdit && !patch.isPending && patch.mutate({ ui_localization: !s.features.ui_localization })}
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 12,
            padding: "10px 12px",
            borderRadius: 9,
            background: color.rowAltBg,
            cursor: canEdit ? "pointer" : "default",
            opacity: canEdit ? 1 : 0.7,
          }}
        >
          <div style={{ marginTop: 2 }}>
            <Toggle on={s.features.ui_localization} />
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600, color: color.ink }}>
              {t("st.localizeUI")}{" "}
              <span style={{ fontSize: 10.5, fontWeight: 600, color: s.features.ui_localization ? color.greenFg : color.muted }}>
                · {patch.isPending ? t("st.saving") : s.features.ui_localization ? t("st.on") : t("st.off")}
              </span>
            </div>
            <div style={{ fontSize: 11.5, color: color.sec2, lineHeight: 1.55, marginTop: 4 }}>{t("st.localizeUIHelp")}</div>
          </div>
        </div>
        {!canEdit && <div style={{ fontSize: 11, color: color.muted, marginTop: 8 }}>{t("st.adminOnly")}</div>}
        <div style={{ marginTop: 12 }}>
          <Row label={t("st.supportedLangs")} value={s.features.supported_locales.join(" · ")} />
          <Row label={t("st.defaultOutput")} value={s.features.default_output_locale} />
        </div>
      </SectionCard>

      {/* LLM */}
      <SectionCard title={t("st.llm")} note={readOnlyNote}>
        <Row label={t("st.provider")} value={s.llm.provider} />
        <Row label={t("st.model")} value={s.llm.model} />
        <Row label={t("st.temperature")} value={s.llm.temperature} />
        <Row label={t("st.maxTokens")} value={s.llm.max_tokens} />
        <Row label={t("st.timeout")} value={s.llm.timeout_seconds} />
        <Row label={t("st.baseUrl")} value={s.llm.base_url} />
        <Row
          label={t("st.apiKey")}
          value={
            <span style={{ color: s.llm.key_configured ? color.greenFg : color.amberFg }}>
              {s.llm.key_configured ? t("st.keyConfigured") : t("st.keyMissing")}{" "}
              <span style={{ color: color.muted, fontWeight: 400 }}>({t("st.keyFrom")} {s.llm.api_key_env})</span>
            </span>
          }
        />
      </SectionCard>

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
