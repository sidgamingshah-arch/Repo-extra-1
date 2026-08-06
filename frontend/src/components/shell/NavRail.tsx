/** Left navigation rail: grouped screen links + an extraction-progress card. */
import { useLocation, useNavigate } from "react-router-dom";

import { useMe, useProject } from "../../lib/queries";
import { color } from "../../theme";
import { useT } from "../../i18n";
import { NAV_GROUPS, SCREENS, screenIdForPath } from "../../screens/config";

export function NavRail() {
  const nav = useNavigate();
  const loc = useLocation();
  const t = useT();
  const { data: me } = useMe();
  const activeId = screenIdForPath(loc.pathname);
  const { data } = useProject();
  const prog = data?.project.progress;

  // Role-gated nav: show a screen only if the caller's role may see it.
  const canSee = (id: string) => !me || me.screens.includes(id);
  const groups = NAV_GROUPS.map((g) => ({ ...g, items: g.items.filter(canSee) }))
    .filter((g) => g.items.length > 0);

  return (
    <div
      style={{
        width: 214,
        flex: "0 0 214px",
        background: "#fff",
        borderRight: `1px solid ${color.cardBorder}`,
        padding: "12px 0",
        overflowY: "auto",
      }}
    >
      {groups.map(({ group, items }) => (
        <div key={group}>
          <div style={{ padding: "12px 16px 5px" }}>
            <span style={{ fontSize: 10, fontWeight: 600, letterSpacing: ".7px", color: color.muted2 }}>
              {t(`group.${group}`)}
            </span>
          </div>
          {items.map((id) => {
            const s = SCREENS[id];
            const active = s.id === activeId;
            return (
              <div
                key={id}
                onClick={() => nav(s.path)}
                style={{
                  position: "relative",
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "8px 16px 8px 15px",
                  cursor: "pointer",
                  background: active ? color.indigoTint : "transparent",
                }}
              >
                <span
                  style={{
                    position: "absolute",
                    left: 0,
                    top: 6,
                    bottom: 6,
                    width: 3,
                    borderRadius: "0 3px 3px 0",
                    background: active ? color.indigo : "transparent",
                  }}
                />
                <span style={{ width: 17, textAlign: "center", fontSize: 13, color: active ? color.indigo : color.sec }}>
                  {s.icon}
                </span>
                <span style={{ fontSize: 12.5, fontWeight: active ? 600 : 500, color: active ? color.indigo : color.sec, flex: 1 }}>
                  {t(`nav.${s.id}`)}
                </span>
                {s.badge && (
                  <span
                    style={{
                      minWidth: 18,
                      height: 18,
                      padding: "0 5px",
                      borderRadius: 9,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 10,
                      fontWeight: 600,
                      background: s.badge.tone === "review" ? color.redBg : color.amberBg,
                      color: s.badge.tone === "review" ? color.redFg : color.amberFg,
                    }}
                  >
                    {s.badge.count}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      ))}

      <div
        style={{
          margin: "14px 16px 0",
          padding: "11px 12px",
          border: `1px solid ${color.cardBorder}`,
          borderRadius: 9,
          background: color.rowAltBg,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: color.sec2, marginBottom: 6 }}>
          <span>{t("progress.title")}</span>
          <span style={{ fontWeight: 600, color: color.ink }}>{prog?.pct ?? 0}%</span>
        </div>
        <div style={{ height: 6, borderRadius: 4, background: color.trackBg, overflow: "hidden" }}>
          <div style={{ width: `${prog?.pct ?? 0}%`, height: "100%", background: color.indigo }} />
        </div>
        <div style={{ fontSize: 10.5, color: color.muted2, marginTop: 7 }}>
          {prog ? `${prog.line_items} line items · ${prog.in_review} in review` : ""}
        </div>
      </div>
    </div>
  );
}
