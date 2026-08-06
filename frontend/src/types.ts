/** Types mirroring the backend API responses (see backend/app/api/routes). */
import type { ConfCat } from "./theme";

export type Basis = "consolidated" | "standalone";
export type StatementKey = "balance_sheet" | "profit_and_loss" | "cash_flow";
export type RowKind = "section" | "subhead" | "item" | "subtotal" | "total";
export type ExportFmt = "excel" | "json";

export interface Confidence {
  cat: ConfCat;
  pct: number;
}

export interface Inspector {
  tag: string;
  src: string;
  formula: string;
  result: string;
  note: string;
}

export interface StatementRow {
  id: string;
  label: string;
  kind: RowKind;
  level?: number;
  note?: string | null;
  note2?: string | null;
  status?: "flag" | "recon" | "edited" | null;
  confidence?: Confidence;
  editable?: boolean;
  formula?: string | null;
  inspector?: Inspector;
  v1: number | null;
  v2: number | null;
}

export interface ViewerMeta {
  company: string;
  subtitle: string;
  chips: { label: string; active: boolean }[];
  callout: string;
}

export interface StatementResponse {
  statement: StatementKey;
  label: string;
  basis: Basis;
  periods: [string, string];
  currency: string;
  currency_symbol: string;
  units: string;
  rows: StatementRow[];
  viewer: ViewerMeta;
}

export interface Project {
  id: string;
  entity: string;
  title: string;
  filename: string;
  pages: number;
  standard: string;
  currency: string;
  currency_symbol: string;
  units: string;
  periods: [string, string];
  bases: Basis[];
  progress: { pct: number; line_items: number; in_review: number };
  template: { key: string; name: string; line_items: number };
  ontology: { file: string; rules: number; aliases: number; status: string };
}

export interface SourceDoc {
  name: string;
  ext: string;
  meta: string;
  tag: "Mixed" | "Native" | "Scanned";
}

export interface IntegrityStat {
  label: string;
  value: string;
  sub: string;
  tone: "neutral" | "warn" | "ok";
}
export interface IntegrityIssue {
  title: string;
  detail: string;
  pages: string;
  note: string;
  status: string;
  severity: "warn" | "ok" | "low";
}
export interface IntegrityResponse {
  score: number;
  grade: string;
  summary: string;
  stats: IntegrityStat[];
  issues: IntegrityIssue[];
}

export interface PageCard {
  no: number;
  cls: string;
  sub: string;
  conf: ConfCat;
  included: boolean;
  scan: "native" | "scanned";
}
export interface PagesResponse {
  pages: PageCard[];
  filters: { label: string; count: number }[];
  focused: number;
  total: number;
  skipped: number;
}

export interface ReviewCalcRow {
  0: string;
  1: string;
  2: boolean;
}
export interface ReviewCheck {
  id: string;
  type: string;
  icon: string;
  title: string;
  where: string;
  severity: string;
  tone: "low" | "med" | "indigo";
  delta: string;
  target: string;
  calc: [string, string, boolean][];
  fix: string;
}
export interface ReviewResponse {
  checks: ReviewCheck[];
  tabs: { label: string; count: number }[];
  summary: { open: number; passed: number };
}

export interface NoteIndexItem {
  no: number;
  title: string;
  conf: ConfCat;
}
export interface NoteDetailRow {
  label: string;
  v1: number;
  v2: number;
  conf?: ConfCat;
  kind?: "sub" | "tot";
}
export interface NoteDetail {
  no: number;
  title: string;
  page: number;
  linked_line: string;
  linked_label: string;
  rows: NoteDetailRow[];
  reconciliation: string | null;
}
export interface NotesResponse {
  notes: NoteIndexItem[];
  count: number;
  linked: number;
}

export interface TemplateNode {
  id: string;
  label: string;
  lvl: number;
  head?: boolean;
  rule?: boolean;
}
export interface NodeConfig {
  breadcrumb: string;
  label: string;
  aliases: string[];
  sign: string;
  value_type: string;
  aggregation: string;
  netting: { expr: string; explain: string };
}
export interface TemplateResponse {
  tree: TemplateNode[];
  node_config: Record<string, NodeConfig>;
  template: { key: string; name: string; line_items: number };
}

export interface ExportOption {
  key: string;
  label: string;
  on: boolean;
}
