/** Signed-in user chip + sign-out — replaces the old client-side role switcher.
 * The role now comes from the authenticated session (/me), not a dropdown. */
import { useT } from "../../i18n";
import { useLogout, useMe } from "../../lib/queries";
import { color, font } from "../../theme";

export function UserMenu() {
  const { data: me } = useMe();
  const logout = useLogout();
  const t = useT();

  if (!me) return null;
  const initials = me.name.split(" ").map((s) => s[0]).join("").slice(0, 2).toUpperCase();

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
      <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.2, alignItems: "flex-end" }}>
        <span style={{ fontSize: 11.5, fontWeight: 600, color: "#e7ebf1" }}>{me.name}</span>
        <span style={{ fontSize: 10, color: "#aeb6c1" }}>{t(`role.${me.role}`)}</span>
      </div>
      <div
        title={`${t("um.signedIn")} · ${me.name}`}
        style={{
          width: 30,
          height: 30,
          flex: "0 0 30px",
          borderRadius: "50%",
          background: color.indigo,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontWeight: 600,
          fontSize: 11.5,
          color: "#fff",
          fontFamily: font.sans,
        }}
      >
        {initials}
      </div>
      <button
        onClick={() => logout.mutate()}
        title={t("um.logout")}
        style={{
          fontSize: 11,
          fontWeight: 600,
          color: "#dfe3e9",
          background: color.stepperActive,
          border: `1px solid ${color.divider}`,
          borderRadius: 7,
          padding: "5px 10px",
          cursor: "pointer",
        }}
      >
        {t("um.logout")}
      </button>
    </div>
  );
}
