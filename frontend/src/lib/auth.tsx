import { createContext, useCallback, useContext, useEffect, useMemo, type ReactNode } from "react";
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api, ApiError, setCsrfToken } from "./api";
import type { Me, Role } from "./types";

interface AuthValue {
  me: Me | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  switchOrg: (orgId: string) => Promise<void>;
  can: (action: Permission) => boolean;
}

export type Permission = "write" | "decide" | "admin";

const AuthContext = createContext<AuthValue | null>(null);

const ROLE_PERMS: Record<Role, Permission[]> = {
  org_admin: ["write", "decide", "admin"],
  reviewer: ["write", "decide"],
  analyst: ["write"],
  viewer: [],
};

/**
 * Drop cached data from the previous identity/organisation. The "me" query is kept
 * (and overwritten) because AuthProvider's observer stays attached to it; clearing
 * the whole cache would detach the observer and leave the stale value on screen.
 */
function clearOtherQueries(qc: QueryClient) {
  qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api<Me>("/auth/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
    retry: false,
  });
  const me = meQuery.data ?? null;

  useEffect(() => {
    if (me) setCsrfToken(me.csrf_token);
  }, [me]);

  const login = useCallback(
    async (email: string, password: string) => {
      const result = await api<Me>("/auth/login", { json: { email, password } });
      setCsrfToken(result.csrf_token);
      clearOtherQueries(qc);
      qc.setQueryData(["me"], result);
    },
    [qc],
  );

  const logout = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      setCsrfToken("");
      clearOtherQueries(qc);
      qc.setQueryData(["me"], null);
    }
  }, [qc]);

  const switchOrg = useCallback(
    async (orgId: string) => {
      const result = await api<Me>("/auth/switch-org", { json: { org_id: orgId } });
      clearOtherQueries(qc);
      qc.setQueryData(["me"], result);
    },
    [qc],
  );

  const can = useCallback((p: Permission) => (me ? ROLE_PERMS[me.role].includes(p) : false), [me]);

  const value = useMemo(
    () => ({ me, loading: meQuery.isLoading, login, logout, switchOrg, can }),
    [me, meQuery.isLoading, login, logout, switchOrg, can],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
