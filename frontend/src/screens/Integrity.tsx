/** Screen 2 — Document integrity. Pre-flight scan results (score, stats, issues). */
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

import { Button, Card } from "../components/ui";
import { EmptyState } from "../components/EmptyState";
import { color, font, radius } from "../theme";
import type { IntegrityIssue, IntegrityStat } from "../types";
import { useDocumentIntegrity, useIntegrity, useProjectLoaded } from "../lib/queries";
import { useAppLocale, useUI } from "../store";
import { SCREENS } from "./config";
import { useT } from "../i18n";

const GRID = "26px 1.7fr 90px 1fr 110px";

/** stat value color by tone. */
function toneColor(tone: IntegrityStat["tone"]): string {
  if (tone === "warn") return color.amberFg;
  if (tone === "ok") return color.greenFg;
  return color.ink;
}

/** issue severity → dot color + status pill bg/fg. */
function sevStyle(sev: IntegrityIssue["severity"]): { dot: string; bg: string; fg: string } {
  if (sev === "warn") return { dot: color.amberFg, bg: color.amberBg, fg: color.amberFg };
  if (sev === "low") return { dot: color.redFg, bg: color.redBg, fg: color.redFg };
  return { dot: color.greenFg, bg: color.greenBg2, fg: color.greenFg };
}

export default function IntegrityScreen() {
  const navigate = useNavigate();
  const t = useT();
  const locale = useAppLocale();
  const extractMode = useUI((s) => s.extractMode);
  const activeDocumentId = useUI((s) => s.activeDocumentId);
  const setActiveDocumentId = useUI((s) => s.setActiveDocumentId);

  // The document explicitly being worked this session (set on upload, persisted across
  // refresh) drives the screen. We deliberately do NOT fall back to "the most recent
  // document in the list" — that could be another session's file. When there's no active
  // document, the demo project shows only if an admin has enabled seed_demo; otherwise the
  // greenfield empty state. So real runs are deterministic and demo never leaks in.
  const docId = activeDocumentId ?? undefined;
  const usingReal = !!docId;
  const realQ = useDocumentIntegrity(docId);
  const loaded = useProjectLoaded();
  const demoQ = useIntegrity(locale, !usingReal);

  // A persisted/stale active id that no longer resolves (deleted doc, DB reset, duplicate)
  // will 404 — clear it so the app falls back cleanly instead of showing a raw error.
  useEffect(() => {
    if (usingReal && realQ.isError) setActiveDocumentId(null);
  }, [usingReal, realQ.isError, setActiveDocumentId]);

  const data = usingReal ? realQ.data : demoQ.data;
  const isPending = usingReal ? realQ.isPending : demoQ.isPending;

  const goNext = () => {
    // Confirm-scope mode pauses on Page Scope first (real pages); auto goes straight to the
    // real extraction. Demo path keeps the workspace/scope destinations.
    if (usingReal) {
      return navigate(extractMode === "auto" ? `/documents/${docId}` : SCREENS.scope.path);
    }
    navigate(extractMode === "auto" ? SCREENS.workspace.path : SCREENS.scope.path);
  };

  // No real document to work: demo only if an admin enabled it, else greenfield guidance.
  if (!usingReal && !loaded) return <EmptyState />;
  // Real doc's integrity couldn't load — degrade to guidance (effect clears the stale id).
  if (usingReal && realQ.isError) return <EmptyState />;
  if (isPending || !data) {
    return (
      <div style={{ padding: 60, textAlign: "center", color: color.muted }}>Loading…</div>
    );
  }

  return (
    <div style={{ maxWidth: 1120, margin: "0 auto", padding: "26px 30px 60px" }}>
      {/* Header: title + integrity-score card */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          marginBottom: 18,
        }}
      >
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 5 }}>{t("i.title")}</h1>
          <p style={{ margin: 0, color: color.sec2 }}>{t("i.subhead")}</p>
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 14,
            background: color.surface,
            border: `1px solid ${color.cardBorder}`,
            borderRadius: radius.card,
            padding: "12px 18px",
          }}
        >
          <div style={{ textAlign: "center" }}>
            <div
              style={{
                fontSize: 26,
                fontWeight: 700,
                color: color.amberFg,
                lineHeight: 1,
                fontFamily: font.mono,
              }}
            >
              {data.score}
            </div>
            <div style={{ fontSize: 10, color: color.muted, marginTop: 3 }}>/100</div>
          </div>
          <div style={{ lineHeight: 1.3 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600 }}>{data.grade}</div>
            <div style={{ fontSize: 11, color: color.muted }}>{data.summary}</div>
          </div>
        </div>
      </div>

      {/* Stat row */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4,1fr)",
          gap: 12,
          marginBottom: 18,
        }}
      >
        {data.stats.map((s, i) => (
          <div
            key={i}
            style={{
              background: color.surface,
              border: `1px solid ${color.cardBorder}`,
              borderRadius: radius.cardSm,
              padding: "14px 15px",
            }}
          >
            <div style={{ fontSize: 11, color: color.muted, marginBottom: 7 }}>{s.label}</div>
            <div
              style={{
                fontSize: 19,
                fontWeight: 600,
                fontFamily: font.mono,
                color: toneColor(s.tone),
              }}
            >
              {s.value}
            </div>
            <div style={{ fontSize: 10.5, color: color.muted2, marginTop: 4 }}>{s.sub}</div>
          </div>
        ))}
      </div>

      {/* Issues table */}
      <Card pad={0} style={{ overflow: "hidden" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: GRID,
            gap: 12,
            padding: "11px 16px",
            background: color.rowAltBg,
            borderBottom: `1px solid #e8eaee`,
            fontSize: 10.5,
            fontWeight: 600,
            letterSpacing: 0.4,
            color: color.muted,
          }}
        >
          <span></span>
          <span>{t("i.col.issue")}</span>
          <span>{t("i.col.pages")}</span>
          <span>{t("i.col.detail")}</span>
          <span>{t("i.col.status")}</span>
        </div>
        {data.issues.map((i, idx) => {
          const sev = sevStyle(i.severity);
          return (
            <div
              key={idx}
              style={{
                display: "grid",
                gridTemplateColumns: GRID,
                gap: 12,
                padding: "13px 16px",
                alignItems: "center",
                borderBottom: `1px solid ${color.hairline2}`,
              }}
            >
              <span
                style={{ width: 9, height: 9, borderRadius: "50%", background: sev.dot }}
              />
              <div>
                <div style={{ fontSize: 12.5, fontWeight: 600 }}>{i.title}</div>
                <div style={{ fontSize: 11, color: color.muted }}>{i.detail}</div>
              </div>
              <span style={{ fontFamily: font.mono, fontSize: 11.5, color: color.sec }}>
                {i.pages}
              </span>
              <span style={{ fontSize: 11.5, color: color.sec }}>{i.note}</span>
              <span
                style={{
                  justifySelf: "start",
                  fontSize: 10.5,
                  fontWeight: 600,
                  padding: "3px 9px",
                  borderRadius: radius.pill,
                  background: sev.bg,
                  color: sev.fg,
                }}
              >
                {i.status}
              </span>
            </div>
          );
        })}
      </Card>

      {/* Footer */}
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 20 }}>
        <Button variant="secondary" onClick={() => navigate("/upload")}>
          ← {t("i.back")}
        </Button>
        <Button onClick={goNext}>
          {usingReal || extractMode === "auto" ? t("i.extractNow") : t("i.detect")} →
        </Button>
      </div>
    </div>
  );
}
