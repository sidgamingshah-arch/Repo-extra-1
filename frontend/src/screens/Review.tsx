/** Screen 5 — Review queue. Automated-check failures grouped by type; each expands
 * into a reconciliation breakdown + suggested fix with resolution actions. */
import { useNavigate } from "react-router-dom";

import { Button } from "../components/ui";
import { useDocumentReview, useReview, useProjectLoaded } from "../lib/queries";
import { EmptyState } from "../components/EmptyState";
import { SCREENS } from "./config";
import { useAppLocale, useUI } from "../store";
import { useT } from "../i18n";
import { useCan } from "../lib/rbac";
import { color, font } from "../theme";
import type { ReviewCheck } from "../types";

/** tone → { accent, iconBg } — mirrors ac / ib in the wireframe. */
function toneColors(tone: ReviewCheck["tone"]): { ac: string; ib: string } {
  if (tone === "low") return { ac: color.redFg, ib: color.redBg };
  if (tone === "med") return { ac: color.amberFg, ib: color.amberBg };
  return { ac: color.indigo, ib: color.indigoTint2 };
}

export default function ReviewScreen() {
  const t = useT();
  const locale = useAppLocale();
  const canResolve = useCan("review:resolve");
  const activeDocumentId = useUI((s) => s.activeDocumentId);
  const usingReal = !!activeDocumentId;
  const loaded = useProjectLoaded();
  const realQ = useDocumentReview(activeDocumentId ?? undefined, locale);
  const demoQ = useReview(locale, !usingReal);
  const data = usingReal ? realQ.data : demoQ.data;
  const isPending = usingReal ? realQ.isPending : demoQ.isPending;
  const openCheck = useUI((s) => s.openCheck);
  const toggleCheck = useUI((s) => s.toggleCheck);
  const navigate = useNavigate();

  // No real document and no admin-seeded demo → greenfield guidance.
  if (!usingReal && !loaded) return <EmptyState />;
  if (usingReal && realQ.isError) return <EmptyState />;
  if (isPending || !data) {
    return (
      <div style={{ padding: 60, textAlign: "center", color: color.muted, fontSize: 13 }}>
        Loading…
      </div>
    );
  }

  const { checks, tabs, summary } = data;

  return (
    <div style={{ maxWidth: 1080, margin: "0 auto", padding: "26px 30px 60px" }}>
      {/* Header row */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          marginBottom: 16,
        }}
      >
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 5 }}>{t("r.title")}</h1>
          <p style={{ margin: 0, color: color.sec2 }}>{t("r.subhead")}</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Counter value={summary.open} label={t("r.open")} fg={color.redFg} />
          <Counter value={summary.passed} label={t("r.passed")} fg={color.greenFg} />
        </div>
      </div>

      {/* Filter tabs */}
      <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
        {tabs.map((t, i) => {
          const on = i === 0;
          return (
            <span
              key={t.label}
              style={{
                fontSize: 11.5,
                fontWeight: 600,
                padding: "6px 12px",
                borderRadius: 8,
                background: on ? color.stepperActive : "#fff",
                color: on ? "#fff" : color.sec,
                border: `1px solid ${on ? color.stepperActive : color.controlBorder}`,
                cursor: "pointer",
              }}
            >
              {t.label} <span style={{ opacity: 0.7 }}>{t.count}</span>
            </span>
          );
        })}
      </div>

      {/* Check cards */}
      {checks.map((c) => {
        const open = openCheck === c.id;
        const { ac, ib } = toneColors(c.tone);
        return (
          <div
            key={c.id}
            style={{
              background: "#fff",
              border: `1px solid ${open ? ac : color.cardBorder}`,
              borderLeft: `3px solid ${ac}`,
              borderRadius: 11,
              marginBottom: 12,
              overflow: "hidden",
            }}
          >
            {/* Header */}
            <div
              onClick={() => toggleCheck(c.id)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 13,
                padding: "14px 16px",
                cursor: "pointer",
              }}
            >
              <span
                style={{
                  width: 26,
                  height: 26,
                  borderRadius: 7,
                  background: ib,
                  color: ac,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 13,
                  fontWeight: 700,
                  flex: "0 0 auto",
                }}
              >
                {c.icon}
              </span>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{c.title}</div>
                <div style={{ fontSize: 11.5, color: color.muted }}>{c.where}</div>
              </div>
              <span
                style={{
                  fontSize: 10.5,
                  fontWeight: 600,
                  padding: "3px 9px",
                  borderRadius: 20,
                  background: ib,
                  color: ac,
                }}
              >
                {c.severity}
              </span>
              <span style={{ fontFamily: font.mono, fontSize: 12, color: ac, fontWeight: 600 }}>
                {c.delta}
              </span>
              <span style={{ fontSize: 11, color: color.faint }}>{open ? "▲" : "▼"}</span>
            </div>

            {/* Body */}
            {open && (
              <div
                style={{
                  borderTop: `1px solid ${color.hairline2}`,
                  padding: "15px 16px 16px",
                  background: "#fbfcfd",
                }}
              >
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr 1fr",
                    gap: 20,
                    marginBottom: 14,
                  }}
                >
                  {/* LEFT — reconciliation */}
                  <div>
                    <div
                      style={{
                        fontSize: 10.5,
                        fontWeight: 600,
                        letterSpacing: 0.4,
                        color: color.muted,
                        marginBottom: 8,
                      }}
                    >
                      {t("r.reconciliation")}
                    </div>
                    {c.calc.map(([label, value, hl], idx) => (
                      <div
                        key={idx}
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          padding: "5px 0",
                          borderBottom: `1px dashed ${color.hairline2}`,
                        }}
                      >
                        <span
                          style={{
                            fontSize: 12,
                            color: hl ? ac : color.sec,
                            fontWeight: hl ? 600 : 400,
                          }}
                        >
                          {label}
                        </span>
                        <span
                          style={{
                            fontFamily: font.mono,
                            fontSize: 12,
                            color: hl ? ac : color.sec,
                            fontWeight: hl ? 600 : 400,
                          }}
                        >
                          {value}
                        </span>
                      </div>
                    ))}
                  </div>

                  {/* RIGHT — suggested fix */}
                  <div>
                    <div
                      style={{
                        fontSize: 10.5,
                        fontWeight: 600,
                        letterSpacing: 0.4,
                        color: color.muted,
                        marginBottom: 8,
                      }}
                    >
                      {t("r.suggestedFix")}
                    </div>
                    <div
                      style={{
                        fontSize: 12,
                        color: color.ink2,
                        lineHeight: 1.55,
                        background: "#fff",
                        border: `1px solid ${color.hairline3}`,
                        borderRadius: 8,
                        padding: 11,
                      }}
                    >
                      {c.fix}
                    </div>
                  </div>
                </div>

                {/* Actions */}
                <div style={{ display: "flex", gap: 9 }}>
                  {canResolve && (
                    <Button variant="primary" style={{ fontSize: 12, padding: "8px 15px", borderRadius: 8 }}>
                      {t("r.applyFix")}
                    </Button>
                  )}
                  <Button
                    variant="secondary"
                    onClick={() => navigate(SCREENS.workspace.path)}
                    style={{ fontSize: 12, padding: "8px 15px", borderRadius: 8 }}
                  >
                    {t("r.openInWorkspace")}
                  </Button>
                  {canResolve && (
                    <Button
                      variant="secondary"
                      style={{
                        fontSize: 12,
                        padding: "8px 15px",
                        borderRadius: 8,
                        color: color.sec2,
                        border: `1px solid ${color.cardBorder}`,
                      }}
                    >
                      {t("r.acceptAsIs")}
                    </Button>
                  )}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Counter({ value, label, fg }: { value: number; label: string; fg: string }) {
  return (
    <div
      style={{
        textAlign: "center",
        background: "#fff",
        border: `1px solid ${color.cardBorder}`,
        borderRadius: 10,
        padding: "9px 14px",
      }}
    >
      <div style={{ fontSize: 18, fontWeight: 700, color: fg, fontFamily: font.mono }}>{value}</div>
      <div style={{ fontSize: 10, color: color.muted }}>{label}</div>
    </div>
  );
}
