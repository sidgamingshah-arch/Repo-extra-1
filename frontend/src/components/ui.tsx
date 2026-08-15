/** Shared UI primitives. Screens compose these; they encode the handoff's exact
 * chrome (pills, confidence badges, chips, segmented toggles, cards, buttons). */
import type { CSSProperties, MouseEvent, ReactNode } from "react";

import { useT } from "../i18n";
import { color, confStyle, font, radius, shadow, type ConfCat } from "../theme";

export function Card({ children, style, pad = 18 }: { children: ReactNode; style?: CSSProperties; pad?: number }) {
  return (
    <div
      style={{
        background: color.surface,
        border: `1px solid ${color.cardBorder}`,
        borderRadius: radius.card,
        padding: pad,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

export function ScreenHeader({ title, subtitle, right }: { title: string; subtitle?: string; right?: ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 18 }}>
      <div>
        <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 5 }}>{title}</h1>
        {subtitle && <p style={{ margin: 0, color: color.sec2 }}>{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

export function Pill({
  children,
  bg,
  fg,
  style,
}: {
  children: ReactNode;
  bg: string;
  fg: string;
  style?: CSSProperties;
}) {
  return (
    <span
      style={{
        fontSize: 10.5,
        fontWeight: 600,
        padding: "3px 9px",
        borderRadius: radius.pill,
        background: bg,
        color: fg,
        ...style,
      }}
    >
      {children}
    </span>
  );
}

/** The ONE rule for turning a served confidence into text, used by every screen that prints one.
 *
 *  Three cases, and they are different statements about the data:
 *
 *   1. a MEASURED percentage (`pct`, 0–100, exactly as the payload serves it) → print the number;
 *   2. no measurement but a BAND (`cat`) → print the band's NAME ("High"), never its
 *      representative percentage. The band is genuinely known and worth showing; a word cannot be
 *      misread as a measurement, and 96/78/54 per band was read as exactly that — a page the
 *      classifier scored 0.40 announced "54%", and every 'high' row announced "96%";
 *   3. neither → say nothing is scored, rather than let a default band ('med' is what the server
 *      buckets a MISSING score into) print "78%" over a line nothing ever scored.
 *
 *  `measured` lets the caller render 2 and 3 as the absences they are instead of as values. No
 *  arithmetic here on purpose — the percentage is derived where it is served, so the browser cannot
 *  produce a second, disagreeing figure. A non-finite or out-of-range value falls to case 2/3
 *  rather than being printed: "1200%" over a mapping is a broken contract, not a confidence. */
export function confReadout(
  { cat, pct }: { cat?: ConfCat | null; pct?: number | null },
  t: (key: string) => string,
): { text: string; measured: boolean; title: string } {
  if (typeof pct === "number" && Number.isFinite(pct) && pct >= 0 && pct <= 100) {
    return { text: `${pct}%`, measured: true, title: t("conf.measuredHelp") };
  }
  if (cat) return { text: t(`conf.cat.${cat}`), measured: false, title: t("conf.bandOnlyHelp") };
  return { text: t("conf.unscored"), measured: false, title: t("conf.unscoredHelp") };
}

/** Confidence badge: the band's colour, and the MEASURED percentage as its text.
 *
 *  It used to print `confStyle(cat).pct` — a literal per band — so the Workspace CONF column showed
 *  "54%" against a row whose served `confidence.pct` was 41, and "78%" against a row with no score
 *  at all. The measurement is passed in and printed; with no measurement the pill names the band
 *  instead, in muted chrome, so nothing on screen looks like a figure that was never measured.
 *  `label` still overrides the text for callers that print something other than a confidence. */
export function ConfidencePill(
  { cat, pct, label, testid }:
  { cat: ConfCat; pct?: number | null; label?: string; testid?: string },
) {
  const t = useT();
  const c = confStyle(cat);
  const r = confReadout({ cat, pct }, t);
  const bare = !label && !r.measured;
  return (
    <span
      data-testid={testid}
      data-measured={label ? undefined : String(r.measured)}
      title={label ? undefined : r.title}
      style={{
        display: "inline-block",
        minWidth: 38,
        textAlign: "center",
        fontSize: 10,
        fontWeight: 600,
        padding: "2px 6px",
        borderRadius: radius.pill,
        background: bare ? "transparent" : c.bg,
        color: bare ? color.muted : c.fg,
        border: bare ? `1px dashed ${color.dashed}` : undefined,
      }}
    >
      {label ?? r.text}
    </span>
  );
}

/** Small indigo note-reference chip. When given an onClick it renders as a hyperlink to
 * the note (underlined, keyboard-activatable). */
export function NoteChip({ children, onClick }: { children: ReactNode; onClick?: (e?: MouseEvent) => void }) {
  const link = !!onClick;
  return (
    <span
      onClick={onClick}
      role={link ? "link" : undefined}
      tabIndex={link ? 0 : undefined}
      title={link ? "Open note" : undefined}
      onKeyDown={link ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick?.(); } } : undefined}
      style={{
        fontSize: 10,
        fontWeight: 600,
        padding: "2px 6px",
        borderRadius: radius.chip,
        background: color.indigoTint2,
        color: color.indigo,
        cursor: link ? "pointer" : "default",
        textDecoration: link ? "underline" : "none",
        textUnderlineOffset: 2,
      }}
    >
      {children}
    </span>
  );
}

export function Button({
  children,
  onClick,
  variant = "primary",
  style,
  disabled = false,
  title,
  ariaLabel,
  testid,
  data,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "ghost";
  style?: CSSProperties;
  disabled?: boolean;
  title?: string;
  /** Overrides the accessible name. For a DESTRUCTIVE control repeated down a list, the visible
   *  label is the same on every copy ("Withdraw acceptance") — `title` cannot fix that, because a
   *  button with text content takes its name from the text and the tooltip is only a hint. The
   *  caller names the row the press acts on here, so "which one am I taking back" is answerable
   *  without sight of the surrounding row. */
  ariaLabel?: string;
  /** Rendered as `data-testid`. A test cannot read a localized label, and the review actions
   *  (accept / withdraw / flip sign) each need naming from outside the component. */
  testid?: string;
  /** Extra `data-*` attributes, keyed WITHOUT the prefix (`{withheld: "true"}` →
   *  `data-withheld="true"`). One control whose meaning varies by case should stay one control
   *  with one testid and state the case in an attribute; minting a second testid per case is how
   *  a test ends up asserting about a button that no longer exists. */
  data?: Record<string, string>;
}) {
  const base: CSSProperties = {
    fontSize: 13,
    fontWeight: 600,
    borderRadius: 9,
    padding: "10px 20px",
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.5 : 1,
  };
  const variants: Record<string, CSSProperties> = {
    primary: { color: "#fff", background: color.indigo, border: "none" },
    secondary: { color: color.ink2, background: "#fff", border: `1px solid ${color.controlBorder}` },
    ghost: { color: color.indigo, background: "#fff", border: `1px solid ${color.indigoBorder2}` },
  };
  return (
    <button onClick={disabled ? undefined : onClick} disabled={disabled} title={title}
            aria-label={ariaLabel} data-testid={testid}
            {...Object.fromEntries(
              Object.entries(data ?? {}).map(([k, v]) => [`data-${k}`, v]))}
            style={{ ...base, ...variants[variant], ...style }}>
      {children}
    </button>
  );
}

/** Segmented control (e.g. Consolidated / Standalone). */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div style={{ display: "flex", background: color.segBg, borderRadius: 8, padding: 2 }}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <span
            key={o.value}
            onClick={() => onChange(o.value)}
            // Which option is active is styling, which a test cannot read. `data-on` states it.
            data-testid={`seg-${o.value}`}
            data-on={on ? "true" : "false"}
            style={{
              fontSize: 12,
              fontWeight: 600,
              padding: "6px 14px",
              borderRadius: 6,
              cursor: "pointer",
              background: on ? "#fff" : "transparent",
              color: on ? color.ink : color.sec2,
              boxShadow: on ? shadow.segActive : "none",
            }}
          >
            {o.label}
          </span>
        );
      })}
    </div>
  );
}

/** A small labeled control shell used by the workspace toolbar / export presentation. */
export function FieldChip({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        fontSize: 12,
        color: color.sec,
        border: `1px solid ${color.cardBorder}`,
        borderRadius: 8,
        padding: "6px 11px",
        cursor: "pointer",
      }}
    >
      <span style={{ color: color.muted }}>{label}</span>
      <span style={{ fontWeight: 600 }}>{value}</span>
      <span style={{ color: color.faint }}>▾</span>
    </div>
  );
}

/** iOS-style toggle switch. */
export function Toggle({ on }: { on: boolean }) {
  return (
    <span
      style={{
        width: 30,
        height: 17,
        borderRadius: 10,
        background: on ? color.indigo : color.toggleOff,
        position: "relative",
        cursor: "pointer",
        display: "inline-block",
        flex: "0 0 auto",
      }}
    >
      <span
        style={{
          position: "absolute",
          top: 2,
          [on ? "right" : "left"]: 2,
          width: 13,
          height: 13,
          borderRadius: "50%",
          background: "#fff",
        }}
      />
    </span>
  );
}

/** Leaf-row status glyph: ! low-confidence, ⇄ note-netted, ƒ edited. */
export function StatusIcon({ status }: { status?: string | null }) {
  if (!status) return null;
  const map: Record<string, [string, string]> = {
    flag: ["!", color.redFg],
    recon: ["⇄", color.amberFg],
    edited: ["ƒ", color.indigo],
    missing: ["—", color.faint],   // template line not found in this extraction
  };
  const s = map[status];
  if (!s) return null;
  return <span style={{ fontSize: 11, color: s[1] }}>{s[0]}</span>;
}

export const mono = font.mono;
export const tokens = { color, font, radius, shadow };
