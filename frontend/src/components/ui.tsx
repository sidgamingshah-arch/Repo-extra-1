/** Shared UI primitives. Screens compose these; they encode the handoff's exact
 * chrome (pills, confidence badges, chips, segmented toggles, cards, buttons). */
import type { CSSProperties, MouseEvent, ReactNode } from "react";

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

export function ConfidencePill({ cat, label }: { cat: ConfCat; label?: string }) {
  const c = confStyle(cat);
  return (
    <span
      style={{
        display: "inline-block",
        minWidth: 38,
        textAlign: "center",
        fontSize: 10,
        fontWeight: 600,
        padding: "2px 6px",
        borderRadius: radius.pill,
        background: c.bg,
        color: c.fg,
      }}
    >
      {label ?? c.pct}
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
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "ghost";
  style?: CSSProperties;
}) {
  const base: CSSProperties = {
    fontSize: 13,
    fontWeight: 600,
    borderRadius: 9,
    padding: "10px 20px",
    cursor: "pointer",
  };
  const variants: Record<string, CSSProperties> = {
    primary: { color: "#fff", background: color.indigo, border: "none" },
    secondary: { color: color.ink2, background: "#fff", border: `1px solid ${color.controlBorder}` },
    ghost: { color: color.indigo, background: "#fff", border: `1px solid ${color.indigoBorder2}` },
  };
  return (
    <button onClick={onClick} style={{ ...base, ...variants[variant], ...style }}>
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
  };
  const s = map[status];
  if (!s) return null;
  return <span style={{ fontSize: 11, color: s[1] }}>{s[0]}</span>;
}

export const mono = font.mono;
export const tokens = { color, font, radius, shadow };
