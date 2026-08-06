/** Ephemeral UI state (Zustand) — mirrors the wireframe's state model. Durable data
 * lives in React Query; this holds transient selection / toggles / edit-mode. */
import { create } from "zustand";

import type { Basis, ExportFmt, Locale, StatementKey } from "./types";

interface UIState {
  locale: Locale;
  dataset: Basis;
  statement: StatementKey;
  sel: string; // selected line-item id in the workspace
  editing: boolean; // inspector edit mode
  note: number; // selected note (All Notes)
  openCheck: string; // expanded review check
  tplSel: string; // selected template node
  exportFmt: ExportFmt;

  setLocale: (l: Locale) => void;
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
