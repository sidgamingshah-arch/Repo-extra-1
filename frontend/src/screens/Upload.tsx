/** Screen 1 — Documents & Template. Source docs dropzone + list, output template,
 * and ontology. Mirrors wireframe scrUpload verbatim. */
import { useNavigate } from "react-router-dom";

import { Button, Card } from "../components/ui";
import { color, font, radius } from "../theme";
import type { ExtractMode, SourceDoc } from "../types";
import { useProject } from "../lib/queries";
import { useUI } from "../store";
import { useT } from "../i18n";
import { useCan } from "../lib/rbac";
import { SCREENS } from "./config";

/** Extension chip color pairs (PDF → red, XLS → green). */
function extColors(ext: string): { bg: string; fg: string } {
  if (ext.toUpperCase().startsWith("XLS")) return { bg: color.greenBg, fg: color.greenFg };
  return { bg: color.redBg, fg: color.redFg };
}

/** Status tag color pairs (Mixed → amber, Native → green, Scanned → indigo tint). */
function tagColors(tag: SourceDoc["tag"]): { bg: string; fg: string } {
  if (tag === "Mixed") return { bg: color.amberBg, fg: color.amberFg };
  if (tag === "Native") return { bg: color.greenBg2, fg: color.greenFg };
  return { bg: color.indigoTint2, fg: color.indigo };
}

function DocRow({ doc }: { doc: SourceDoc }) {
  const ext = extColors(doc.ext);
  const tag = tagColors(doc.tag);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 11,
        padding: "10px 12px",
        border: `1px solid ${color.hairline3}`,
        borderRadius: 9,
        marginBottom: 8,
      }}
    >
      <span
        style={{
          width: 30,
          height: 30,
          borderRadius: 7,
          background: ext.bg,
          color: ext.fg,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 11,
          fontWeight: 600,
          flex: "0 0 auto",
        }}
      >
        {doc.ext}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5, fontWeight: 500 }}>{doc.name}</div>
        <div style={{ fontSize: 11, color: color.muted }}>{doc.meta}</div>
      </div>
      <span
        style={{
          fontSize: 10.5,
          fontWeight: 600,
          padding: "3px 8px",
          borderRadius: radius.pill,
          background: tag.bg,
          color: tag.fg,
        }}
      >
        {doc.tag}
      </span>
    </div>
  );
}

/** One selectable extraction-mode tile (radio semantics). */
function ModeOption({
  value,
  selected,
  onSelect,
  glyph,
  title,
  desc,
  badge,
}: {
  value: ExtractMode;
  selected: boolean;
  onSelect: (v: ExtractMode) => void;
  glyph: string;
  title: string;
  desc: string;
  badge?: string;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={() => onSelect(value)}
      style={{
        flex: 1,
        display: "flex",
        alignItems: "flex-start",
        gap: 11,
        textAlign: "start",
        padding: 13,
        borderRadius: 10,
        cursor: "pointer",
        fontFamily: font.sans,
        background: selected ? color.indigoTint : "#fff",
        border: `1.5px solid ${selected ? color.indigo : color.hairline3}`,
      }}
    >
      {/* radio dot */}
      <span
        aria-hidden
        style={{
          marginTop: 2,
          width: 16,
          height: 16,
          borderRadius: "50%",
          flex: "0 0 auto",
          border: `1.5px solid ${selected ? color.indigo : color.controlBorder}`,
          background: "#fff",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {selected && (
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: color.indigo }} />
        )}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
          <span style={{ fontSize: 13.5, fontWeight: 600 }}>
            <span style={{ color: color.faint, marginInlineEnd: 6 }}>{glyph}</span>
            {title}
          </span>
          {badge && (
            <span
              style={{
                fontSize: 9.5,
                fontWeight: 600,
                padding: "2px 7px",
                borderRadius: radius.pill,
                background: color.greenBg2,
                color: color.greenFg,
              }}
            >
              {badge}
            </span>
          )}
        </div>
        <div style={{ fontSize: 11.5, color: color.sec2, lineHeight: 1.45 }}>{desc}</div>
      </div>
    </button>
  );
}

export default function UploadScreen() {
  const navigate = useNavigate();
  const t = useT();
  const canTemplate = useCan("config:template");
  const canOntology = useCan("config:ontology");
  const extractMode = useUI((s) => s.extractMode);
  const setExtractMode = useUI((s) => s.setExtractMode);
  const { data, isPending } = useProject();

  if (isPending || !data) {
    return (
      <div style={{ padding: 60, textAlign: "center", color: color.muted }}>Loading…</div>
    );
  }

  const { project, documents } = data;
  const tpl = project.template;

  return (
    <div style={{ maxWidth: 1120, margin: "0 auto", padding: "26px 30px 60px" }}>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 5 }}>{t("u.title")}</h1>
        <p style={{ margin: 0, color: color.sec2 }}>{t("u.subhead")}</p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.55fr 1fr", gap: 18 }}>
        {/* LEFT — Source documents */}
        <Card>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 12,
            }}
          >
            <span style={{ fontWeight: 600, fontSize: 14 }}>{t("u.srcDocs")}</span>
            <span style={{ fontSize: 11, color: color.sec2 }}>{t("u.srcTypes")}</span>
          </div>
          <div
            style={{
              border: `1.5px dashed ${color.dashed}`,
              borderRadius: 10,
              background: color.rowAltBg,
              padding: 26,
              textAlign: "center",
              marginBottom: 14,
            }}
          >
            <div style={{ fontSize: 26, color: color.faint, marginBottom: 6 }}>⬍</div>
            <div style={{ fontWeight: 600, marginBottom: 3 }}>
              {t("u.dropHere")} <span style={{ color: color.indigo }}>{t("u.browse")}</span>
            </div>
            <div style={{ fontSize: 11.5, color: color.muted }}>{t("u.dropHint")}</div>
          </div>
          {documents.map((d) => (
            <DocRow key={d.name} doc={d} />
          ))}
        </Card>

        {/* RIGHT — Template + Ontology */}
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <Card>
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 11 }}>{t("u.outputTemplate")}</div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: 11,
                border: `1px solid ${color.indigoBorder}`,
                background: color.indigoTint,
                borderRadius: 9,
                marginBottom: 9,
              }}
            >
              <span
                style={{
                  width: 30,
                  height: 30,
                  borderRadius: 7,
                  background: color.indigo,
                  color: "#fff",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 14,
                  flex: "0 0 auto",
                }}
              >
                ▦
              </span>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 12.5, fontWeight: 600 }}>{tpl.name}</div>
                <div style={{ fontSize: 11, color: color.sec2 }}>{t("u.templateMeta")}</div>
              </div>
              <span style={{ fontSize: 11, color: color.indigo, fontWeight: 600 }}>{t("u.selected")}</span>
            </div>
            {canTemplate && (
              <div style={{ display: "flex", gap: 8 }}>
                <Button
                  variant="secondary"
                  style={{ flex: 1, fontSize: 11.5, padding: 8, borderRadius: radius.control }}
                >
                  {t("u.chooseAnother")}
                </Button>
                <Button
                  variant="ghost"
                  style={{ flex: 1, fontSize: 11.5, padding: 8, borderRadius: radius.control }}
                >
                  {t("u.newTemplate")}
                </Button>
              </div>
            )}
          </Card>

          <Card>
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 5 }}>{t("u.ontology")}</div>
            <p style={{ margin: "0 0 11px", fontSize: 11.5, color: color.sec2, lineHeight: 1.5 }}>
              {t("u.ontologyExplainer")}
            </p>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: 11,
                border: `1px solid ${color.hairline3}`,
                borderRadius: 9,
                marginBottom: 10,
              }}
            >
              <span
                style={{
                  width: 30,
                  height: 30,
                  borderRadius: 7,
                  background: color.greenBg2,
                  color: color.greenFg,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 13,
                  flex: "0 0 auto",
                }}
              >
                ◆
              </span>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 12.5, fontWeight: 600 }}>{project.ontology.file}</div>
                <div style={{ fontSize: 11, color: color.muted }}>1,240 rules · 380 aliases</div>
              </div>
              <span
                style={{
                  fontSize: 10.5,
                  fontWeight: 600,
                  padding: "3px 8px",
                  borderRadius: radius.pill,
                  background: color.greenBg2,
                  color: color.greenFg,
                }}
              >
                {t("u.valid")}
              </span>
            </div>
            {canOntology && (
              <button
                style={{
                  width: "100%",
                  fontSize: 11.5,
                  fontWeight: 600,
                  color: color.ink2,
                  background: "#fff",
                  border: `1px dashed ${color.dashed}`,
                  borderRadius: radius.control,
                  padding: 9,
                  cursor: "pointer",
                  fontFamily: font.sans,
                }}
              >
                {t("u.replaceOntology")}
              </button>
            )}
          </Card>
        </div>
      </div>

      {/* 4 · Extraction mode — auto (default) vs confirm page scope */}
      <Card style={{ marginTop: 18 }}>
        <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 3 }}>{t("u.mode")}</div>
        <p style={{ margin: "0 0 12px", fontSize: 11.5, color: color.sec2, lineHeight: 1.5 }}>
          {t("u.modeHint")}
        </p>
        <div role="radiogroup" aria-label={t("u.mode")} style={{ display: "flex", gap: 12 }}>
          <ModeOption
            value="auto"
            selected={extractMode === "auto"}
            onSelect={setExtractMode}
            glyph="⚡"
            title={t("u.autoTitle")}
            desc={t("u.autoDesc")}
            badge={t("u.autoRec")}
          />
          <ModeOption
            value="confirm"
            selected={extractMode === "confirm"}
            onSelect={setExtractMode}
            glyph="▦"
            title={t("u.confirmTitle")}
            desc={t("u.confirmDesc")}
          />
        </div>
      </Card>

      <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 20 }}>
        <Button variant="secondary" style={{ padding: "10px 18px" }}>
          {t("u.saveDraft")}
        </Button>
        <Button style={{ padding: "10px 22px" }} onClick={() => navigate(SCREENS.integrity.path)}>
          {t("u.runIntegrity")} →
        </Button>
      </div>
    </div>
  );
}
