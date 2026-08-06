/** Client-side permission helpers (mirrors the backend RBAC; the server still
 * enforces). Screens use useCan() to hide/disable admin-only configuration controls.
 * Both derive from the authenticated session (/me), not a client-chosen role. */
import { useMe } from "./queries";

export function useCan(permission: string): boolean {
  const { data: me } = useMe();
  return !!me?.permissions.includes(permission);
}

export function useRole(): string | undefined {
  const { data: me } = useMe();
  return me?.role;
}
