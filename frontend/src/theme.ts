/**
 * Design tokens — the single source of truth for the UI, transcribed exactly from
 * the design handoff. Components style with these constants (inline styles, mirroring
 * the wireframe) so every screen stays visually consistent. Do NOT introduce colors
 * outside this file.
 */
export const color = {
  // Page / surfaces
  pageBg: "#f5f6f8",
  surface: "#ffffff",
  cardBorder: "#e2e5ea",
  hairline: "#f2f3f5",
  hairline2: "#f0f1f4",
  hairline3: "#eef0f3",
  rowAltBg: "#fafbfc",

  // Ink
  ink: "#1e2530",
  ink2: "#374151",
  sec: "#4b5563",
  sec2: "#6b7280",
  muted: "#8a93a0",
  muted2: "#98a1ae",
  faint: "#9aa3b0",

  // Indigo (primary/accent)
  indigo: "#2743c4",
  indigoHover: "#1a2f9c",
  indigoTint: "#f4f6fe",
  indigoTint2: "#eef1fb",
  indigoTint3: "#eaf0ff",
  indigoBorder: "#dfe6fb",
  indigoBorder2: "#c3ccf4",

  // Dark chrome
  topbar: "#161c26",
  topbarBorder: "#0c1119",
  stepperActive: "#242b37",
  divider: "#2c333f",
  stepFuture: "#8a93a0",
  viewerBg: "#5b6472",
  viewerHeader: "#4a525f",

  // Semantic / confidence
  greenFg: "#1a7f5a",
  greenBg: "#e6f4ee",
  greenBg2: "#eaf4ef",
  amberFg: "#b7791f",
  amberBg: "#fdf3e0",
  redFg: "#c0392b",
  redBg: "#fdecea",
  excelGreen: "#217346",

  // Controls
  controlBorder: "#d4dae2",
  dashed: "#c2cad6",
  segBg: "#eef0f3",
  toggleOff: "#cfd4dc",
  trackBg: "#e7eaef",
} as const;

export const font = {
  sans: "'IBM Plex Sans', system-ui, sans-serif",
  mono: "'IBM Plex Mono', monospace",
} as const;

export const radius = {
  card: 12,
  cardSm: 11,
  control: 8,
  controlSm: 7,
  pill: 20,
  chip: 5,
  toggle: 10,
} as const;

export const shadow = {
  paper: "0 6px 22px rgba(0,0,0,.28)",
  focusRing: "0 0 0 3px rgba(39,67,196,.12)",
  segActive: "0 1px 2px rgba(0,0,0,.1)",
} as const;

export const layout = {
  topbarH: 52,
  navRail: 214,
  sourceViewer: "43%",
  notesList: 290,
  templateTree: 360,
  screenMax: 1120,
  screenMaxWide: 1180,
  // Workspace output grid columns: LINE ITEM / NOTE / FY25 / NOTE / FY24 / CONF.
  gridCols: "minmax(120px,1fr) 52px 90px 52px 90px 54px",
} as const;

/** Confidence category → badge colors + representative percentage. */
export type ConfCat = "high" | "med" | "low";
export function confStyle(cat: ConfCat): { bg: string; fg: string; pct: string } {
  if (cat === "high") return { bg: color.greenBg, fg: color.greenFg, pct: "96%" };
  if (cat === "med") return { bg: color.amberBg, fg: color.amberFg, pct: "78%" };
  return { bg: color.redBg, fg: color.redFg, pct: "54%" };
}

/** Indian-grouping number formatter (e.g. 12,68,100). */
export const fmtIN = (n: number | null | undefined): string =>
  n == null ? "" : n.toLocaleString("en-IN");
