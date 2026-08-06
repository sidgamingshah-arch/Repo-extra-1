/** Fixed top bar: logo + wordmark + active document title + pipeline stepper + avatar.
 * The stepper marks steps before the current pipeline position as done (green check). */
import { useLocation, useNavigate } from "react-router-dom";

import { useProject } from "../../lib/queries";
import { color } from "../../theme";
import { useT } from "../../i18n";
import { STEPPER, screenIdForPath } from "../../screens/config";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { UserMenu } from "./UserMenu";

export function TopBar() {
  const nav = useNavigate();
  const loc = useLocation();
  const { data } = useProject();
  const t = useT();
  const activeId = screenIdForPath(loc.pathname);
  const curIdx = STEPPER.findIndex((s) => s.id === activeId);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 16,
        height: 52,
        flex: "0 0 52px",
        padding: "0 16px",
        background: color.topbar,
        color: "#e7ebf1",
        borderBottom: `1px solid ${color.topbarBorder}`,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
        <div
          style={{
            width: 26,
            height: 26,
            borderRadius: 6,
            background: color.indigo,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 700,
            fontSize: 13,
            color: "#fff",
          }}
        >
          FX
        </div>
        <span style={{ fontWeight: 600, letterSpacing: ".2px" }}>FinExtract</span>
      </div>

      <div style={{ width: 1, height: 22, background: color.divider }} />

      <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.25, minWidth: 0, overflow: "hidden" }}>
        <span style={{ fontWeight: 600, fontSize: 12.5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {data?.project.title ?? "Loading…"}
        </span>
        <span style={{ fontSize: 11, color: color.muted, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {data ? `${data.project.filename} · ${data.project.pages} pages · ${data.project.standard}` : ""}
        </span>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 2, marginLeft: "auto" }}>
        {STEPPER.map((s, i) => {
          const active = s.id === activeId;
          const done = curIdx !== -1 && i < curIdx;
          return (
            <div
              key={s.id}
              onClick={() => nav(s.path)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 7,
                padding: "5px 10px",
                borderRadius: 7,
                cursor: "pointer",
                background: active ? color.stepperActive : "transparent",
              }}
            >
              <span
                style={{
                  width: 18,
                  height: 18,
                  borderRadius: "50%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 10,
                  fontWeight: 600,
                  background: active ? color.indigo : done ? color.greenFg : color.divider,
                  color: active || done ? "#fff" : color.muted,
                }}
              >
                {done ? "✓" : s.step}
              </span>
              <span
                style={{
                  fontSize: 11.5,
                  fontWeight: active ? 600 : 500,
                  color: active ? "#fff" : done ? "#aeb6c1" : color.muted,
                }}
              >
                {t(`step.${s.id}`)}
              </span>
            </div>
          );
        })}
      </div>

      <div style={{ width: 1, height: 22, background: color.divider }} />
      <LanguageSwitcher />
      <div style={{ width: 1, height: 22, background: color.divider }} />
      <UserMenu />
    </div>
  );
}
