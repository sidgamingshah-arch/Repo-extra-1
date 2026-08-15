/** Left navigation rail: grouped screen links + the sample project's extraction-progress card. */
import { useLocation, useNavigate } from "react-router-dom";

import { useMe, useProject } from "../../lib/queries";
import { color } from "../../theme";
import { useT } from "../../i18n";
import { useUI } from "../../store";
import { NAV_GROUPS, SCREENS, screenIdForPath } from "../../screens/config";

export function NavRail() {
  const nav = useNavigate();
  const loc = useLocation();
  const t = useT();
  const { data: me } = useMe();
  const activeId = screenIdForPath(loc.pathname);
  // WHOSE progress the card can report. `useProject()` serves the SEEDED SAMPLE project and
  // nothing else, so with a real uploaded document active the card was printing the sample's
  // "33 line items · 4 in review" under a label naming the active extraction — on every screen,
  // including the Review screen showing that document's own 4-row figures. The same wrong-source
  // defect was fixed in Export.tsx (`usingReal ? … : sampleProgress`) and left here.
  //
  // The rail has no cheap honest source for a real document's line population: the only payloads
  // that carry one are the extraction run and the review queue, either of which is a heavy fetch
  // for a nav card that renders on all eleven screens. So the clause is OMITTED rather than
  // sourced from the wrong project or paid for with a request the rail cannot justify — and the
  // query is not issued at all while a real document is active, because there is then nothing in
  // its answer this component may print.
  const activeDocumentId = useUI((s) => s.activeDocumentId);
  const usingReal = !!activeDocumentId;
  const { data } = useProject(!usingReal);
  // `loaded` is the sample project's own "there is an extraction here" flag. Unloaded, the route
  // still serves a counted-from-nothing {0, 0}; "0 line items" under "Extraction progress" asserts
  // an extraction that has no lines, where the truth is that there is no extraction.
  const prog = !usingReal && data?.loaded ? data.project.progress : undefined;

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

      {/* Rendered only when there IS a figure to print, and only when the figure belongs to the
          extraction the label names. A card whose title says "Extraction progress" and whose body
          is empty reads as a load that failed; a card whose body is another project's counts is
          worse. So the whole card is absent while a real document is active, and absent before the
          sample project's counts have arrived. */}
      {prog && (
        <div
          data-testid="nav-progress"
          style={{
            margin: "14px 16px 0",
            padding: "11px 12px",
            border: `1px solid ${color.cardBorder}`,
            borderRadius: 9,
            background: color.rowAltBg,
          }}
        >
          {/* No percentage and no bar. Both rendered `progress.pct`, which was a literal 72 in the
              sample payload derived from nothing, and read `?? 0` — so once the server stopped
              serving a figure it could not compute, this card would have drawn an empty bar and
              announced "0%" over a project with 33 mapped line items. The two counts below are the
              server's own, over the data it serves, and they are all this card can honestly say.
              The labels are translated: they were hardcoded English inside a localized shell. */}
          <div style={{ fontSize: 11, color: color.sec2, marginBottom: 6 }}>{t("progress.title")}</div>
          <div style={{ fontSize: 10.5, color: color.muted2 }}>
            {`${prog.line_items} ${t("progress.lineItems")} · `
             + `${prog.in_review} ${t("progress.inReview")}`}
          </div>
        </div>
      )}
    </div>
  );
}
