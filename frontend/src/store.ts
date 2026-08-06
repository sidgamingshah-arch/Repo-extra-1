/** Ephemeral UI state (Zustand) — mirrors the wireframe's state model. Durable data
 * lives in React Query; this holds transient selection / toggles / edit-mode. */
import { create } from "zustand";

import type { Basis, ExportFmt, Locale, Role, StatementKey } from "./types";

const ROLE_KEY = "finex-role";
export function storedRole(): Role {
  if (typeof localStorage === "undefined") return "analyst";
  const r = localStorage.getItem(ROLE_KEY);
  return r === "admin" || r === "reviewer" || r === "analyst" ? r : "analyst";
}

interface UIState {
  locale: Locale;
  role: Role;
  dataset: Basis;
  statement: StatementKey;
  sel: string; // selected line-item id in the workspace
  editing: boolean; // inspector edit mode
  note: number; // selected note (All Notes)
  openCheck: string; // expanded review check
  tplSel: string; // selected template node
  exportFmt: ExportFmt;

  setLocale: (l: Locale) => void;
  setRole: (r: Role) => void;
  setDataset: (b: Basis) => void;
  setStatement: (s: StatementKey) => void;
  selRow: (id: string) => void;
  selForEdit: (id: string) => void;
  startEdit: () => void;
  cancelEdit: () => void;
  stopEditing: () => void;
  setNote: (n: number) => void;
  toggleCheck: (id: string) => void;
  setTpl: (id: string) => void;
  setFmt: (f: ExportFmt) => void;
}

export const useUI = create<UIState>((set) => ({
  locale: "en",
  role: storedRole(),
  dataset: "consolidated",
  statement: "balance_sheet",
  sel: "trade_recv",
  editing: false,
  note: 12,
  openCheck: "bs",
  tplSel: "trade_recv",
  exportFmt: "excel",

  setLocale: (locale) => {
    if (typeof document !== "undefined") {
      document.documentElement.dir = locale === "ar" ? "rtl" : "ltr";
      document.documentElement.lang = locale;
    }
    set({ locale });
  },
  setRole: (role) => {
    if (typeof localStorage !== "undefined") localStorage.setItem(ROLE_KEY, role);
    set({ role });
  },
  setDataset: (dataset) => set({ dataset }),
  setStatement: (statement) => set({ statement, sel: "" }),
  selRow: (sel) => set({ sel, editing: false }),
  selForEdit: (sel) => set({ sel, editing: true }),
  startEdit: () => set({ editing: true }),
  cancelEdit: () => set({ editing: false }),
  stopEditing: () => set({ editing: false }),
  setNote: (note) => set({ note }),
  toggleCheck: (id) => set((s) => ({ openCheck: s.openCheck === id ? "" : id })),
  setTpl: (tplSel) => set({ tplSel }),
  setFmt: (exportFmt) => set({ exportFmt }),
}));
