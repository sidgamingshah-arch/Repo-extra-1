/** Fixed top bar: logo + wordmark + active document title + pipeline stepper + avatar.
 * The stepper marks steps before the current pipeline position as done (green check). */
import { useLocation, useNavigate } from "react-router-dom";

import { useDocuments, useMe, useProject } from "../../lib/queries";
import { useUI } from "../../store";
import { color } from "../../theme";
import { useT } from "../../i18n";
import { STEPPER, screenIdForPath } from "../../screens/config";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { UserMenu } from "./UserMenu";

export function TopBar() {
  const nav = useNavigate();
  const loc = useLocation();
  const { data: me } = useMe();
  const t = useT();
  const extractMode = useUI((s) => s.extractMode);
  // When a real uploaded document is being worked, the title bar reflects THAT file — not
  // the demo project — so demo chrome never bleeds into a real run.
  const activeDocumentId = useUI((s) => s.activeDocumentId);
  const usingReal = !!activeDocumentId;
  // Not requested while a real document is active: the sample project is not what this bar is
  // naming then, so there is nothing in its answer to print. (Same wrong-source rule as the nav
  // rail's progress card.)
  const { data } = useProject(!usingReal);
  const { data: docsData } = useDocuments();
  const activeDoc = docsData?.documents?.find((d) => d.id === activeDocumentId);
  // Which document is active is settled by `activeDocumentId`, NOT by whether its row has arrived
  // from /documents yet. Branching on `activeDoc` meant that for as long as that request was in
  // flight — every cold load and every invalidation — the bar printed the SAMPLE project's title
  // and its "…· 33 pages · IFRS" subtitle as the identity of the real file being worked. A pending
  // request is not "no document": it is this document, not yet named.
  const title = usingReal
    ? activeDoc?.name ?? t("empty.loading")
    : data?.project.title ?? t("empty.loading");
  const subtitle = usingReal
    ? activeDoc?.meta ?? ""
    : data
    ? `${data.project.filename} · ${data.project.pages} ${t("tb.pages")} · ${data.project.standard}`
    : "";
  // In auto mode the pipeline skips the manual Page Scope confirmation, so the
  // stepper collapses to Upload → Integrity → Extract → Review → Export. Also limit the
  // stepper to steps the caller's role can actually reach (e.g. a reviewer has no upload).
  const steps = STEPPER
    .filter((s) => !(extractMode === "auto" && s.id === "scope"))
    .filter((s) => !me || me.screens.includes(s.id));
  const activeId = screenIdForPath(loc.pathname);
  const curIdx = steps.findIndex((s) => s.id === activeId);

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
          {title}
        </span>
        <span style={{ fontSize: 11, color: color.muted, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {subtitle}
        </span>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 2, marginLeft: "auto" }}>
        {steps.map((s, i) => {
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
                {done ? "✓" : i + 1}
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
