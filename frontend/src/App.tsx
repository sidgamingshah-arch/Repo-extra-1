import type { ReactNode } from "react";
import { useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { NavRail } from "./components/shell/NavRail";
import { TopBar } from "./components/shell/TopBar";
import Login from "./screens/Login";
import { ApiError } from "./lib/api";
import { useMe, useSettings } from "./lib/queries";
import { SCREENS } from "./screens/config";
import { useAppLocale, useUI } from "./store";
import { color } from "./theme";
import CommentaryScreen from "./screens/Commentary";
import ExportScreen from "./screens/Export";
import IntegrityScreen from "./screens/Integrity";
import NotesScreen from "./screens/Notes";
import ReviewScreen from "./screens/Review";
import ScopeScreen from "./screens/Scope";
import SettingsScreen from "./screens/Settings";
import TemplateScreen from "./screens/Template";
import UploadScreen from "./screens/Upload";
import WorkspaceScreen from "./screens/Workspace";

/** Route guard: renders the screen only if the caller's role may see it; otherwise
 * redirects to the first screen the role can access. */
function RequireScreen({ screen, children }: { screen: string; children: ReactNode }) {
  const { data: me, isPending } = useMe();
  if (isPending || !me) {
    return <div style={{ padding: 60, textAlign: "center", color: color.muted }}>Loading…</div>;
  }
  if (!me.screens.includes(screen)) {
    const first = me.screens[0] ?? "workspace";
    return <Navigate to={SCREENS[first]?.path ?? "/workspace"} replace />;
  }
  return <>{children}</>;
}

/** The authenticated application shell. */
function Shell() {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", width: "100%", overflow: "hidden" }}>
      <TopBar />
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        <NavRail />
        <div style={{ flex: 1, minWidth: 0, overflowY: "auto", position: "relative" }}>
          <Routes>
            <Route path="/" element={<Navigate to="/workspace" replace />} />
            <Route path="/upload" element={<RequireScreen screen="upload"><UploadScreen /></RequireScreen>} />
            <Route path="/integrity" element={<RequireScreen screen="integrity"><IntegrityScreen /></RequireScreen>} />
            <Route path="/scope" element={<RequireScreen screen="scope"><ScopeScreen /></RequireScreen>} />
            <Route path="/workspace" element={<RequireScreen screen="workspace"><WorkspaceScreen /></RequireScreen>} />
            <Route path="/notes" element={<RequireScreen screen="notes"><NotesScreen /></RequireScreen>} />
            <Route path="/review" element={<RequireScreen screen="review"><ReviewScreen /></RequireScreen>} />
            <Route path="/commentary" element={<RequireScreen screen="commentary"><CommentaryScreen /></RequireScreen>} />
            <Route path="/template" element={<RequireScreen screen="template"><TemplateScreen /></RequireScreen>} />
            <Route path="/settings" element={<RequireScreen screen="settings"><SettingsScreen /></RequireScreen>} />
            <Route path="/export" element={<RequireScreen screen="export"><ExportScreen /></RequireScreen>} />
            <Route path="*" element={<Navigate to="/workspace" replace />} />
          </Routes>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const token = useUI((s) => s.token);
  const setToken = useUI((s) => s.setToken);
  const setUiLocalization = useUI((s) => s.setUiLocalization);
  const appLocale = useAppLocale();
  const { data: me, isError, error } = useMe();
  const { data: settings } = useSettings();

  // A rejected session (stale/expired token → 401) cleanly returns the user to login.
  useEffect(() => {
    if (error instanceof ApiError && error.status === 401) setToken(null);
  }, [error, setToken]);

  // Keep the admin interface-localization flag in sync with the server.
  useEffect(() => {
    if (settings) setUiLocalization(settings.features.ui_localization);
  }, [settings, setUiLocalization]);

  // Reflect the effective interface locale on <html> (RTL only when the UI itself is
  // localized to Arabic; data-only Arabic keeps an LTR layout).
  useEffect(() => {
    if (typeof document === "undefined") return;
    document.documentElement.dir = appLocale === "ar" ? "rtl" : "ltr";
    document.documentElement.lang = appLocale;
  }, [appLocale]);

  // Not logged in (no token, or the session was rejected) → show the login screen.
  if (!token || isError || (token && me && !me.authenticated)) {
    return <Login />;
  }
  return <Shell />;
}
