import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, getToken, setToken, setUnauthorizedHandler } from "./api";
import type { User } from "./types";

function load<T>(key: string, fallback: T): T {
  try {
    const raw = sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}
function save(key: string, value: unknown) {
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* ignore */
  }
}

export interface ShortlistState {
  jobId: string | null;
  selected: string[];
  minScore: string;
  maxScore: string;
  draft: { subject?: string; message?: string };
}

interface AppState {
  user: User | null;
  loadingUser: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  can: (perm: string) => boolean;
  activeJobId: string | null;
  setActiveJobId: (id: string | null) => void;
  shortlist: ShortlistState;
  toggleSelected: (jobId: string, appId: string) => void;
  setSelected: (jobId: string, ids: string[]) => void;
  setRange: (jobId: string, min: string, max: string) => void;
  setDraft: (d: { subject?: string; message?: string }) => void;
  demoMode: boolean;
}

const Ctx = createContext<AppState | null>(null);
const EMPTY: ShortlistState = { jobId: null, selected: [], minScore: "", maxScore: "", draft: {} };

/** Selection and range are per job: switching jobs starts a fresh selection. */
function forJob(s: ShortlistState, jobId: string): ShortlistState {
  return s.jobId === jobId ? s : { ...EMPTY, jobId, draft: s.draft };
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loadingUser, setLoadingUser] = useState(true);
  const [activeJobId, setActiveJobIdState] = useState<string | null>(() => load("tm_job", null));
  const [shortlist, setShortlist] = useState<ShortlistState>(() => load("tm_shortlist", EMPTY));
  const [demoMode, setDemoMode] = useState(true);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    setShortlist(EMPTY);
    save("tm_shortlist", EMPTY);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(logout);
    api("/health").then((h) => setDemoMode(Boolean(h.mock_services))).catch(() => {});
    if (!getToken()) {
      setLoadingUser(false);
      return;
    }
    api<User>("/auth/me")
      .then(setUser)
      .catch(() => logout())
      .finally(() => setLoadingUser(false));
  }, [logout]);

  useEffect(() => save("tm_shortlist", shortlist), [shortlist]);

  // Stable action callbacks so pages can list them as effect dependencies without re-running.
  const setActiveJobId = useCallback((id: string | null) => {
    setActiveJobIdState(id);
    save("tm_job", id);
  }, []);
  const toggleSelected = useCallback((jobId: string, appId: string) => {
    setShortlist((s) => {
      const cur = forJob(s, jobId);
      const has = cur.selected.includes(appId);
      return { ...cur, selected: has ? cur.selected.filter((x) => x !== appId) : [...cur.selected, appId] };
    });
  }, []);
  const setSelected = useCallback((jobId: string, ids: string[]) => {
    setShortlist((s) => ({ ...forJob(s, jobId), selected: ids }));
  }, []);
  const setRange = useCallback((jobId: string, min: string, max: string) => {
    setShortlist((s) => ({ ...forJob(s, jobId), minScore: min, maxScore: max }));
  }, []);
  const setDraft = useCallback((d: { subject?: string; message?: string }) => {
    setShortlist((s) => ({ ...s, draft: { ...s.draft, ...d } }));
  }, []);
  const login = useCallback(async (email: string, password: string) => {
    const r = await api<{ access_token: string; user: User }>("/auth/login", { body: { email, password } });
    setToken(r.access_token);
    setUser(r.user);
  }, []);

  const value = useMemo<AppState>(
    () => ({
      user,
      loadingUser,
      demoMode,
      login,
      logout,
      can: (perm) => Boolean(user?.permissions.includes(perm)),
      activeJobId,
      setActiveJobId,
      shortlist,
      toggleSelected,
      setSelected,
      setRange,
      setDraft,
    }),
    [user, loadingUser, demoMode, login, logout, activeJobId, setActiveJobId, shortlist, toggleSelected, setSelected, setRange, setDraft],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp outside AppProvider");
  return v;
}
