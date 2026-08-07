/** Types mirroring the backend API responses (see backend/app/api/routes). */
import type { ConfCat } from "./theme";

export type Locale = "en" | "zh" | "ar" | "fr";
export type Role = "admin" | "reviewer" | "analyst";
export type Basis = "consolidated" | "standalone";
/** How the pipeline proceeds after the integrity check:
 *  - `auto`    — detect statement pages and extract in one pass (default).
 *  - `confirm` — pause on the Page Scope screen so the user reviews/adjusts
 *                the detected pages before extraction. */
export type ExtractMode = "auto" | "confirm";

export interface Me {
  authenticated: boolean;
  username: string;
  name: string;
  via: "session" | "role-header";
  role: Role;
  roles: Role[];
  permissions: string[];
  screens: string[];
}

export interface DemoUser {
  username: string;
  name: string;
  role: Role;
}
export interface LoginResponse {
  token: string;
  token_type: string;
  expires_in: number;
  user: { username: string; name: string; role: Role };
}

export interface CommentaryMetric {
  key: string;
  label: string;
  value: number;
  tone: "good" | "warn" | "bad";
}
export type TrendKind = "amount" | "ratio" | "percent";
export interface CommentaryTrend {
  key: string;
  label: string;
  kind: TrendKind;
  current: number;
  prior: number;
  delta: number;
  direction: "up" | "down" | "flat";
  favorable: boolean;
  tone: "good" | "warn" | "bad";
}
export interface Commentary {
  headline: string;
  assessment: string;
  metrics: CommentaryMetric[];
  trends: CommentaryTrend[];
  strengths: string[];
  weaknesses: string[];
  data_quality: string;
  basis: string;
}

/** One row of the audit log — a past LLM/extraction run and its token usage. */
export interface AuditEntry {
  run_id: string;
  entity: string;
  action: "analysis" | "extraction" | "submit_review" | string;
  provider: string;
  model: string;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  status: "succeeded" | "failed";
  created_at: string;
}
export interface AuditResponse {
  entries: AuditEntry[];
}

/** Editable (non-secret) LLM configuration fields — the API key is never sent. */
export interface LlmConfigPatch {
  provider?: string;
  model?: string;
  base_url?: string;
  temperature?: number;
  max_tokens?: number;
  timeout_seconds?: number;
  api_key_env?: string;
}
/** Runtime-mutable settings an admin can PATCH. */
export interface SettingsPatch {
  ui_localization?: boolean;
  review_required?: boolean;
  seed_demo?: boolean;
  llm?: LlmConfigPatch;
}

export interface AppSettings {
  features: {
    ui_localization: boolean;
    review_required: boolean;
    seed_demo: boolean;
    default_output_locale: string;
    supported_locales: string[];
  };
  llm: {
    provider: string;
    model: string;
    temperature: number;
    max_tokens: number;
    timeout_seconds: number;
    base_url: string;
    api_key_env: string;
    key_configured: boolean;
  };
  ocr: { engine: string; languages: string[]; dpi: number };
  embeddings: { provider: string; model: string };
  extraction: {
    fuzzy_accept: number;
    fuzzy_candidate: number;
    embedding_accept: number;
    mapping_margin: number;
    auto_accept_confidence: number;
    recon_abs_tolerance: number;
    recon_rel_tolerance: number;
  };
  auth: { allow_role_header: boolean; demo_mode: boolean; session_ttl_minutes: number };
}
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
  source_label?: string; // original-language label for the source "paper"
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
  id?: string;
  name: string;
  ext: string;
  meta: string;
  tag: "Mixed" | "Native" | "Scanned";
}
export interface ProjectResponse {
  project: Project;
  documents: SourceDoc[];
  loaded: boolean;
}

/** Provenance of an extracted value — sheet+cell (Excel) or page+bbox (PDF). */
export interface ExtractionProvenance {
  source_kind: string;
  page_index: number;
  sheet: string | null;
  cell: string | null;
  label_cell: string | null;
  bbox: { x0: number; y0: number; x1: number; y1: number } | null;
  text_snippet: string | null;
}
export interface ExtractionValue {
  period_label: string;
  value: string | null;
  provenance: ExtractionProvenance | null;
}
export interface ExtractionRow {
  source_label: string;
  canonical_key: string | null;
  note: string | null;
  role: string;
  mapping_method: string | null;
  mapping_confidence: number | null;
  flags: string[];
  values: ExtractionValue[];
}
export interface ExtractionResult {
  locale: string;
  format: string;
  filename: string;
  line_item_count: number;
  notes: number;
  rows: ExtractionRow[];
}
export interface ExtractionRunResponse {
  run_id: string;
  status: string;
  result: ExtractionResult;
}
export interface OntologyRef {
  id: string;
  ontology_key: string;
  target_template_key: string;
  version: number;
}
export interface TemplateRef {
  id: string;
  template_key: string;
  name: string;
  version: number;
  is_published: boolean;
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
