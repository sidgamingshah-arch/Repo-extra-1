/** Role switcher — stands in for real authentication (sends X-Role on API calls).
 * Switching role re-filters the nav (admin sees config; analyst gets the simple flow)
 * and re-runs server-side permission checks. */
import { useT } from "../../i18n";
import { useUI } from "../../store";
import { color } from "../../theme";
import type { Role } from "../../types";

const ROLES: Role[] = ["admin", "reviewer", "analyst"];

export function RoleSwitcher() {
  const role = useUI((s) => s.role);
  const setRole = useUI((s) => s.setRole);
  const t = useT();

  return (
    <label title={t("role.label")} style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
      <span aria-hidden style={{ fontSize: 12, color: "#aeb6c1" }}>◔</span>
      <select
        value={role}
        onChange={(e) => setRole(e.target.value as Role)}
        style={{
          background: color.stepperActive,
          color: "#e7ebf1",
          border: `1px solid ${color.divider}`,
          borderRadius: 7,
          padding: "4px 8px",
          fontSize: 11.5,
          fontWeight: 600,
          fontFamily: "inherit",
          cursor: "pointer",
          outline: "none",
        }}
      >
        {ROLES.map((r) => (
          <option key={r} value={r} style={{ color: "#111" }}>
            {t(`role.${r}`)}
          </option>
        ))}
      </select>
    </label>
  );
}
