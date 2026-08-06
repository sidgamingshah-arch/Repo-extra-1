/** Language switcher — offers the locales the backend reports as FULLY supported
 * (input = output parity), driven by GET /languages. Selecting a locale sets the UI
 * language, localizes server-side output labels, and flips the layout to RTL for Arabic. */
import { NATIVE_NAME } from "../../i18n";
import { useLanguages } from "../../lib/queries";
import { useUI } from "../../store";
import { color } from "../../theme";
import type { Locale } from "../../types";

const FALLBACK: Locale[] = ["en", "zh", "ar", "fr"];

export function LanguageSwitcher() {
  const locale = useUI((s) => s.locale);
  const setLocale = useUI((s) => s.setLocale);
  const { data } = useLanguages();

  const supported = (data?.fully_supported?.length
    ? (data.fully_supported as Locale[])
    : FALLBACK
  ).filter((l) => l in NATIVE_NAME);

  return (
    <label
      title="Language"
      style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}
    >
      <span aria-hidden style={{ fontSize: 13, color: "#aeb6c1" }}>◐</span>
      <select
        value={locale}
        onChange={(e) => setLocale(e.target.value as Locale)}
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
        {supported.map((l) => (
          <option key={l} value={l} style={{ color: "#111" }}>
            {NATIVE_NAME[l]}
          </option>
        ))}
      </select>
    </label>
  );
}
