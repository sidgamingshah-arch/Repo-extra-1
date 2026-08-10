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
 * provenance, mapped against the given ontology/template. Extraction is a background job:
 * this POSTs once per (doc, ontology/template) to start it, then polls the run until it
 * reaches succeeded/failed. `enabled` gates the start until the ontology list has settled. */
export function useExtraction(
  documentId: string | undefined,
  ontologyId?: string,
  templateId?: string,
  enabled = true,
) {
  const start = useQuery({
    queryKey: ["extraction-start", documentId, ontologyId ?? null, templateId ?? null],
    queryFn: () => api.runExtraction(documentId as string, {
      ontology_version_id: ontologyId, template_version_id: templateId,
    }),
    enabled: !!documentId && enabled,
    staleTime: Infinity,
    retry: false,
  });
  const runId = start.data?.run_id;
  const poll = useQuery({
    queryKey: ["extraction-run", runId],
    queryFn: () => api.getRun(runId as string),
    enabled: !!runId,
    retry: false,
    // Keep polling while the background job is running; stop once it settles.
    refetchInterval: (q) => (q.state.data?.status === "running" ? 1000 : false),
  });

  const run = poll.data;
  const succeeded = run?.status === "succeeded" && !!run?.result;
  const failed = start.isError || poll.isError || run?.status === "failed";
  return {
    data: succeeded ? run : undefined,
    isPending: (start.isPending && enabled) || (!!runId && !succeeded && !failed),
    isError: failed,
    error: (start.error as Error) ?? (poll.error as Error) ?? undefined,
  };
}

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

/** Generate an LLM credit narrative for a document (on-demand; the deterministic credit
 * view is always available regardless). */
export function useCreditNarrative() {
  return useMutation({
    mutationFn: ({ id, locale }: { id: string; locale: Locale }) => api.creditNarrative(id, locale),
  });
}

/** Delete an uploaded document (owner/admin). Refreshes the list and clears the active
 * document when it's the one removed, so the pipeline steps fall back cleanly. */
export function useDeleteDocument() {
  const qc = useQueryClient();
  const activeDocumentId = useUI((s) => s.activeDocumentId);
  const setActiveDocumentId = useUI((s) => s.setActiveDocumentId);
  return useMutation({
    mutationFn: (id: string) => api.deleteDocument(id),
    onSuccess: (_res, id) => {
      if (activeDocumentId === id) setActiveDocumentId(null);
      qc.invalidateQueries({ queryKey: ["documents"] });
      qc.invalidateQueries({ queryKey: ["project"] });
    },
  });
}

/** Real per-document pre-flight integrity — the uploaded file's own results. */
export const useDocumentIntegrity = (documentId: string | undefined, locale: Locale = "en") =>
  useQuery({
    queryKey: ["document-integrity", documentId, locale],
    queryFn: () => api.documentIntegrity(documentId as string, locale),
    enabled: !!documentId,
    retry: false,
  });

/** Real per-document review queue (unmapped + low-confidence items from the latest run). */
export const useDocumentReview = (documentId: string | undefined, locale: Locale = "en") =>
  useQuery({
    queryKey: ["document-review", documentId, locale],
    queryFn: () => api.documentReview(documentId as string, locale),
    enabled: !!documentId,
    retry: false,
  });

/** Derived analysis (ratios / disclosures / notes) for a document. */
export const useDocumentAnalysis = (documentId: string | undefined, locale: Locale = "en") =>
  useQuery({
    queryKey: ["document-analysis", documentId, locale],
    queryFn: () => api.documentAnalysis(documentId as string, locale),
    enabled: !!documentId,
    retry: false,
  });

/** Real per-document notes index + one note's detail. */
export const useDocumentNotes = (documentId: string | undefined) =>
  useQuery({
    queryKey: ["document-notes", documentId],
    queryFn: () => api.documentNotes(documentId as string),
    enabled: !!documentId,
    retry: false,
  });
export const useDocumentNote = (documentId: string | undefined, no: number) =>
  useQuery({
    queryKey: ["document-note", documentId, no],
    queryFn: () => api.documentNote(documentId as string, no),
    enabled: !!documentId,
    retry: false,
  });

/** Edit a value/formula on a real extraction; refreshes the document's statement/run/export. */
export function useEditDocumentLineItem(documentId: string | undefined) {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["document-statement", documentId] });
    qc.invalidateQueries({ queryKey: ["document-run", documentId] });
    qc.invalidateQueries({ queryKey: ["document-review", documentId] });
  };
  return useMutation({
    mutationFn: (vars: { key: string; value: number | null; formula: string }) =>
      api.editDocumentLineItem(documentId as string, vars.key, vars.value, vars.formula),
    onSuccess: invalidate,
  });
}

/** Revert an edited real line item to its original machine-extracted values. */
export function useRevertDocumentLineItem(documentId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (key: string) => api.revertDocumentLineItem(documentId as string, key),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["document-statement", documentId] });
      qc.invalidateQueries({ queryKey: ["document-run", documentId] });
      qc.invalidateQueries({ queryKey: ["document-review", documentId] });
    },
  });
}

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
export const useNotes = (locale: Locale = "en", enabled = true) =>
  useQuery({ queryKey: ["notes", locale], queryFn: () => api.notes(locale), enabled });
export const useNote = (no: number, locale: Locale = "en", enabled = true) =>
  useQuery({ queryKey: ["note", no, locale], queryFn: () => api.note(no, locale), enabled });
export const useTemplate = (locale: Locale = "en") =>
  useQuery({ queryKey: ["template", locale], queryFn: () => api.template(locale) });
/** A real configured template's structure (Template & Ontology screen, admin). */
export const useTemplateDetail = (id: string | undefined, locale: Locale = "en") =>
  useQuery({
    queryKey: ["template-detail", id, locale],
    queryFn: () => api.templateDetail(id as string, locale),
    enabled: !!id,
  });
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

/** Persist the user's page selection for extraction; refreshes the pages view. */
export function useSetDocumentScope(documentId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (includedPages: number[]) =>
      api.setDocumentScope(documentId as string, includedPages),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["document-pages", documentId] }),
  });
}

/** Data-driven commentary from a document's real extraction (Analysis screen, real mode). */
export const useDocumentCommentary = (documentId: string | undefined, locale: Locale = "en") =>
  useQuery({
    queryKey: ["document-commentary", documentId, locale],
    queryFn: () => api.documentCommentary(documentId as string, locale),
    enabled: !!documentId,
    retry: false,
  });

/** One statement of a document's real extraction (Workspace grid), labels in `locale`. */
export const useDocumentStatement = (
  documentId: string | undefined, statement: StatementKey, basis: Basis, locale: Locale = "en") =>
  useQuery({
    queryKey: ["document-statement", documentId, statement, basis, locale],
    queryFn: () => api.documentStatement(documentId as string, statement, basis, locale),
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
