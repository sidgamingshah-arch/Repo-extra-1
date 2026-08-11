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
/** One tunable extraction setting, as DESCRIBED BY THE BACKEND — bounds, step and an
 *  explanation of what it does. The Settings screen renders and validates from this, so the
 *  UI cannot disagree with what the API will accept. */
export interface ExtractionField {
  key: string;
  kind: "number" | "bool" | "choice";
  label: string;
  help: string;
  min: number | null;
  max: number | null;
  step: number | null;
  choices: string[];
}

/** Runtime-mutable settings an admin can PATCH. */
export interface SettingsPatch {
  ui_localization?: boolean;
  review_required?: boolean;
  seed_demo?: boolean;
  llm?: LlmConfigPatch;
  /** Restore the LLM configuration to what config.toml shipped. */
  reset_llm?: boolean;
  /** Mapping / reconciliation thresholds. Out-of-range values are refused by the API (422). */
  extraction?: Record<string, number | boolean | string>;
  /** Restore every extraction knob to the value config.toml shipped. */
  reset_extraction?: boolean;
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
  /** Runtime-tunable pipeline thresholds, keyed by knob name. Rendered from
   *  `extraction_fields` rather than a hardcoded list, so a knob added on the backend appears
   *  here with no frontend change. */
  extraction: Record<string, number | boolean | string>;
  /** What config.toml shipped for each knob — for "restore defaults" and for showing which
   *  values have been moved away from them. */
  extraction_defaults: Record<string, number | boolean | string>;
  extraction_fields: ExtractionField[];
  auth: { allow_role_header: boolean; demo_mode: boolean; session_ttl_minutes: number };
}

/** One rate from the admin-maintained FX master: 1 `base` = `rate` `quote` on `as_of`.
 *  `rate` stays a STRING end to end — the backend holds it as an exact decimal, and
 *  parsing it into a JS number here would be the one place drift could creep in. */
export interface FxRate {
  id: string;
  base: string;
  quote: string;
  rate: string;
  as_of: string;
  source: string;
  created_at: string | null;
  updated_at: string | null;
}
/** A rate submitted by the admin editor. `as_of` omitted means "as of today" (server-side). */
export interface FxRateInput {
  base: string;
  quote: string;
  rate: string;
  as_of?: string;
  source?: string;
}
/** The answer to "what is base→quote?". `resolved` false is a normal answer — the master
 *  holds no rate for the pair — and the caller must then refuse to convert. */
export type FxRateResolution =
  | {
      resolved: true;
      base: string;
      quote: string;
      rate: string;
      as_of: string;
      /** True when the rate is OUR arithmetic (a reciprocal), not a quote as entered. */
      derived: boolean;
      method: "direct" | "inverse";
      /** The currencies actually traversed, in the direction the master stores them. */
      path: string[];
      source: string;
      rate_id: string;
    }
  | {
      resolved: false;
      base: string;
      quote: string;
      reason: "no_rate_configured";
      detail: string;
    };
/** The views the Workspace can show. The first four are statements the document prints; the
 *  last two are determined by its figures — the KPIs computed off the statements, and everything
 *  extracted that reaches no face statement. Both are real-extraction only. */
export type StatementKey = "balance_sheet" | "profit_and_loss" | "cash_flow"
  | "changes_in_equity" | "kpi" | "additional_items";
/** Views that exist only for a real extraction (there is no demo data behind them). */
export const DERIVED_STATEMENTS: StatementKey[] = ["kpi", "additional_items"];
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

/** One printed line that went into a combined figure.
 *
 * Several printed lines legitimately share one concept — three depreciation lines, two tax
 * payments, whatever a section's residual "Others" bucket absorbs. The combined figure then
 * matches no single line on the page, so each contributor carries its own values and its own
 * source location and can be traced back to where it was printed. */
export interface RowContribution {
  label: string;
  canonical_key?: string | null;
  v1: number | null;
  v2: number | null;
  method?: string | null;
  /** Routed here because nothing more specific matched, rather than positively identified. */
  residual?: boolean;
  src: string;
  source?: ExtractionProvenance | null;
  /** …and the same for the prior period, printed in its own column on its own page. */
  src2?: string;
  source2?: ExtractionProvenance | null;
}

export interface StatementRow {
  id: string;
  label: string;
  source_label?: string; // original-language label for the source "paper"
  kind: RowKind;
  level?: number;
  note?: string | null;
  note2?: string | null;
  status?: "flag" | "recon" | "edited" | "missing" | null;
  confidence?: Confidence;
  editable?: boolean;
  formula?: string | null;
  inspector?: Inspector;
  /** Present only when more than one printed line was combined into this figure. */
  contributions?: RowContribution[] | null;
  v1: number | null;
  v2: number | null;
  /** Matrix layouts only: the row's figures keyed by column name (see StatementResponse.layout).
   *  v1/v2 stay null there, because a component is not a period. */
  cells?: Record<string, number | null> | null;
  source?: ExtractionProvenance | null;   // real docs: current-period value's source location
  source2?: ExtractionProvenance | null;  // …and the prior period's, which is a figure too
  /** Pre-formatted figures in the row's OWN unit (a KPI's ×, %, days). When present the grid
   *  renders these verbatim and applies no currency/magnitude presentation — scaling a current
   *  ratio into "thousands" would be nonsense. */
  display1?: string | null;
  display2?: string | null;
}

/** A named column of a matrix statement — an equity component, not a period. */
export interface StatementColumn {
  key: string;
  label: string;
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
  /** Shape of the statement. "matrix" means the columns are NAMED (equity components, not
   *  periods) and every row carries `cells` instead of v1/v2. Absent means the two-column
   *  comparative default. */
  layout?: "comparative" | "matrix";
  /** Matrix layouts only: the named columns, in the order they are printed. */
  columns?: StatementColumn[];
  periods: string[];
  currency: string;
  currency_symbol: string;
  units: string;
  units_scale_factor?: number;  // detected source magnitude (e.g. 1000 for "in thousands"); default 1
  /** "raw" means the rows carry their own formatted figures (display1/display2) and must not be
   *  re-scaled or re-currencied. Absent means ordinary monetary presentation. */
  presentation?: "raw" | "monetary";
  rows: StatementRow[];
  viewer: ViewerMeta;
  format?: string;       // real docs: "pdf" | "xlsx" | … → chooses the live source viewer
  page_count?: number;   // real docs: page count for the PDF viewer
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
export interface ValueConfidence {
  mapping: number;
  validation: number | null;
  overall: number;
  weakest: number;
  flags: string[];
}
export interface ExtractionValue {
  period_label: string;
  value: string | null;
  provenance: ExtractionProvenance | null;
  confidence?: ValueConfidence;
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
export interface SourceUnits {
  currency: string;
  scale_factor: number;
  units_label: string | null;
}
export interface ExtractionResult {
  locale: string;
  format: string;
  filename: string;
  entity?: string | null;
  page_count?: number;
  line_item_count: number;
  notes: number;
  rows: ExtractionRow[];
  units?: SourceUnits | null;
  /** How ontology mapping actually ran. "deterministic" means the LLM was unavailable and the
   *  weaker rule/alias ensemble decided — surfaced so a degraded run is visible, not implied. */
  mapping?: { strategy: string; reason: string; llm_calls: number; model: string } | null;
}
export interface ExtractionRunResponse {
  run_id: string;
  status: string;
  result: ExtractionResult;
}
/** Derived analysis from a real extraction: ratios, disclosure scan, free-form notes. */
export interface Ratio {
  key: string;
  label: string;
  category: string;
  unit: string;
  formula: string;
  value: number | null;
  display: string;
  available: boolean;
}
export interface Disclosure {
  key: string;
  label: string;
  present: boolean;
  page: number | null;
  snippet: string;
}
export interface FreeNote {
  title: string;
  text: string;
}
export type CreditTone = "strong" | "adequate" | "weak";
export type CreditStance = CreditTone | "insufficient";
export interface CreditFactor {
  category: string;
  category_key: string;
  key: string;
  label: string;
  value: number | null;
  display: string;
  unit: string;
  tone: CreditTone;
  tone_label: string;
}
export interface CreditFlag {
  key: string;
  label: string;
  severity: "severe" | "high" | "watch";
  implication: string;
  page: number | null;
  snippet: string;
}
export interface CreditNarrative {
  text: string;
  provider: string;
  model: string;
}
export interface CreditAnalysis {
  stance: CreditStance;
  stance_label: string;
  factors: CreditFactor[];
  flags: CreditFlag[];
  summary: string;
  basis: string;
  narrative?: CreditNarrative;  // cached LLM narrative, when present
}
export interface AnalysisResponse {
  ratios: Ratio[];
  disclosures: Disclosure[];
  notes: FreeNote[];
  credit?: CreditAnalysis;
}

/** A window of spreadsheet cells around a value's origin (Excel click-to-source). */
export interface CellContextCell {
  ref: string;
  value: string;
  is_target: boolean;
  numeric: boolean;
}
export interface CellContext {
  sheet: string;
  target: string;
  col_letters: string[];
  row_numbers: number[];
  grid: CellContextCell[][];
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
  kind?: "face" | "notes" | "other";
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
  /** The concept this node maps to — the key an ontology edit targets. */
  canonical_key?: string;
  /** Merged display set (this locale + English fallback, capped) — read-only. */
  aliases: string[];
  /** RAW aliases stored for the requested locale — what the editor loads and saves back,
   *  so saving one language's aliases can't absorb another's fallbacks. */
  aliases_locale?: string[];
  sign: string;
  value_type: string;
  aggregation: string;
  netting: { expr: string; explain: string };
  /** The criteria the mapper reasons over. Aliases only fire when the printed wording is
   *  close to one; these decide the concept by MEANING, so they are editable too. Optional
   *  because the demo project's template view predates them. */
  definition?: string;
  include?: string[];
  exclude?: string[];
  /** Other canonical_keys this concept is easily confused with (server rejects unknown keys). */
  confusable_with?: string[];
  value_scope?: ValueScope;
  /** Lexical hints for the deterministic tier (keyword / regex / phrases that rule a match out). */
  keyword_hints?: string[];
  regex_hints?: string[];
  exclude_hints?: string[];
}
/** How a concept's value relates to its neighbours — mirrors the backend `ValueScope`. */
export type ValueScope =
  | "exclusive_leaf"
  | "exclusive_child"
  | "exclusive_residual"
  | "not_applicable";
export interface NettingRuleView {
  id: string;
  target_key: string;
  target_label: string;
  subtract: { key: string; label: string }[];
  add: { key: string; label: string }[];
  condition: string;
  label: string;
}
export interface TemplateResponse {
  tree: TemplateNode[];
  node_config: Record<string, NodeConfig>;
  template: { key: string; name: string; line_items: number };
  netting_rules?: NettingRuleView[];
  /** The ontology version whose rules this view shows — the target of inline edits.
   *  Null when no ontology targets this template (nothing to edit). */
  ontology?: { id: string; ontology_key: string; version: number; locale: string } | null;
}

/** An inline edit to ONE concept's mapping rules; only the fields present are changed.
 *  `aliases` is locale-scoped, so editing one language never clobbers another's list. */
export interface MappingEdit {
  canonical_key: string;
  locale?: string;
  aliases?: string[];
  sign_convention?: string;
  label?: string;
  description?: string;
  definition?: string;
  include?: string[];
  exclude?: string[];
  confusable_with?: string[];
  value_scope?: ValueScope;
  keyword_hints?: string[];
  regex_hints?: string[];
  exclude_hints?: string[];
}
/** Upsert or remove ONE netting rule, identified by its id. */
export interface NettingRuleEdit {
  id: string;
  delete?: boolean;
  target_key?: string;
  subtract_keys?: string[];
  add_keys?: string[];
  condition?: string;
  label?: string;
}
/** Every ontology edit publishes a new version — this is the version it published. */
export interface OntologyEditResult {
  id: string;
  ontology_key: string;
  version: number;
}

export interface ExportOption {
  key: string;
  label: string;
  on: boolean;
}
