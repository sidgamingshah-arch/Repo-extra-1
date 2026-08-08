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

/** Error carrying the HTTP status so callers (e.g. auth gating) can special-case 401. */
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
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
    throw new ApiError(res.status, `${res.status} ${res.statusText} — ${text}`);
  }
  return res.json() as Promise<T>;
}

import type {
  AppSettings,
  AuditEntry,
  AuditResponse,
  Basis,
  CellContext,
  Commentary,
  DemoUser,
  ExtractionRunResponse,
  ExportFmt,
  IntegrityResponse,
  Locale,
  LoginResponse,
  Me,
  NoteDetail,
  NotesResponse,
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
  /** One statement of a document's real extraction, grouped for the Workspace grid. */
  documentStatement: (documentId: string, statement: StatementKey, basis: Basis) =>
    req<StatementResponse>(
      `/documents/${documentId}/statement?statement=${statement}&basis=${basis}`,
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
  languages: () =>
    req<{ languages: { locale: string; name: string; rtl: boolean; supported: boolean }[]; fully_supported: string[] }>(
      `/languages`,
    ),
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

/** GET a REAL document's export (built from its latest extraction) and download it. */
export async function downloadDocumentExport(documentId: string, format: ExportFmt): Promise<void> {
  const res = await fetch(`${BASE}/documents/${documentId}/export?fmt=${format}`, {
    headers: { ...authHeader() },
  });
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
