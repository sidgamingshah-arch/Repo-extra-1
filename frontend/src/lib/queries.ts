/** React Query hooks — the data layer each screen consumes. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { Basis, Locale, StatementKey } from "../types";
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
    mutationFn: (body: { ui_localization?: boolean }) => api.patchSettings(body),
    onSuccess: (res) => {
      setUiLocalization(res.features.ui_localization);
      qc.setQueryData(["settings"], res);
    },
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
export const useIntegrity = (locale: Locale = "en") =>
  useQuery({ queryKey: ["integrity", locale], queryFn: () => api.integrity(locale) });
export const usePages = (locale: Locale = "en") =>
  useQuery({ queryKey: ["pages", locale], queryFn: () => api.pages(locale) });
export const useReview = (locale: Locale = "en") =>
  useQuery({ queryKey: ["review", locale], queryFn: () => api.review(locale) });
export const useNotes = (locale: Locale = "en") =>
  useQuery({ queryKey: ["notes", locale], queryFn: () => api.notes(locale) });
export const useNote = (no: number, locale: Locale = "en") =>
  useQuery({ queryKey: ["note", no, locale], queryFn: () => api.note(no, locale) });
export const useTemplate = (locale: Locale = "en") =>
  useQuery({ queryKey: ["template", locale], queryFn: () => api.template(locale) });
export const useExportOptions = () =>
  useQuery({ queryKey: ["export-options"], queryFn: api.exportOptions });
export const useLanguages = () => useQuery({ queryKey: ["languages"], queryFn: api.languages });

export const useStatement = (statement: StatementKey, basis: Basis, locale: Locale = "en") =>
  useQuery({
    queryKey: ["statement", statement, basis, locale],
    queryFn: () => api.statement(statement, basis, locale),
  });

export function useEditLineItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; value: number | null; formula: string }) =>
      api.editLineItem(vars.id, vars.value, vars.formula),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["statement"] }),
  });
}
