/** Thin fetch client. All calls go to /api/v1 (proxied to FastAPI in dev). */
const BASE = "/api/v1";
const PROJECT = "demo";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText} — ${text}`);
  }
  return res.json() as Promise<T>;
}

import type {
  Basis,
  ExportFmt,
  IntegrityResponse,
  Locale,
  NoteDetail,
  NotesResponse,
  PagesResponse,
  Project,
  ReviewResponse,
  SourceDoc,
  StatementKey,
  StatementResponse,
  TemplateResponse,
  ExportOption,
} from "../types";

export const api = {
  project: () => req<{ project: Project; documents: SourceDoc[] }>(`/projects/${PROJECT}`),
  integrity: () => req<IntegrityResponse>(`/projects/${PROJECT}/integrity`),
  pages: () => req<PagesResponse>(`/projects/${PROJECT}/pages`),
  statement: (statement: StatementKey, basis: Basis, locale: Locale = "en") =>
    req<StatementResponse>(`/projects/${PROJECT}/statements/${statement}?basis=${basis}&locale=${locale}`),
  editLineItem: (id: string, value: number | null, formula: string) =>
    req<{ id: string; value: number | null; formula: string }>(
      `/projects/${PROJECT}/line-items/${id}`,
      { method: "PATCH", body: JSON.stringify({ value, formula }) },
    ),
  revertLineItem: (id: string) =>
    req<{ id: string }>(`/projects/${PROJECT}/line-items/${id}`, { method: "DELETE" }),
  notes: () => req<NotesResponse>(`/projects/${PROJECT}/notes`),
  note: (no: number) => req<NoteDetail>(`/projects/${PROJECT}/notes/${no}`),
  review: () => req<ReviewResponse>(`/projects/${PROJECT}/review`),
  template: () => req<TemplateResponse>(`/projects/${PROJECT}/template`),
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
    headers: { "Content-Type": "application/json" },
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
