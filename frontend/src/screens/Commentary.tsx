/** Analysis — a one-page financial commentary derived from the extracted statements:
 * headline + assessment, key ratios (tone-coded), and selected strengths / risks. */
import { Card, ScreenHeader } from "../components/ui";
import { useT } from "../i18n";
import { useAudit, useCommentary, useProjectLoaded, useRunAnalysis } from "../lib/queries";
import { EmptyState } from "../components/EmptyState";
import { useCan } from "../lib/rbac";
import { useAppLocale } from "../store";
import { color, fmtIN, font, radius } from "../theme";
import type { AuditEntry, CommentaryMetric, CommentaryTrend } from "../types";

function toneColors(tone: CommentaryMetric["tone"]): { fg: string; bg: string } {
  if (tone === "good") return { fg: color.greenFg, bg: color.greenBg };
  if (tone === "bad") return { fg: color.redFg, bg: color.redBg };
  return { fg: color.amberFg, bg: color.amberBg };
}

function MetricTile({ m }: { m: CommentaryMetric }) {
  const c = toneColors(m.tone);
  return (
    <div style={{ background: color.surface, border: `1px solid ${color.cardBorder}`, borderRadius: 11, padding: "13px 15px" }}>
      <div style={{ fontSize: 11, color: color.muted, marginBottom: 7, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
        {m.label}
      </div>
      <div style={{ fontSize: 20, fontWeight: 600, fontFamily: font.mono, color: c.fg }}>{m.value}</div>
      <div style={{ marginTop: 6, height: 4, borderRadius: 3, background: c.bg }} />
    </div>
  );
}

/** Format a trend value / delta by kind (amount → grouped crore + YoY %; percent →
 * percentage points; ratio → absolute change). */
function trendValue(kind: CommentaryTrend["kind"], v: number): string {
  if (kind === "amount") return fmtIN(v);
  if (kind === "percent") return `${v}%`;
  return v.toFixed(2);
}
function trendDelta(t: CommentaryTrend): string {
  const sign = t.delta > 0 ? "+" : "";
  if (t.kind === "amount") return `${sign}${t.delta}%`;
  if (t.kind === "percent") return `${sign}${t.delta} pp`;
  return `${sign}${t.delta}`;
}

function TrendTile({ t, vs }: { t: CommentaryTrend; vs: string }) {
  const c = t.tone === "good" ? { fg: color.greenFg, bg: color.greenBg }
    : t.tone === "bad" ? { fg: color.redFg, bg: color.redBg }
    : { fg: color.amberFg, bg: color.amberBg };
  const arrow = t.direction === "up" ? "▲" : t.direction === "down" ? "▼" : "▬";
  return (
    <div style={{ background: color.surface, border: `1px solid ${color.cardBorder}`, borderRadius: 11, padding: "12px 14px" }}>
      <div style={{ fontSize: 11, color: color.muted, marginBottom: 7, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
        {t.label}
      </div>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8 }}>
        <span style={{ fontSize: 17, fontWeight: 600, fontFamily: font.mono, color: color.ink }}>
          {trendValue(t.kind, t.current)}
        </span>
        <span style={{ fontSize: 11.5, fontWeight: 600, fontFamily: font.mono, color: c.fg, whiteSpace: "nowrap" }}>
          {arrow} {trendDelta(t)}
        </span>
      </div>
      <div style={{ fontSize: 10.5, color: color.muted2, fontFamily: font.mono, marginTop: 5 }}>
        {trendValue(t.kind, t.prior)} <span style={{ color: color.faint }}>{vs}</span> {trendValue(t.kind, t.current)}
      </div>
    </div>
  );
}

function PointList({ title, points, accent }: { title: string; points: string[]; accent: string }) {
  return (
    <Card style={{ borderLeft: `3px solid ${accent}` }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 11 }}>{title}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {points.map((p, i) => (
          <div key={i} style={{ display: "flex", gap: 9, alignItems: "flex-start" }}>
            <span style={{ color: accent, fontSize: 13, lineHeight: "18px", flex: "0 0 auto" }}>◆</span>
            <span style={{ fontSize: 12.5, color: color.ink2, lineHeight: 1.5 }}>{p}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

/** Format a token count with grouping, or an em-dash when the run used no LLM. */
function tok(n: number | null): string {
  return n === null || n === undefined ? "—" : n.toLocaleString();
}

function AuditLog({ t }: { t: (k: string) => string }) {
  const { data } = useAudit();
  const entries = data?.entries ?? [];
  const AUDIT_GRID = "1.7fr 1.1fr 0.8fr 1.3fr 0.9fr 0.9fr 0.8fr";
  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, margin: "4px 2px 10px" }}>
        <span style={{ fontSize: 10.5, fontWeight: 600, letterSpacing: 0.4, color: color.muted }}>
          {t("cm.audit").toUpperCase()}
        </span>
        <span style={{ fontSize: 11, color: color.muted2 }}>{t("cm.auditHint")}</span>
      </div>
      <Card pad={0} style={{ overflow: "hidden" }}>
        <div
          style={{
            display: "grid", gridTemplateColumns: AUDIT_GRID, gap: 10, padding: "10px 14px",
            background: color.rowAltBg, borderBottom: `1px solid ${color.hairline2}`,
            fontSize: 10, fontWeight: 600, letterSpacing: 0.3, color: color.muted,
          }}
        >
          <span>{t("cm.col.run")}</span>
          <span>{t("cm.col.time")}</span>
          <span>{t("cm.col.action")}</span>
          <span>{t("cm.col.model")}</span>
          <span style={{ textAlign: "right" }}>{t("cm.col.inTok")}</span>
          <span style={{ textAlign: "right" }}>{t("cm.col.outTok")}</span>
          <span style={{ textAlign: "right" }}>{t("cm.col.totTok")}</span>
        </div>
        {entries.length === 0 && (
          <div style={{ padding: "16px 14px", fontSize: 12, color: color.muted }}>{t("cm.auditEmpty")}</div>
        )}
        {entries.map((e: AuditEntry) => (
          <div
            key={e.run_id}
            style={{
              display: "grid", gridTemplateColumns: AUDIT_GRID, gap: 10, padding: "11px 14px",
              alignItems: "center", borderBottom: `1px solid ${color.hairline2}`,
              opacity: e.status === "failed" ? 0.6 : 1,
            }}
          >
            <span style={{ fontFamily: font.mono, fontSize: 10.5, color: color.ink2, wordBreak: "break-all" }}>
              {e.run_id}
            </span>
            <span style={{ fontSize: 11, color: color.sec2 }}>
              {new Date(e.created_at).toLocaleString()}
            </span>
            <span style={{ fontSize: 11 }}>
              <span
                style={{
                  fontSize: 10, fontWeight: 600, padding: "2px 7px", borderRadius: radius.pill,
                  background: e.action === "analysis" ? color.indigoTint2 : color.greenBg2,
                  color: e.action === "analysis" ? color.indigo : color.greenFg,
                }}
              >
                {e.action}
              </span>
            </span>
            <span style={{ fontFamily: font.mono, fontSize: 10.5, color: color.sec }}>{e.model}</span>
            <span style={{ fontFamily: font.mono, fontSize: 11.5, textAlign: "right", color: color.ink }}>
              {tok(e.input_tokens)}
            </span>
            <span style={{ fontFamily: font.mono, fontSize: 11.5, textAlign: "right", color: color.ink }}>
              {tok(e.output_tokens)}
            </span>
            <span style={{ fontFamily: font.mono, fontSize: 11.5, fontWeight: 600, textAlign: "right", color: color.ink }}>
              {tok(e.total_tokens)}
            </span>
          </div>
        ))}
      </Card>
    </div>
  );
}

export default function CommentaryScreen() {
  const t = useT();
  const locale = useAppLocale();
  const loaded = useProjectLoaded();
  const { data, isPending } = useCommentary(locale);
  const canGenerate = useCan("analysis:run");
  const runAnalysis = useRunAnalysis();

  if (!loaded) return <EmptyState />;
  if (isPending || !data) {
    return <div style={{ padding: 60, textAlign: "center", color: color.muted }}>Loading…</div>;
  }

  return (
    <div style={{ maxWidth: 1080, margin: "0 auto", padding: "26px 30px 60px" }}>
      <ScreenHeader
        title={t("cm.title")}
        subtitle={t("cm.subhead")}
        right={
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {canGenerate && (
              <button
                onClick={() => runAnalysis.mutate()}
                disabled={runAnalysis.isPending}
                style={{
                  fontSize: 12, fontWeight: 600, color: "#fff",
                  background: runAnalysis.isPending ? color.faint : color.indigo,
                  border: "none", borderRadius: 8, padding: "8px 14px",
                  cursor: runAnalysis.isPending ? "default" : "pointer",
                }}
              >
                {runAnalysis.isPending ? t("cm.generating") : `✦ ${t("cm.generate")}`}
              </button>
            )}
            <button
              onClick={() => window.print()}
              style={{
                fontSize: 12, fontWeight: 600, color: color.ink2, background: "#fff",
                border: `1px solid ${color.controlBorder}`, borderRadius: 8, padding: "8px 14px", cursor: "pointer",
              }}
            >
              {t("cm.print")}
            </button>
          </div>
        }
      />

      {canGenerate && runAnalysis.isError && (
        <div
          style={{
            marginBottom: 14, padding: "10px 13px", background: color.redBg,
            border: `1px solid ${color.redBg}`, borderRadius: 9, fontSize: 12, color: color.redFg,
          }}
        >
          <b>{t("cm.genFailed")}.</b>{" "}
          <span style={{ fontFamily: font.mono, fontSize: 11 }}>
            {(runAnalysis.error as Error)?.message}
          </span>
        </div>
      )}

      {/* Headline + assessment */}
      <Card style={{ marginBottom: 16, borderLeft: `3px solid ${color.indigo}` }}>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8, lineHeight: 1.4 }}>{data.headline}</div>
        <div style={{ fontSize: 10.5, color: color.muted, fontFamily: font.mono, marginBottom: 10 }}>{data.basis}</div>
        <div style={{ fontSize: 12.5, color: color.sec, lineHeight: 1.6 }}>{data.assessment}</div>
      </Card>

      {/* Key metrics */}
      <div style={{ fontSize: 10.5, fontWeight: 600, letterSpacing: 0.4, color: color.muted, margin: "4px 2px 10px" }}>
        {t("cm.metrics").toUpperCase()}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 18 }}>
        {data.metrics.map((m) => (
          <MetricTile key={m.key} m={m} />
        ))}
      </div>

      {/* Year-on-year trends */}
      {data.trends?.length > 0 && (
        <>
          <div style={{ fontSize: 10.5, fontWeight: 600, letterSpacing: 0.4, color: color.muted, margin: "4px 2px 10px" }}>
            {t("cm.trends").toUpperCase()}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 18 }}>
            {data.trends.map((tr) => (
              <TrendTile key={tr.key} t={tr} vs={t("cm.trendVs")} />
            ))}
          </div>
        </>
      )}

      {/* Strengths / weaknesses */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
        <PointList title={t("cm.strengths")} points={data.strengths} accent={color.greenFg} />
        <PointList title={t("cm.weaknesses")} points={data.weaknesses} accent={color.amberFg} />
      </div>

      {/* Data quality */}
      <div
        style={{
          padding: "13px 15px", background: color.amberBg, border: `1px solid ${color.amberBg}`,
          borderRadius: 10, fontSize: 12, color: color.amberFg, lineHeight: 1.55,
        }}
      >
        <b>{t("cm.dataQuality")}.</b> {data.data_quality}
      </div>

      {/* Audit log — LLM/extraction runs with per-run input/output token usage */}
      <div style={{ marginTop: 20 }}>
        <AuditLog t={t} />
      </div>
    </div>
  );
}
