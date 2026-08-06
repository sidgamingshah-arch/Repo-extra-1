/** React Query hooks — the data layer each screen consumes. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { Basis, Locale, StatementKey } from "../types";
import { api } from "./api";

export const useMe = (role: string) =>
  useQuery({ queryKey: ["me", role], queryFn: api.me });
export const useCommentary = (locale: Locale = "en") =>
  useQuery({ queryKey: ["commentary", locale], queryFn: () => api.commentary(locale) });
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
