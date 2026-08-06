/** Client-side permission helpers (mirrors the backend RBAC; the server still
 * enforces). Screens use useCan() to hide/disable admin-only configuration controls. */
import { useUI } from "../store";
import { useMe } from "./queries";

export function useCan(permission: string): boolean {
  const role = useUI((s) => s.role);
  const { data: me } = useMe(role);
  return !!me?.permissions.includes(permission);
}

export function useRole() {
  return useUI((s) => s.role);
}
