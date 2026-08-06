import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { NavRail } from "./components/shell/NavRail";
import { TopBar } from "./components/shell/TopBar";
import { useMe } from "./lib/queries";
import { SCREENS } from "./screens/config";
import { useUI } from "./store";
import { color } from "./theme";
import CommentaryScreen from "./screens/Commentary";
import ExportScreen from "./screens/Export";
import IntegrityScreen from "./screens/Integrity";
import NotesScreen from "./screens/Notes";
import ReviewScreen from "./screens/Review";
import ScopeScreen from "./screens/Scope";
import TemplateScreen from "./screens/Template";
import UploadScreen from "./screens/Upload";
import WorkspaceScreen from "./screens/Workspace";

/** Route guard: renders the screen only if the caller's role may see it; otherwise
 * redirects to the first screen the role can access. */
function RequireScreen({ screen, children }: { screen: string; children: ReactNode }) {
  const role = useUI((s) => s.role);
  const { data: me, isPending } = useMe(role);
  if (isPending || !me) {
    return <div style={{ padding: 60, textAlign: "center", color: color.muted }}>Loading…</div>;
  }
  if (!me.screens.includes(screen)) {
    const first = me.screens[0] ?? "workspace";
    return <Navigate to={SCREENS[first]?.path ?? "/workspace"} replace />;
  }
  return <>{children}</>;
}

export default function App() {
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
            <Route path="/export" element={<RequireScreen screen="export"><ExportScreen /></RequireScreen>} />
            <Route path="*" element={<Navigate to="/workspace" replace />} />
          </Routes>
        </div>
      </div>
    </div>
  );
}
