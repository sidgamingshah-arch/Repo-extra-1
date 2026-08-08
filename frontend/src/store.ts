/** Ephemeral UI state (Zustand) — mirrors the wireframe's state model. Durable data
 * lives in React Query; this holds transient selection / toggles / edit-mode, plus the
 * session token and the two locale concerns:
 *
 *  - `locale`        — the OUTPUT language for extracted financial data (statements,
 *                      line items, notes). Always applied.
 *  - `uiLocalization`— admin flag (synced from GET /settings): when true the whole
 *                      interface is localized too; when false the UI stays English and
 *                      only financial output follows `locale`.
 *
 * `appLocale` (see useAppLocale) is the effective locale for interface chrome. */
import { create } from "zustand";

import { getToken, setStoredToken } from "./lib/api";
import type { Basis, ExportFmt, ExtractMode, Locale, StatementKey } from "./types";

interface UIState {
  locale: Locale; // output/data language
  uiLocalization: boolean; // admin flag: localize whole UI (from /settings)
  token: string | null; // session token

  extractMode: ExtractMode; // chosen at upload: auto-extract vs confirm page scope
  dataset: Basis;
  statement: StatementKey;
  sel: string; // selected line-item id in the workspace
  editing: boolean; // inspector edit mode
  note: number; // selected note (All Notes)
  openCheck: string; // expanded review check
  tplSel: string; // selected template node
  selectedTemplateKey: string | null; // active output template for the next run (null = default)
  exportFmt: ExportFmt;

  setLocale: (l: Locale) => void;
  setUiLocalization: (v: boolean) => void;
  setToken: (t: string | null) => void;
  setExtractMode: (m: ExtractMode) => void;
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
  setSelectedTemplateKey: (k: string | null) => void;
  setFmt: (f: ExportFmt) => void;
}

export const useUI = create<UIState>((set) => ({
  locale: "en",
  uiLocalization: false,
  token: getToken(),
  extractMode: "auto",
  dataset: "consolidated",
  statement: "balance_sheet",
  sel: "trade_recv",
  editing: false,
  note: 12,
  openCheck: "bs",
  tplSel: "trade_recv",
  selectedTemplateKey: null,
  exportFmt: "excel",

  setLocale: (locale) => set({ locale }),
  setUiLocalization: (uiLocalization) => set({ uiLocalization }),
  setToken: (token) => {
    setStoredToken(token);
    set({ token });
  },
  setExtractMode: (extractMode) => set({ extractMode }),
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
  setSelectedTemplateKey: (selectedTemplateKey) => set({ selectedTemplateKey }),
  setFmt: (exportFmt) => set({ exportFmt }),
}));

/** Effective locale for interface chrome: the chosen language only when an admin has
 * enabled whole-interface localization; otherwise English (financial output still
 * localizes via `locale`). */
export function useAppLocale(): Locale {
  return useUI((s) => (s.uiLocalization ? s.locale : "en"));
}
