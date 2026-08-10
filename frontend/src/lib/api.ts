/** Thin fetch client. All calls go to /api/v1 (proxied to FastAPI in dev). */
const BASE = "/api/v1";
const PROJECT = "demo";
const TOKEN_KEY = "finex-token";

export function getToken(): string | null {
  if (typeof localStorage === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}
export function setStoredToken(token: string | null): void {
  if (typeof localStorage === "undefined") return;
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

// The document currently being worked through the stepper (integrity → extract → review →
// export). Persisted so a page refresh keeps the real run bound to the SAME file rather
// than silently falling back to some other document in the shared list.
const ACTIVE_DOC_KEY = "finex-active-doc";
export function getStoredActiveDoc(): string | null {
  if (typeof localStorage === "undefined") return null;
  return localStorage.getItem(ACTIVE_DOC_KEY);
}
export function setStoredActiveDoc(id: string | null): void {
  if (typeof localStorage === "undefined") return;
  if (id) localStorage.setItem(ACTIVE_DOC_KEY, id);
  else localStorage.removeItem(ACTIVE_DOC_KEY);
}

/** Error carrying the HTTP status so callers (e.g. auth gating) can special-case 401.
 *  `detail` is the server's own explanation when it sent one — editors show it verbatim
 *  rather than a generic failure, so a rejected value says WHY it was rejected. */
export class ApiError extends Error {
  status: number;
  detail?: string;
  constructor(status: number, message: string, detail?: string) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

/** Pull FastAPI's `detail` out of an error body; undefined when it isn't a plain message. */
function errorDetail(text: string): string | undefined {
  try {
    const body = JSON.parse(text) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : undefined;
  } catch {
    return undefined;
  }
}

function authHeader(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...authHeader(), ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, `${res.status} ${res.statusText} — ${text}`, errorDetail(text));
  }
  if (res.status === 204) return undefined as T; // no content (e.g. DELETE)
  return res.json() as Promise<T>;
}

import type {
  AnalysisResponse,
  AppSettings,
  AuditEntry,
  AuditResponse,
  Basis,
  CellContext,
  Commentary,
  DemoUser,
  ExtractionRunResponse,
  ExportFmt,
  FxRate,
  FxRateInput,
  FxRateResolution,
  IntegrityResponse,
  Locale,
  LoginResponse,
  MappingEdit,
  Me,
  NettingRuleEdit,
  NoteDetail,
  NotesResponse,
  OntologyEditResult,
  OntologyRef,
  PagesResponse,
  ProjectResponse,
  ReviewResponse,
  TemplateRef,
  SettingsPatch,
  SourceDoc,
  StatementKey,
  StatementResponse,
  TemplateResponse,
  ExportOption,
} from "../types";

export const api = {
  // --- auth / identity ---
  login: (username: string, password?: string) =>
    req<LoginResponse>(`/auth/login`, {
      method: "POST",
      body: JSON.stringify({ username, password: password ?? null }),
    }),
  logout: () => req<{ ok: boolean }>(`/auth/logout`, { method: "POST" }),
  demoUsers: () => req<{ users: DemoUser[]; demo_mode: boolean }>(`/auth/demo-users`),
  me: () => req<Me>(`/me`),
  // --- settings ---
  settings: () => req<AppSettings>(`/settings`),
  patchSettings: (body: SettingsPatch) =>
    req<AppSettings>(`/settings`, { method: "PATCH", body: JSON.stringify(body) }),
  // --- FX rate master (admin-maintained; drives presentation currency conversion) ---
  /** The whole master — readable by any authenticated user (the Workspace needs it). */
  fxRates: () => req<{ rates: FxRate[] }>(`/fx-rates`),
  /** Ask the master for one pair. Resolution happens server-side so the reciprocal of a
   *  stored rate is computed in exact decimal, and comes back labelled as derived. */
  resolveFxRate: (base: string, quote: string) =>
    req<FxRateResolution>(
      `/fx-rates/resolve?base=${encodeURIComponent(base)}&quote=${encodeURIComponent(quote)}`,
    ),
  /** Create or restate a rate for a pair + as-of date (admin). */
  upsertFxRate: (body: FxRateInput) =>
    req<FxRate>(`/fx-rates`, { method: "POST", body: JSON.stringify(body) }),
  updateFxRate: (id: string, body: FxRateInput) =>
    req<FxRate>(`/fx-rates/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteFxRate: (id: string) => req<void>(`/fx-rates/${id}`, { method: "DELETE" }),
  submitForReview: () =>
    req<{ ok: boolean; entry: AuditEntry }>(`/projects/${PROJECT}/submit-review`, { method: "POST" }),
  commentary: (locale: Locale = "en") =>
    req<Commentary>(`/projects/${PROJECT}/commentary?locale=${locale}`),
  audit: () => req<AuditResponse>(`/projects/${PROJECT}/audit`),
  runAnalysis: () =>
    req<{ entry: AuditEntry; result: unknown }>(`/projects/${PROJECT}/analysis`, { method: "POST" }),
  project: () => req<ProjectResponse>(`/projects/${PROJECT}`),
  documents: () => req<{ documents: SourceDoc[] }>(`/documents`),
  ontologies: () => req<OntologyRef[]>(`/ontologies`),
  templates: () => req<TemplateRef[]>(`/templates`),
  runExtraction: (
    documentId: string,
    body: { ontology_version_id?: string; template_version_id?: string } = {},
  ) =>
    req<{ run_id: string; status: string }>(`/documents/${documentId}/extractions`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  /** Poll a background extraction run's status/result. */
  getRun: (runId: string) => req<ExtractionRunResponse>(`/extractions/${runId}`),
  /** Real per-document pre-flight integrity (drives the Integrity screen for an upload). */
  documentIntegrity: (documentId: string, locale: Locale = "en") =>
    req<IntegrityResponse>(`/documents/${documentId}/integrity?locale=${locale}`),
  /** Real per-document review queue, derived from the latest extraction (unmapped + low
   * confidence). */
  documentReview: (documentId: string, locale: Locale = "en") =>
    req<ReviewResponse>(`/documents/${documentId}/review?locale=${locale}`),
  /** Derived analysis for a document: computed ratios, disclosure scan, free-form notes. */
  documentAnalysis: (documentId: string, locale: Locale = "en") =>
    req<AnalysisResponse>(`/documents/${documentId}/analysis?locale=${locale}`),
  /** Real per-document notes index + detail, from line-item note references. */
  documentNotes: (documentId: string) =>
    req<NotesResponse>(`/documents/${documentId}/notes`),
  documentNote: (documentId: string, no: number) =>
    req<NoteDetail>(`/documents/${documentId}/notes/${no}`),
  /** Edit a value/formula on a real extraction (persists onto the latest run). */
  editDocumentLineItem: (documentId: string, key: string, value: number | null, formula: string) =>
    req<{ status: string; value: string | null }>(
      `/documents/${documentId}/line-items/${encodeURIComponent(key)}`,
      { method: "PATCH", body: JSON.stringify({ value, formula }) },
    ),
  /** Revert an edited line item to its original machine-extracted values. */
  revertDocumentLineItem: (documentId: string, key: string) =>
    req<{ reverted: boolean }>(
      `/documents/${documentId}/line-items/${encodeURIComponent(key)}`,
      { method: "DELETE" },
    ),
  /** The latest extraction run for a document (drives the Export preview/counts). */
  documentRun: (documentId: string) =>
    req<ExtractionRunResponse>(`/documents/${documentId}/run`),
  /** Real per-page classification for the Page Scope screen (available pre-extraction). */
  documentPages: (documentId: string) =>
    req<PagesResponse>(`/documents/${documentId}/pages`),
  /** Persist the user's page selection for extraction (the Page Scope toggles). Extraction
   * then restricts itself to these pages; an empty list resets to the default (all face/notes). */
  setDocumentScope: (documentId: string, includedPages: number[]) =>
    req<{ ok: boolean; included_pages: number[]; count: number }>(
      `/documents/${documentId}/scope`,
      { method: "PUT", body: JSON.stringify({ included_pages: includedPages }) },
    ),
  /** Data-driven commentary computed from a document's real extraction (not the demo). */
  documentCommentary: (documentId: string, locale: Locale = "en") =>
    req<Commentary>(`/documents/${documentId}/commentary?locale=${locale}`),
  /** One statement of a document's real extraction, grouped for the Workspace grid. */
  documentStatement: (documentId: string, statement: StatementKey, basis: Basis, locale: Locale = "en") =>
    req<StatementResponse>(
      `/documents/${documentId}/statement?statement=${statement}&basis=${basis}&locale=${locale}`,
    ),
  /** A window of spreadsheet cells around a value's origin — the Excel click-to-source
   * backdrop (mirrors fetchPageImage for PDFs). */
  cellContext: (documentId: string, sheet: string, cell: string) =>
    req<CellContext>(
      `/documents/${documentId}/cell-context?sheet=${encodeURIComponent(sheet)}&cell=${encodeURIComponent(cell)}`,
    ),
  /** PNG of a PDF page (auth'd fetch → blob), used as the click-to-source backdrop. */
  fetchPageImage: async (documentId: string, pageIndex: number): Promise<Blob> => {
    const res = await fetch(`${BASE}/documents/${documentId}/pages/${pageIndex}/image`, {
      headers: { ...authHeader() },
    });
    if (!res.ok) throw new ApiError(res.status, `${res.status} ${res.statusText}`);
    return res.blob();
  },
  uploadDocument: async (file: File): Promise<{ id: string; page_count: number; integrity_report: unknown }> => {
    const fd = new FormData();
    fd.append("file", file);
    // No JSON Content-Type — let the browser set the multipart boundary.
    const res = await fetch(`${BASE}/documents`, { method: "POST", headers: { ...authHeader() }, body: fd });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new ApiError(res.status, `${res.status} ${res.statusText} — ${text}`);
    }
    return res.json();
  },
  deleteDocument: (id: string) =>
    req<void>(`/documents/${id}`, { method: "DELETE" }),
  /** Generate an LLM credit narrative that rationalises the deterministic credit view. */
  creditNarrative: (id: string, locale: Locale = "en") =>
    req<{ narrative: string; provider: string; model: string }>(
      `/documents/${id}/credit-narrative?locale=${locale}`, { method: "POST" }),
  integrity: (locale: Locale = "en") =>
    req<IntegrityResponse>(`/projects/${PROJECT}/integrity?locale=${locale}`),
  pages: (locale: Locale = "en") =>
    req<PagesResponse>(`/projects/${PROJECT}/pages?locale=${locale}`),
  statement: (statement: StatementKey, basis: Basis, locale: Locale = "en") =>
    req<StatementResponse>(`/projects/${PROJECT}/statements/${statement}?basis=${basis}&locale=${locale}`),
  editLineItem: (id: string, value: number | null, formula: string) =>
    req<{ id: string; value: number | null; formula: string }>(
      `/projects/${PROJECT}/line-items/${id}`,
      { method: "PATCH", body: JSON.stringify({ value, formula }) },
    ),
  revertLineItem: (id: string) =>
    req<{ id: string }>(`/projects/${PROJECT}/line-items/${id}`, { method: "DELETE" }),
  notes: (locale: Locale = "en") => req<NotesResponse>(`/projects/${PROJECT}/notes?locale=${locale}`),
  note: (no: number, locale: Locale = "en") =>
    req<NoteDetail>(`/projects/${PROJECT}/notes/${no}?locale=${locale}`),
  review: (locale: Locale = "en") => req<ReviewResponse>(`/projects/${PROJECT}/review?locale=${locale}`),
  template: (locale: Locale = "en") => req<TemplateResponse>(`/projects/${PROJECT}/template?locale=${locale}`),
  exportOptions: () => req<{ options: ExportOption[] }>(`/projects/${PROJECT}/export-options`),
  exportUrl: () => `${BASE}/projects/${PROJECT}/export`,
  /** A real configured template rendered into the tree + per-node config the Template &
   *  Ontology screen shows (aliases/sign/netting from the paired ontology). */
  templateDetail: (id: string, locale: Locale = "en") =>
    req<TemplateResponse>(`/templates/${id}/detail?locale=${locale}`),
  languages: () =>
    req<{ languages: { locale: string; name: string; rtl: boolean; supported: boolean }[]; fully_supported: string[] }>(
      `/languages`,
    ),
  /** Author a template from the frontend: POST a template definition (validated + versioned
   *  server-side). Returns the new version's id/key so it can be selected on Upload. */
  createTemplate: (definition: unknown) =>
    req<{ id: string; template_key: string; version: number }>(
      `/templates`, { method: "POST", body: JSON.stringify({ definition }) }),
  createOntology: (definition: unknown) =>
    req<{ id: string; ontology_key: string; version: number }>(
      `/ontologies`, { method: "POST", body: JSON.stringify({ definition }) }),
  /** Edit ONE concept's rules inline — aliases, sign, and the mapping criteria the model
   *  reasons over. The server validates the result and publishes a NEW ontology version (so a
   *  past extraction still explains itself against the version it actually used); the
   *  response carries that new version's id/number. */
  editOntologyMapping: (ontologyId: string, edit: MappingEdit) =>
    req<OntologyEditResult & { canonical_key: string }>(
      `/ontologies/${ontologyId}/mappings`,
      { method: "PATCH", body: JSON.stringify(edit) }),
  /** Upsert or delete ONE netting rule. Netting restates a reported figure, so it goes
   *  through the same versioned publish + validation as a concept edit. */
  editNettingRule: (ontologyId: string, edit: NettingRuleEdit) =>
    req<OntologyEditResult>(
      `/ontologies/${ontologyId}/netting-rules`,
      { method: "PATCH", body: JSON.stringify(edit) }),
  listTemplates: () =>
    req<{ id: string; template_key: string; name: string; version: number }[]>(`/templates`),
};

/** POST the export request and trigger a browser download of the returned file. */
export async function downloadExport(body: {
  format: ExportFmt;
  basis: Basis;
  currency: string;
  units: string;
  include: Record<string, boolean>;
}): Promise<void> {
  const res = await fetch(api.exportUrl(), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeader() },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Export failed: ${res.status}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = body.format === "excel" ? "spread.xlsx" : "extract.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** GET a REAL document's export (built from its latest extraction) and download it. Excel
 * uses the formatted, template-driven statement layout, localized to `locale`. */
export async function downloadDocumentExport(
  documentId: string, format: ExportFmt, locale: Locale = "en", include?: string[],
  units?: string,
): Promise<void> {
  const inc = include && format === "excel" ? `&include=${include.join(",")}` : "";
  const un = units ? `&units=${encodeURIComponent(units)}` : "";
  const res = await fetch(
    `${BASE}/documents/${documentId}/export?fmt=${format}&layout=statement&locale=${locale}${inc}${un}`,
    { headers: { ...authHeader() } },
  );
  if (!res.ok) throw new Error(`Export failed: ${res.status}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = format === "excel" ? "extract.xlsx" : "extract.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
