import { useEffect, useState } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./api";
import ChatPanel from "./components/ChatPanel";
import { Loading } from "./components/ui";
import AuditPage from "./pages/AuditPage";
import CandidateDetailPage from "./pages/CandidateDetailPage";
import IngestionPage from "./pages/IngestionPage";
import IntegrationsPage from "./pages/IntegrationsPage";
import JobEditorPage from "./pages/JobEditorPage";
import JobsPage from "./pages/JobsPage";
import LoginPage from "./pages/LoginPage";
import ResultsPage from "./pages/ResultsPage";
import ShortlistPage from "./pages/ShortlistPage";
import { useApp } from "./state";
import type { Job } from "./types";

function DemoBanner() {
  const { demoMode } = useApp();
  if (!demoMode) return null;
  return (
    <div className="demo-banner" role="note">
      <strong>DEMO MODE</strong> — extraction, scoring and rubric proposals use a deterministic <em>mock keyword
      matcher</em>, not AI. Email goes to a <em>mock outbox</em>. All candidates are synthetic.
    </div>
  );
}

function Sidebar() {
  const { user, logout, can, activeJobId, setActiveJobId, shortlist } = useApp();
  const [jobs, setJobs] = useState<Job[]>([]);
  const loc = useLocation();
  useEffect(() => {
    api<Job[]>("/jobs").then(setJobs).catch(() => setJobs([]));
  }, [loc.pathname]);
  const jobId = activeJobId && jobs.some((j) => j.id === activeJobId) ? activeJobId : jobs[0]?.id ?? null;
  const selectedCount = shortlist.jobId === jobId ? shortlist.selected.length : 0;

  return (
    <aside className="sidebar">
      <div className="brand">
        TalentMatch <span>AI</span>
      </div>
      <div className="tenant">{user?.tenant.name}</div>
      <label className="job-picker">
        <span>Active job</span>
        <select value={jobId ?? ""} onChange={(e) => setActiveJobId(e.target.value || null)}>
          {jobs.length === 0 && <option value="">No jobs yet</option>}
          {jobs.map((j) => (
            <option key={j.id} value={j.id}>
              {j.title}{j.external_ref ? ` (${j.external_ref})` : ""}
            </option>
          ))}
        </select>
      </label>
      <nav>
        <NavLink to="/jobs" end>Job openings</NavLink>
        {jobId && (
          <>
            <NavLink to={`/jobs/${jobId}`} end>Description &amp; rubric</NavLink>
            <NavLink to={`/jobs/${jobId}/ingestion`}>Resume ingestion</NavLink>
            <NavLink to={`/jobs/${jobId}/results`}>Candidate results</NavLink>
          </>
        )}
        {can("shortlist:send") && (
          <NavLink to="/shortlist">
            Shortlist &amp; email {selectedCount > 0 && <span className="pill">{selectedCount}</span>}
          </NavLink>
        )}
        {can("integrations:read") && <NavLink to="/integrations">Integrations &amp; settings</NavLink>}
        {can("audit:read") && <NavLink to="/audit">Audit history</NavLink>}
      </nav>
      <div className="whoami">
        <div>{user?.full_name}</div>
        <div className="muted">
          {user?.email} · {user?.role.replace("_", " ")}
        </div>
        <button className="link" onClick={logout}>Sign out</button>
      </div>
    </aside>
  );
}

export default function App() {
  const { user, loadingUser } = useApp();
  const loc = useLocation();
  if (loadingUser) return <Loading label="Checking session…" />;
  if (!user) {
    return (
      <>
        <DemoBanner />
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="*" element={<Navigate to="/login" replace state={{ from: loc.pathname }} />} />
        </Routes>
      </>
    );
  }
  return (
    <div className="layout">
      <Sidebar />
      <main>
        <DemoBanner />
        <div className="content">
          <Routes>
            <Route path="/" element={<Navigate to="/jobs" replace />} />
            <Route path="/login" element={<Navigate to="/jobs" replace />} />
            <Route path="/jobs" element={<JobsPage />} />
            <Route path="/jobs/:jobId" element={<JobEditorPage />} />
            <Route path="/jobs/:jobId/ingestion" element={<IngestionPage />} />
            <Route path="/jobs/:jobId/results" element={<ResultsPage />} />
            <Route path="/applications/:appId" element={<CandidateDetailPage />} />
            <Route path="/shortlist" element={<ShortlistPage />} />
            <Route path="/integrations" element={<IntegrationsPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="*" element={<div className="state">Page not found.</div>} />
          </Routes>
        </div>
      </main>
      <ChatPanel />
    </div>
  );
}
