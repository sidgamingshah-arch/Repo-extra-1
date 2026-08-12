/** React Query hooks — the data layer each screen consumes. */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { Basis, FxRateInput, Locale, OntologyRef, SettingsPatch, StatementKey } from "../types";
import { useUI } from "../store";
import { api, downloadOntologySkeleton } from "./api";

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

// --- FX rate master ---
/** The whole FX master (admin editor). Readable by any authenticated user. */
export const useFxRates = () => {
  const token = useUI((s) => s.token);
  return useQuery({ queryKey: ["fx-rates"], queryFn: api.fxRates, enabled: !!token });
};

/** Resolve one currency pair against the master. Disabled while `base`/`quote` are absent
 *  or equal — an identical pair is not a conversion, so there is nothing to look up.
 *  A "no rate configured" answer is data, not an error: it arrives as `resolved: false`
 *  and the caller must then decline to convert. */
export const useFxRateResolution = (base: string | undefined, quote: string | undefined) => {
  const enabled = !!base && !!quote && base !== quote;
  return useQuery({
    queryKey: ["fx-resolve", base ?? null, quote ?? null],
    queryFn: () => api.resolveFxRate(base as string, quote as string),
    enabled,
    retry: false,
  });
};

/** Create/restate a rate (admin). Invalidates the master AND every resolution, since a new
 *  rate can change — or newly enable — any pair currently on screen. */
export function useUpsertFxRate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: FxRateInput) => api.upsertFxRate(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["fx-rates"] });
      qc.invalidateQueries({ queryKey: ["fx-resolve"] });
    },
  });
}

export function useUpdateFxRate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; body: FxRateInput }) => api.updateFxRate(vars.id, vars.body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["fx-rates"] });
      qc.invalidateQueries({ queryKey: ["fx-resolve"] });
    },
  });
}

export function useDeleteFxRate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteFxRate(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["fx-rates"] });
      qc.invalidateQueries({ queryKey: ["fx-resolve"] });
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

/** The rulebook IN FORCE among the rows matching `pred` — the ONE copy of that rule on the client.
 *
 * It lives in the data layer because two screens ask the question (the index, to name the rulebook
 * a template row is described by; the extraction view, to decide which one a run defaults to) and
 * they were answering it differently: each had its own `version >` comparison, which is a third
 * and fourth spelling of a rule the server already owns.
 *
 * `version` counts edits to ONE ontology_key, so it cannot rank two DIFFERENT rulebooks targeting
 * the same template. With v1 and the v2 that replaces it both seeded at version 1 the comparison
 * was a tie and the index named whichever row arrived first — the superseded v1, while the
 * extractor was using v2. Order, therefore: drop what has been replaced; then prefer a rulebook
 * that DECLARES it replaces something, so a generated skeleton of empty stubs cannot outrank the
 * adopted rulebook by having been saved a few more times; then the highest version; then the key,
 * so the answer is stable rather than a property of row order. This mirrors
 * `app/services/ontology_select.pick` — the extractor's own choice — deliberately, and the
 * server-computed `superseded` flag is read rather than re-derived so the two cannot disagree.
 */
export function ontologyInForce(
  rows: OntologyRef[] | undefined,
  pred: (o: OntologyRef) => boolean = () => true,
): OntologyRef | undefined {
  const matches = (rows ?? []).filter(pred);
  if (!matches.length) return undefined;
  // Every candidate superseded is still an answer: what a row is described by is the best of what
  // EXISTS. Reporting nothing would read as "no rulebook", which is a different fact.
  const live = matches.filter((o) => !o.superseded);
  const rank = (o: OntologyRef): [number, number, string] =>
    [o.supersedes ? 1 : 0, o.version, o.ontology_key];
  return (live.length ? live : matches).reduce((best, o) => {
    const [ad, av, ak] = rank(o);
    const [bd, bv, bk] = rank(best);
    if (ad !== bd) return ad > bd ? o : best;
    if (av !== bv) return av > bv ? o : best;
    return ak > bk ? o : best;
  });
}

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

/** Everything a manual value changes. An edit moves the statement figure, and with it the
 *  accounting checks, the KPIs, the commentary and the export — refreshing only the grid left
 *  the rest of the app showing the pre-edit number. */
function invalidateAfterEdit(qc: ReturnType<typeof useQueryClient>, documentId: string | undefined) {
  for (const key of ["document-statement", "document-run", "document-review",
                     "document-analysis", "document-commentary"]) {
    qc.invalidateQueries({ queryKey: [key, documentId] });
  }
}

/** Edit ONE figure on a real extraction — a concept, in one basis, for one period.
 *  Errors are NOT swallowed: the caller shows the server's reason and keeps the editor open,
 *  because a rejected edit that closes the editor looks exactly like a saved one. */
export function useEditDocumentLineItem(documentId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: {
      key: string; value: number | null; formula: string;
      basis: Basis; period: "current" | "prior"; comment?: string;
    }) =>
      api.editDocumentLineItem(documentId as string, vars.key, vars.value, vars.formula,
                               vars.basis, vars.period, vars.comment ?? ""),
    onSuccess: () => invalidateAfterEdit(qc, documentId),
  });
}

/** Revert an edited real line item to its original machine-extracted values. */
export function useRevertDocumentLineItem(documentId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (key: string) => api.revertDocumentLineItem(documentId as string, key),
    onSuccess: () => invalidateAfterEdit(qc, documentId),
  });
}

/** Publish an edited template workbook as a new template version; refreshes the template lists
 *  so the new version is immediately selectable on Upload. */
export function useUploadTemplateXlsx() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { file: File; templateKey: string; name: string }) =>
      api.uploadTemplateXlsx(vars.file, vars.templateKey, vars.name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["templates"] });
      qc.invalidateQueries({ queryKey: ["template-detail"] });
      qc.invalidateQueries({ queryKey: ["project"] });
    },
  });
}

/** Upload an ontology (the extraction rulebook) against a template. */
export function useUploadOntology() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { definition: unknown; targetTemplateKey?: string }) =>
      api.createOntology(vars.definition, vars.targetTemplateKey),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ontologies"] });
      qc.invalidateQueries({ queryKey: ["template-detail"] });
    },
  });
}

/** The shape an authored ontology must have (JSON Schema + the per-field index).
 *
 * `enabled` exists because the endpoint is admin-only: called without `config:ontology` it 403s,
 * so the screen must gate it on the permission rather than let every viewer fire a doomed request.
 * Generated from the models, so it cannot change between requests — fetched once and kept. */
export const useOntologySchema = (enabled = true) =>
  useQuery({
    queryKey: ["ontology-schema"],
    queryFn: api.ontologySchema,
    enabled,
    staleTime: Infinity,
    retry: false,
  });

/** Download a ready-to-edit ontology skeleton for a template.
 *
 * A mutation, not a query: it writes a file to the user's disk, so it must run when the button is
 * pressed and never be replayed from cache — and its failure has to reach the screen, because a
 * download that silently did nothing is indistinguishable from one the browser blocked. */
export function useDownloadOntologySkeleton() {
  return useMutation({
    mutationFn: (vars: { templateId: string; fallbackName: string }) =>
      downloadOntologySkeleton(vars.templateId, vars.fallbackName),
  });
}

/** What the template workbook's columns mean — read from the reader that enforces them, so the
 *  screen can never describe a contract the API doesn't hold to. */
export const useTemplateXlsxColumns = () =>
  useQuery({ queryKey: ["template-xlsx-columns"], queryFn: api.templateXlsxColumns });

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
/** A real configured template's structure (Template & Ontology screen, admin).
 *
 * Keeps the previous template's detail on screen while a newly selected one loads. Without it the
 * screen blanks to "Loading…" on every selection change — which also unmounted the authoring
 * panel the moment it published a template and selected the new version, taking its confirmation
 * (or its error) with it. */
export const useTemplateDetail = (id: string | undefined, locale: Locale = "en") =>
  useQuery({
    queryKey: ["template-detail", id, locale],
    queryFn: () => api.templateDetail(id as string, locale),
    enabled: !!id,
    placeholderData: keepPreviousData,
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
