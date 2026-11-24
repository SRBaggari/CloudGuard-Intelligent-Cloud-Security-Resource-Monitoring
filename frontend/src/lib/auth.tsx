import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, tokens } from "./api";
import { useTheme } from "./theme";
import type { TokenPair, User } from "./types";

interface AuthState {
  user: User | null;
  ready: boolean;
  isAdmin: boolean;
  login: (username: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const { setPreference } = useTheme();

  // apply the theme saved in the user's profile when they sign in
  useEffect(() => {
    if (user?.theme_preference) setPreference(user.theme_preference);
  }, [user?.id, user?.theme_preference]); // eslint-disable-line react-hooks/exhaustive-deps

  const refreshUser = useCallback(async () => {
    if (!tokens.access) {
      setUser(null);
      return;
    }
    try {
      setUser(await api<User>("/api/auth/me"));
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    refreshUser().finally(() => setReady(true));
    const onLogout = () => setUser(null);
    window.addEventListener("cg:logout", onLogout);
    return () => window.removeEventListener("cg:logout", onLogout);
  }, [refreshUser]);

  const login = useCallback(async (username: string, password: string) => {
    const res = await api<TokenPair>("/api/auth/login", { method: "POST", body: { username, password }, auth: false });
    tokens.set(res.access_token, res.refresh_token);
    setUser(res.user);
    return res.user;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api("/api/auth/logout", { method: "POST", body: { refresh_token: tokens.refresh ?? "" } });
    } catch {
      /* already logged out server-side */
    }
    tokens.clear();
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, ready, isAdmin: user?.role_name === "admin", login, logout, refreshUser }),
    [user, ready, login, logout, refreshUser],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
