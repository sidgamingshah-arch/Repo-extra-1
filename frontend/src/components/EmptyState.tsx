/** Greenfield onboarding state shown on data screens when no project is loaded.
 * Points the user to the Upload screen; admins can also load the sample dataset. */
import { useNavigate } from "react-router-dom";

import { useT } from "../i18n";
import { useCan } from "../lib/rbac";
import { usePatchSettings } from "../lib/queries";
import { SCREENS } from "../screens/config";
import { color } from "../theme";

export function EmptyState() {
  const t = useT();
  const nav = useNavigate();
  const canConfig = useCan("config:settings");
  const patch = usePatchSettings();
  return (
    <div style={{ maxWidth: 560, margin: "72px auto", textAlign: "center", padding: "0 24px" }}>
      <div style={{ fontSize: 40, color: color.faint, marginBottom: 14 }}>▤</div>
      <h2 style={{ fontSize: 18, fontWeight: 600, margin: "0 0 8px" }}>{t("empty.title")}</h2>
      <p style={{ fontSize: 13, color: color.sec2, lineHeight: 1.6, margin: "0 auto 20px", maxWidth: 440 }}>
        {t("empty.body")}
      </p>
      <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
        <button
          onClick={() => nav(SCREENS.upload.path)}
          style={{
            fontSize: 13, fontWeight: 600, color: "#fff", background: color.indigo,
            border: "none", borderRadius: 9, padding: "10px 18px", cursor: "pointer",
          }}
        >
          {t("empty.goUpload")}
        </button>
        {canConfig && (
          <button
            onClick={() => patch.mutate({ seed_demo: true })}
            disabled={patch.isPending}
            style={{
              fontSize: 13, fontWeight: 600, color: color.ink2, background: "#fff",
              border: `1px solid ${color.controlBorder}`, borderRadius: 9, padding: "10px 18px",
              cursor: patch.isPending ? "default" : "pointer",
            }}
          >
            {patch.isPending ? t("empty.loading") : t("empty.loadSample")}
          </button>
        )}
      </div>
    </div>
  );
}
