/** Screen/route registry — the single source used by both the nav rail and the top
 * pipeline stepper, so they always navigate to the same 8 destinations. */
export interface ScreenDef {
  id: string;
  path: string;
  label: string;
  icon: string; // unicode glyph, per the handoff
  step?: number; // position in the pipeline stepper (1..6), if part of it
  badge?: { count: number; tone: "review" | "warn" };
}

export const SCREENS: Record<string, ScreenDef> = {
  upload: { id: "upload", path: "/upload", label: "Documents & Template", icon: "▤", step: 1 },
  integrity: { id: "integrity", path: "/integrity", label: "Document Integrity", icon: "◎", step: 2, badge: { count: 3, tone: "warn" } },
  scope: { id: "scope", path: "/scope", label: "Page Scope", icon: "▦", step: 3 },
  workspace: { id: "workspace", path: "/workspace", label: "Workspace", icon: "▤", step: 4 },
  notes: { id: "notes", path: "/notes", label: "All Notes", icon: "☰" },
  review: { id: "review", path: "/review", label: "Review Queue", icon: "✓", step: 5, badge: { count: 12, tone: "review" } },
  template: { id: "template", path: "/template", label: "Template & Ontology", icon: "◆" },
  export: { id: "export", path: "/export", label: "Export", icon: "⬎", step: 6 },
};

/** Pipeline stepper, in order. */
export const STEPPER: { id: string; label: string; step: number; path: string }[] = [
  { id: "upload", label: "Upload", step: 1, path: "/upload" },
  { id: "integrity", label: "Integrity", step: 2, path: "/integrity" },
  { id: "scope", label: "Scope", step: 3, path: "/scope" },
  { id: "workspace", label: "Extract", step: 4, path: "/workspace" },
  { id: "review", label: "Review", step: 5, path: "/review" },
  { id: "export", label: "Export", step: 6, path: "/export" },
];

/** Left-nav groups. */
export const NAV_GROUPS: { group: string; items: string[] }[] = [
  { group: "SETUP", items: ["upload"] },
  { group: "PRE-FLIGHT", items: ["integrity", "scope"] },
  { group: "EXTRACT", items: ["workspace", "notes"] },
  { group: "QUALITY", items: ["review"] },
  { group: "CONFIGURE", items: ["template"] },
  { group: "DELIVER", items: ["export"] },
];

/** Map a pathname to the active screen id. */
export function screenIdForPath(pathname: string): string {
  const found = Object.values(SCREENS).find((s) => pathname.startsWith(s.path));
  return found?.id ?? "workspace";
}
