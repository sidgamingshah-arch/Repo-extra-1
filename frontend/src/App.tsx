import { Navigate, Route, Routes } from "react-router-dom";

import { NavRail } from "./components/shell/NavRail";
import { TopBar } from "./components/shell/TopBar";
import ExportScreen from "./screens/Export";
import IntegrityScreen from "./screens/Integrity";
import NotesScreen from "./screens/Notes";
import ReviewScreen from "./screens/Review";
import ScopeScreen from "./screens/Scope";
import TemplateScreen from "./screens/Template";
import UploadScreen from "./screens/Upload";
import WorkspaceScreen from "./screens/Workspace";

export default function App() {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", width: "100%", overflow: "hidden" }}>
      <TopBar />
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        <NavRail />
        <div style={{ flex: 1, minWidth: 0, overflowY: "auto", position: "relative" }}>
          <Routes>
            <Route path="/" element={<Navigate to="/workspace" replace />} />
            <Route path="/upload" element={<UploadScreen />} />
            <Route path="/integrity" element={<IntegrityScreen />} />
            <Route path="/scope" element={<ScopeScreen />} />
            <Route path="/workspace" element={<WorkspaceScreen />} />
            <Route path="/notes" element={<NotesScreen />} />
            <Route path="/review" element={<ReviewScreen />} />
            <Route path="/template" element={<TemplateScreen />} />
            <Route path="/export" element={<ExportScreen />} />
            <Route path="*" element={<Navigate to="/workspace" replace />} />
          </Routes>
        </div>
      </div>
    </div>
  );
}
