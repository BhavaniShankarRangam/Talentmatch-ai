import { ChangeEvent, DragEvent, useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { Badge, Empty, ErrorBox, Loading, PageHeader } from "../components/ui";
import { formatDate, humanize } from "../format";
import { useApp } from "../state";

interface IngestRow {
  application_id: string;
  candidate_name: string | null;
  filename: string | null;
  source_system: string;
  external_application_id: string | null;
  submitted_at: string;
  status: string;
  status_detail: string | null;
  parse_status: string | null;
  extraction_confidence: string | null;
  page_count: number | null;
  duplicate_of_id: string | null;
  flags: string[];
}
interface ConnectorTask {
  id: string;
  status: string;
  attempts: number;
  max_attempts: number;
  record_id: string;
  source: string;
  last_error: string | null;
  updated_at: string;
}
interface UploadResult {
  filename: string;
  accepted: boolean;
  error?: string;
  duplicate?: boolean;
  status?: string;
}

const ACTIVE = new Set(["received", "processing", "scoring"]);

export default function IngestionPage() {
  const { jobId = "" } = useParams();
  const { can, setActiveJobId } = useApp();
  const [data, setData] = useState<{ applications: IngestRow[]; connector_tasks: ConnectorTask[] } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [uploading, setUploading] = useState(false);
  const [results, setResults] = useState<UploadResult[] | null>(null);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);

  const load = useCallback(() => api(`/jobs/${jobId}/ingestion`).then(setData).catch(setError), [jobId]);
  useEffect(() => {
    setActiveJobId(jobId);
    load();
  }, [jobId, load, setActiveJobId]);

  const busy = data?.applications.some((a) => ACTIVE.has(a.status)) || data?.connector_tasks.some((t) => t.status === "queued" || t.status === "running");
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(load, 1500);
    return () => clearInterval(t);
  }, [busy, load]);

  async function uploadFiles(files: FileList | File[]) {
    const list = Array.from(files);
    if (!list.length) return;
    const form = new FormData();
    list.forEach((f) => form.append("files", f));
    setUploading(true);
    setResults(null);
    setError(null);
    try {
      const r = await api<{ results: UploadResult[] }>(`/jobs/${jobId}/applications/upload`, { form });
      setResults(r.results);
      await load();
    } catch (e) {
      setError(e);
    } finally {
      setUploading(false);
    }
  }

  async function syncAts() {
    setSyncMsg(null);
    try {
      const r = await api("/integrations/mock-ats/sync", { method: "POST" });
      setSyncMsg(`Mock ATS: ${r.records_found} record(s) found, ${r.queued} queued, ${r.skipped_existing} already imported.`);
      await load();
    } catch (e: any) {
      setSyncMsg(`Sync failed: ${e.message}`);
    }
  }

  async function reprocess(id: string) {
    try {
      await api(`/applications/${id}/reprocess`, { method: "POST" });
      await load();
    } catch (e) {
      setError(e);
    }
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    uploadFiles(e.dataTransfer.files);
  };

  return (
    <>
      <PageHeader title="Resume ingestion & processing" sub="Upload resumes for this job, or pull them from a connected source."
        actions={<Link className="btn" to={`/jobs/${jobId}/results`}>Candidate results →</Link>} />

      {can("applications:upload") && (
        <section className="card">
          <div
            className={`dropzone ${drag ? "drag" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={onDrop}
          >
            <p><strong>Drop PDF or DOCX resumes here</strong> or</p>
            <label className="btn primary">
              {uploading ? "Uploading…" : "Choose files"}
              <input type="file" multiple accept=".pdf,.docx" hidden disabled={uploading}
                onChange={(e: ChangeEvent<HTMLInputElement>) => { if (e.target.files) uploadFiles(e.target.files); e.target.value = ""; }} />
            </label>
            <p className="muted small">Max 10 MB per file, up to 50 files per upload. Synthetic demo resumes: <code>backend/demo_data/resumes</code>.</p>
          </div>
          {results && (
            <ul className="upload-results">
              {results.map((r, i) => (
                <li key={i} className={r.accepted ? "" : "bad-text"}>
                  {r.filename}: {r.accepted ? (r.duplicate ? "accepted — identical file already submitted (marked duplicate)" : "accepted, queued for processing") : `rejected — ${r.error}`}
                </li>
              ))}
            </ul>
          )}
          {can("integrations:sync") && (
            <div className="row-between top-gap">
              <span className="muted small">Mock ATS connector (demo fixtures; one record fails once and is retried, one is permanently missing its file).</span>
              <button className="btn" onClick={syncAts}>Sync mock ATS</button>
            </div>
          )}
          {syncMsg && <div className="state state-ok small">{syncMsg}</div>}
        </section>
      )}

      <ErrorBox error={error} />
      {!data && !error && <Loading />}
      {data && data.connector_tasks.length > 0 && (
        <section className="card">
          <h2>Connector ingestion tasks</h2>
          <table className="table compact">
            <thead><tr><th>Source</th><th>Record</th><th>Status</th><th>Attempts</th><th>Last error</th><th>Updated</th></tr></thead>
            <tbody>
              {data.connector_tasks.map((t) => (
                <tr key={t.id}><td>{t.source}</td><td>{t.record_id}</td><td><Badge value={t.status} /></td>
                  <td>{t.attempts}/{t.max_attempts}</td><td className="small">{t.last_error ?? "—"}</td><td className="small">{formatDate(t.updated_at)}</td></tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      {data && data.applications.length === 0 && <Empty title="No resumes yet">Upload resumes above to start processing.</Empty>}
      {data && data.applications.length > 0 && (
        <table className="table">
          <thead>
            <tr><th>Candidate / file</th><th>Source</th><th>Submitted</th><th>Status</th><th>Parsing</th><th>Extraction confidence</th><th>Details</th><th /></tr>
          </thead>
          <tbody>
            {data.applications.map((a) => (
              <tr key={a.application_id}>
                <td>
                  <Link to={`/applications/${a.application_id}`}>{a.candidate_name ?? "(name not detected)"}</Link>
                  <div className="muted small">{a.filename}</div>
                </td>
                <td className="small">{humanize(a.source_system)}{a.external_application_id && <div className="muted">{a.external_application_id}</div>}</td>
                <td className="small">{formatDate(a.submitted_at)}</td>
                <td><Badge value={a.status} /></td>
                <td><Badge value={a.parse_status} />{a.page_count ? <span className="muted small"> {a.page_count}p</span> : null}</td>
                <td>{a.extraction_confidence ?? "—"}</td>
                <td className="small">
                  {a.status_detail}
                  {a.flags.map((f) => <div key={f}><Badge value="needs_clarification" label={humanize(f)} /></div>)}
                  {a.duplicate_of_id && <div><Link to={`/applications/${a.duplicate_of_id}`}>View original</Link></div>}
                </td>
                <td>
                  {can("applications:reprocess") && (a.status === "needs_manual_review") && (
                    <button className="btn small" onClick={() => reprocess(a.application_id)}>Retry</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
