/** React Query hooks — the data layer each screen consumes. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { Basis, StatementKey } from "../types";
import { api } from "./api";

export const useProject = () => useQuery({ queryKey: ["project"], queryFn: api.project });
export const useIntegrity = () => useQuery({ queryKey: ["integrity"], queryFn: api.integrity });
export const usePages = () => useQuery({ queryKey: ["pages"], queryFn: api.pages });
export const useReview = () => useQuery({ queryKey: ["review"], queryFn: api.review });
export const useNotes = () => useQuery({ queryKey: ["notes"], queryFn: api.notes });
export const useNote = (no: number) =>
  useQuery({ queryKey: ["note", no], queryFn: () => api.note(no) });
export const useTemplate = () => useQuery({ queryKey: ["template"], queryFn: api.template });
export const useExportOptions = () =>
  useQuery({ queryKey: ["export-options"], queryFn: api.exportOptions });
export const useLanguages = () => useQuery({ queryKey: ["languages"], queryFn: api.languages });

export const useStatement = (statement: StatementKey, basis: Basis) =>
  useQuery({
    queryKey: ["statement", statement, basis],
    queryFn: () => api.statement(statement, basis),
  });

export function useEditLineItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; value: number | null; formula: string }) =>
      api.editLineItem(vars.id, vars.value, vars.formula),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["statement"] }),
  });
}
