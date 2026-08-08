/** React Query hooks — the data layer each screen consumes. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { Basis, Locale, SettingsPatch, StatementKey } from "../types";
import { useUI } from "../store";
import { api } from "./api";

// --- auth / identity ---
/** Current principal — enabled only once a session token exists; no retry so a 401
 * surfaces immediately as "logged out". */
export const useMe = () => {
  const token = useUI((s) => s.token);
  return useQuery({ queryKey: ["me", token], queryFn: api.me, enabled: !!token, retry: false });
};
export const useDemoUsers = () =>
  useQuery({ queryKey: ["demo-users"], queryFn: api.demoUsers });

export function useLogin() {
  const qc = useQueryClient();
  const setToken = useUI((s) => s.setToken);
  return useMutation({
    mutationFn: (vars: { username: string; password?: string }) =>
      api.login(vars.username, vars.password),
    onSuccess: (res) => {
      setToken(res.token);
      qc.invalidateQueries();
    },
  });
}

export function useLogout() {
  const qc = useQueryClient();
  const setToken = useUI((s) => s.setToken);
  return useMutation({
    mutationFn: () => api.logout().catch(() => ({ ok: true })),
    onSuccess: () => {
      setToken(null);
      qc.clear();
    },
  });
}

// --- settings ---
export const useSettings = () => {
  const token = useUI((s) => s.token);
  return useQuery({ queryKey: ["settings"], queryFn: api.settings, enabled: !!token });
};

export function usePatchSettings() {
  const qc = useQueryClient();
  const setUiLocalization = useUI((s) => s.setUiLocalization);
  return useMutation({
    mutationFn: (body: SettingsPatch) => api.patchSettings(body),
    onSuccess: (res) => {
      setUiLocalization(res.features.ui_localization);
      qc.setQueryData(["settings"], res);
      // Role gating (/me) depends on review_required; refresh it.
      qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
}

/** Analyst hands the final output to the reviewer; refreshes the audit log. */
export function useSubmitForReview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.submitForReview(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["audit"] }),
  });
}

// --- project data ---
export const useCommentary = (locale: Locale = "en") =>
  useQuery({ queryKey: ["commentary", locale], queryFn: () => api.commentary(locale) });
export const useAudit = () =>
  useQuery({ queryKey: ["audit"], queryFn: api.audit });

/** Trigger a live LLM analysis run; refreshes the audit log on completion. */
export function useRunAnalysis() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.runAnalysis(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["audit"] }),
  });
}
export const useProject = () => useQuery({ queryKey: ["project"], queryFn: api.project });
/** Whether a project's data is loaded (false in greenfield until a sample/real run exists). */
export const useProjectLoaded = () => useProject().data?.loaded ?? false;
export const useDocuments = () => useQuery({ queryKey: ["documents"], queryFn: api.documents });

export const useOntologies = () => useQuery({ queryKey: ["ontologies"], queryFn: api.ontologies });
export const useTemplates = () => useQuery({ queryKey: ["templates"], queryFn: api.templates });

/** Run (and fetch) the extraction for one uploaded document — its real line items with
 * provenance, mapped against the given ontology/template. POSTs once per (doc, ontology)
 * and caches the result. `enabled` gates the run until the ontology list has settled. */
export const useExtraction = (
  documentId: string | undefined,
  ontologyId?: string,
  templateId?: string,
  enabled = true,
) =>
  useQuery({
    queryKey: ["extraction", documentId, ontologyId ?? null, templateId ?? null],
    queryFn: () => api.runExtraction(documentId as string, {
      ontology_version_id: ontologyId, template_version_id: templateId,
    }),
    enabled: !!documentId && enabled,
    staleTime: Infinity,
    retry: false,
  });

/** Cells around a value's spreadsheet origin — the Excel click-to-source backdrop.
 * Enabled only once a spreadsheet cell has been picked. */
export const useCellContext = (documentId: string, sheet?: string, cell?: string) =>
  useQuery({
    queryKey: ["cell-context", documentId, sheet ?? null, cell ?? null],
    queryFn: () => api.cellContext(documentId, sheet as string, cell as string),
    enabled: !!documentId && !!sheet && !!cell,
    staleTime: Infinity,
    retry: false,
  });

/** Upload a source document; refreshes the documents list and project, and marks the
 * uploaded document active so the Integrity/Extract steps operate on the real file. */
export function useUploadDocument() {
  const qc = useQueryClient();
  const setActiveDocumentId = useUI((s) => s.setActiveDocumentId);
  return useMutation({
    mutationFn: (file: File) => api.uploadDocument(file),
    onSuccess: (res) => {
      if (res?.id) setActiveDocumentId(res.id);
      qc.invalidateQueries({ queryKey: ["documents"] });
      qc.invalidateQueries({ queryKey: ["project"] });
    },
  });
}

/** Real per-document pre-flight integrity — the uploaded file's own results. */
export const useDocumentIntegrity = (documentId: string | undefined) =>
  useQuery({
    queryKey: ["document-integrity", documentId],
    queryFn: () => api.documentIntegrity(documentId as string),
    enabled: !!documentId,
    retry: false,
  });

/** Real per-document review queue (unmapped + low-confidence items from the latest run). */
export const useDocumentReview = (documentId: string | undefined) =>
  useQuery({
    queryKey: ["document-review", documentId],
    queryFn: () => api.documentReview(documentId as string),
    enabled: !!documentId,
    retry: false,
  });

/** Latest extraction run for a document (Export preview/counts). */
export const useDocumentRun = (documentId: string | undefined) =>
  useQuery({
    queryKey: ["document-run", documentId],
    queryFn: () => api.documentRun(documentId as string),
    enabled: !!documentId,
    retry: false,
  });
export const useIntegrity = (locale: Locale = "en", enabled = true) =>
  useQuery({ queryKey: ["integrity", locale], queryFn: () => api.integrity(locale), enabled });
export const usePages = (locale: Locale = "en", enabled = true) =>
  useQuery({ queryKey: ["pages", locale], queryFn: () => api.pages(locale), enabled });
export const useReview = (locale: Locale = "en", enabled = true) =>
  useQuery({ queryKey: ["review", locale], queryFn: () => api.review(locale), enabled });
export const useNotes = (locale: Locale = "en") =>
  useQuery({ queryKey: ["notes", locale], queryFn: () => api.notes(locale) });
export const useNote = (no: number, locale: Locale = "en") =>
  useQuery({ queryKey: ["note", no, locale], queryFn: () => api.note(no, locale) });
export const useTemplate = (locale: Locale = "en") =>
  useQuery({ queryKey: ["template", locale], queryFn: () => api.template(locale) });
export const useExportOptions = () =>
  useQuery({ queryKey: ["export-options"], queryFn: api.exportOptions });
export const useLanguages = () => useQuery({ queryKey: ["languages"], queryFn: api.languages });

export const useStatement = (statement: StatementKey, basis: Basis, locale: Locale = "en", enabled = true) =>
  useQuery({
    queryKey: ["statement", statement, basis, locale],
    queryFn: () => api.statement(statement, basis, locale),
    enabled,
  });

/** Real per-page classification for a document (Page Scope). */
export const useDocumentPages = (documentId: string | undefined) =>
  useQuery({
    queryKey: ["document-pages", documentId],
    queryFn: () => api.documentPages(documentId as string),
    enabled: !!documentId,
    retry: false,
  });

/** One statement of a document's real extraction (Workspace grid). */
export const useDocumentStatement = (documentId: string | undefined, statement: StatementKey, basis: Basis) =>
  useQuery({
    queryKey: ["document-statement", documentId, statement, basis],
    queryFn: () => api.documentStatement(documentId as string, statement, basis),
    enabled: !!documentId,
    retry: false,
  });

export function useEditLineItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; value: number | null; formula: string }) =>
      api.editLineItem(vars.id, vars.value, vars.formula),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["statement"] }),
  });
}
