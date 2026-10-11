import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, ApiError, setLockdownHandler, setUnauthorizedHandler } from "@/services/api";
import type { LoginResult, Me, Permission } from "@/types/api";

const ME_KEY = ["auth", "me"] as const;

/** Why the user was signed out without asking, shown on the sign-in screen. */
export type SignOutReason = "session_ended" | "lockdown";

interface AuthValue {
  user: Me | null;
  loading: boolean;
  /** Step 1. Resolves with mfa_required=true when a second factor is still needed. */
  login: (email: string, password: string) => Promise<LoginResult>;
  /** Step 2 (only when login returned mfa_required). */
  verifyMfa: (code: string) => Promise<void>;
  logout: () => Promise<void>;
  /** Local sign-out after the server ended the session (e.g. lockdown, suspension). */
  endSession: (reason: SignOutReason) => void;
  signOutReason: SignOutReason | null;
  refresh: () => Promise<void>;
  /** UI convenience only. The server enforces every permission independently. */
  can: (permission: Permission) => boolean;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [signOutReason, setSignOutReason] = useState<SignOutReason | null>(null);

  const meQuery = useQuery<Me | null>({
    queryKey: ME_KEY,
    queryFn: async () => {
      try {
        // skipUnauthorizedHandler: a 401 here simply means "not signed in", and the handler
        // resets the cache, which must not happen while this very query is in flight.
        return await api.get<Me>("/auth/me/", undefined, { skipUnauthorizedHandler: true });
      } catch (error) {
        // "Not signed in" is a normal state here, not a failure.
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
    staleTime: 60_000,
    retry: false,
  });

  /** Drop every cached response so the next user on this browser never sees the previous user's data. */
  const resetCache = useCallback(
    (user: Me | null) => {
      void queryClient.cancelQueries();
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== ME_KEY[0] });
      queryClient.setQueryData(ME_KEY, user);
    },
    [queryClient],
  );
  const clearSession = useCallback(() => resetCache(null), [resetCache]);
  const endSession = useCallback(
    (reason: SignOutReason) => {
      setSignOutReason(reason);
      resetCache(null);
    },
    [resetCache],
  );
  const refresh = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ME_KEY });
  }, [queryClient]);

  useEffect(() => {
    setUnauthorizedHandler(() => endSession("session_ended"));
    setLockdownHandler(() => void refresh());
    return () => {
      setUnauthorizedHandler(null);
      setLockdownHandler(null);
    };
  }, [endSession, refresh]);

  const login = useCallback(
    async (email: string, password: string) => {
      const result = await api.post<LoginResult>("/auth/login/", { email, password }, { skipUnauthorizedHandler: true });
      if (!result.mfa_required && result.user) {
        setSignOutReason(null);
        resetCache(result.user);
      }
      return result;
    },
    [resetCache],
  );

  const verifyMfa = useCallback(
    async (code: string) => {
      const result = await api.post<LoginResult>("/auth/mfa/verify/", { code }, { skipUnauthorizedHandler: true });
      setSignOutReason(null);
      resetCache(result.user);
    },
    [resetCache],
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout/", undefined, { skipUnauthorizedHandler: true });
    } catch {
      // The server session may outlive this failed request, but the user asked to leave:
      // always sign out locally and never surface an error from the sign-out button.
    } finally {
      setSignOutReason(null);
      clearSession();
    }
  }, [clearSession]);

  const user = meQuery.data ?? null;
  const value = useMemo<AuthValue>(
    () => ({
      user,
      loading: meQuery.isPending,
      login,
      verifyMfa,
      logout,
      endSession,
      signOutReason,
      refresh,
      can: (permission) => user?.permissions.includes(permission) ?? false,
    }),
    [user, meQuery.isPending, login, verifyMfa, logout, endSession, signOutReason, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
