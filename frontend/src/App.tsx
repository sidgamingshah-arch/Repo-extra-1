import type { ReactNode } from "react";
import { useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { NavRail } from "./components/shell/NavRail";
import { TopBar } from "./components/shell/TopBar";
import Login from "./screens/Login";
import { useMe, useSettings } from "./lib/queries";
import { SCREENS } from "./screens/config";
import { useAppLocale, useUI } from "./store";
import { color } from "./theme";
import CommentaryScreen from "./screens/Commentary";
import ExportScreen from "./screens/Export";
import ExtractionView from "./screens/ExtractionView";
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
            {/* Extraction is its OWN destination. It used to be mounted only at /documents/:id and
                gated on the `upload` screen, with no entry in SCREENS — so it appeared in no nav
                group, held no stepper slot, and `screenIdForPath` fell through to its "workspace"
                default, which left the rail and the stepper both highlighting Workspace while the
                reader was looking at the extraction. A screen the product cannot name is a screen
                the reader cannot find. */}
            <Route path="/extraction" element={<RequireScreen screen="extraction"><ExtractionView /></RequireScreen>} />
            {/* The old deep link still resolves: an extraction is bound to the ACTIVE document
                (`useUI.activeDocumentId`, persisted to localStorage), so the id in the path was
                never what selected it. Kept as a redirect rather than deleted because links to it
                exist in the wild — in the Upload screen's own buttons, among other places. */}
            <Route path="/documents/:id" element={<Navigate to="/extraction" replace />} />
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
  const setUiLocalization = useUI((s) => s.setUiLocalization);
  const appLocale = useAppLocale();
  const { data: settings } = useSettings();

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

  // No session → login. A 401 from any query clears the token (see main.tsx's
  // QueryCache handler), so an expired/rejected session lands here too. Transient
  // non-401 errors keep the shell rather than bouncing an authenticated user out.
  if (!token) return <Login />;
  return <Shell />;
}
