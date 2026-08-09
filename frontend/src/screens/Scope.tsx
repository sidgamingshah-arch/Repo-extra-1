/** Screen 3 — Statement page detection. Mirrors the wireframe's scrDetect(). */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button, Toggle } from "../components/ui";
import { EmptyState } from "../components/EmptyState";
import { SCREENS } from "./config";
import {
  useDocumentPages, usePages, useProjectLoaded, useSetDocumentScope,
} from "../lib/queries";
import { useAppLocale, useUI } from "../store";
import { useT } from "../i18n";
import { useCan } from "../lib/rbac";
import { color, confStyle, font, layout, radius } from "../theme";
import type { PageCard } from "../types";

function PageCardTile(
  { p, t, canScope, included, onToggle }:
  { p: PageCard; t: (key: string) => string; canScope: boolean;
    included: boolean; onToggle?: () => void },
) {
  const cc = confStyle(p.conf);
  const scanned = p.scan === "scanned";
  return (
    <div
      style={{
        background: color.surface,
        border: `1.5px solid ${included ? color.indigo : color.cardBorder}`,
        borderRadius: radius.cardSm,
        overflow: "hidden",
      }}
    >
      {/* Faux thumbnail */}
      <div
        style={{
          height: 118,
          background: "#f6f7f9",
          position: "relative",
          padding: "11px 12px",
          borderBottom: `1px solid ${color.hairline3}`,
        }}
      >
        <div style={{ height: 6, width: "60%", background: "#dde1e7", borderRadius: 2, marginBottom: 7 }} />
        <div style={{ height: 4, width: "88%", background: color.trackBg, borderRadius: 2, marginBottom: 4 }} />
        <div style={{ height: 4, width: "80%", background: color.trackBg, borderRadius: 2, marginBottom: 4 }} />
        <div style={{ height: 4, width: "90%", background: color.trackBg, borderRadius: 2, marginBottom: 4 }} />
        <div style={{ height: 4, width: "72%", background: color.trackBg, borderRadius: 2 }} />
        <span
          style={{
            position: "absolute",
            top: 8,
            right: 9,
            fontSize: 9.5,
            fontWeight: 600,
            padding: "2px 6px",
            borderRadius: 5,
            background: scanned ? color.redBg : color.greenBg2,
            color: scanned ? color.redFg : color.greenFg,
          }}
        >
          {scanned ? t("sc.scan") : t("sc.native")}
        </span>
        <span
          style={{
            position: "absolute",
            bottom: 8,
            right: 9,
            fontFamily: font.mono,
            fontSize: 10,
            color: color.faint,
          }}
        >
          p.{p.no}
        </span>
      </div>
      {/* Body */}
      <div style={{ padding: "9px 11px" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 5,
          }}
        >
          <span style={{ fontSize: 11.5, fontWeight: 600, color: included ? color.ink : color.muted2 }}>
            {p.cls}
          </span>
          <span style={{ fontSize: 10, fontFamily: font.mono, color: cc.fg }}>{cc.pct}</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontSize: 10.5, color: color.muted2 }}>
            {included ? t("sc.inScope") : t("sc.skipped")}
          </span>
          <span
            onClick={canScope && onToggle ? onToggle : undefined}
            style={canScope && onToggle ? { cursor: "pointer" } : { pointerEvents: "none", opacity: 0.5 }}
          >
            <Toggle on={included} />
          </span>
        </div>
      </div>
    </div>
  );
}

export default function ScopeScreen() {
  const nav = useNavigate();
  const t = useT();
  const locale = useAppLocale();
  const canScope = useCan("config:scope");
  const activeDocumentId = useUI((s) => s.activeDocumentId);
  const usingReal = !!activeDocumentId;
  const loaded = useProjectLoaded();
  const realQ = useDocumentPages(activeDocumentId ?? undefined);
  const demoQ = usePages(locale, !usingReal);
  const data = usingReal ? realQ.data : demoQ.data;
  const isPending = usingReal ? realQ.isPending : demoQ.isPending;
  const setScope = useSetDocumentScope(activeDocumentId ?? undefined);

  // Local selection of INCLUDED page indices (0-based), synced from the fetched pages. On a
  // real document, toggling persists the scope so extraction restricts itself to it.
  const [selected, setSelected] = useState<Set<number> | null>(null);
  useEffect(() => {
    if (data) {
      setSelected(new Set(data.pages.filter((p) => p.included).map((p) => p.no - 1)));
    }
  }, [data]);

  const toggle = (idx: number) => {
    setSelected((prev) => {
      const next = new Set(prev ?? []);
      next.has(idx) ? next.delete(idx) : next.add(idx);
      if (usingReal) setScope.mutate([...next]);
      return next;
    });
  };

  if (!usingReal && !loaded) return <EmptyState />;
  if (usingReal && realQ.isError) return <EmptyState />;
  if (isPending || !data) {
    return (
      <div style={{ padding: 60, textAlign: "center", color: color.muted }}>Loading…</div>
    );
  }

  // Focused = the live local selection (so counts move with the toggles); fall back to the
  // server's figure until the first sync.
  const focused = selected ? selected.size : data.focused;

  return (
    <div style={{ maxWidth: layout.screenMaxWide, margin: "0 auto", padding: "26px 30px 60px" }}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          marginBottom: 16,
        }}
      >
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 5 }}>{t("sc.title")}</h1>
          <p style={{ margin: 0, color: color.sec2 }}>{t("sc.subhead")}</p>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 12.5, fontWeight: 600 }}>
            {t("sc.focused")} <span style={{ color: color.indigo }}>{focused} of {data.total}</span> {t("sc.pages")}
          </div>
          <div style={{ fontSize: 11, color: color.muted }}>{data.total - focused} {t("sc.pagesSkipped")}</div>
        </div>
      </div>

      {/* Filter chips */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        {data.filters.map((f, i) => {
          const active = i === 0;
          return (
            <span
              key={f.label}
              style={{
                fontSize: 11.5,
                fontWeight: 600,
                padding: "6px 12px",
                borderRadius: radius.pill,
                border: `1px solid ${active ? color.stepperActive : color.controlBorder}`,
                background: active ? color.stepperActive : color.surface,
                color: active ? "#fff" : color.sec,
                cursor: "pointer",
              }}
            >
              {f.label} <span style={{ opacity: 0.6 }}>{f.count}</span>
            </span>
          );
        })}
      </div>

      {/* Page grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill,minmax(158px,1fr))",
          gap: 14,
        }}
      >
        {data.pages.map((p) => (
          <PageCardTile
            key={p.no}
            p={p}
            t={t}
            canScope={canScope && usingReal}
            included={selected ? selected.has(p.no - 1) : p.included}
            onToggle={() => toggle(p.no - 1)}
          />
        ))}
      </div>

      {/* Footer */}
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 22 }}>
        <Button variant="secondary" onClick={() => nav(SCREENS.integrity.path)}>
          ← {t("sc.back")}
        </Button>
        <Button onClick={() => nav(usingReal ? `/documents/${activeDocumentId}` : SCREENS.workspace.path)}>
          {t("sc.extract")} {focused} {t("sc.pages")} →
        </Button>
      </div>
    </div>
  );
}
