import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { Badge, Empty, ErrorBox, Loading, PageHeader } from "../components/ui";
import { useApp } from "../state";
import type { Job } from "../types";

export default function JobsPage() {
  const { can, setActiveJobId } = useApp();
  const nav = useNavigate();
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ title: "", department: "", location: "", external_ref: "", description: "" });
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<unknown>(null);

  useEffect(() => {
    api<Job[]>("/jobs").then(setJobs).catch(setError);
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setFormError(null);
    try {
      const job = await api<Job>("/jobs", { body: { ...form, external_ref: form.external_ref || null } });
      setActiveJobId(job.id);
      nav(`/jobs/${job.id}`);
    } catch (err) {
      setFormError(err);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Job openings"
        sub="Create or import a job, approve its evaluation rubric, then collect resumes."
        actions={can("jobs:write") && <button className="btn primary" onClick={() => setShowForm((s) => !s)}>{showForm ? "Cancel" : "New job opening"}</button>}
      />
      {showForm && (
        <form className="card form-grid" onSubmit={create}>
          <label>Title<input required minLength={2} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
          <label>Department<input value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })} /></label>
          <label>Location<input value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} /></label>
          <label>External requisition ID (for ATS mapping)<input value={form.external_ref} onChange={(e) => setForm({ ...form, external_ref: e.target.value })} /></label>
          <label className="span-2">
            Job description (paste; you can also upload a file on the next page)
            <textarea rows={10} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </label>
          <ErrorBox error={formError} />
          <div className="span-2"><button className="btn primary" disabled={saving}>{saving ? "Creating…" : "Create job"}</button></div>
        </form>
      )}
      <ErrorBox error={error} />
      {!jobs && !error && <Loading />}
      {jobs && jobs.length === 0 && <Empty title="No job openings yet">Create one to get started.</Empty>}
      {jobs && jobs.length > 0 && (
        <table className="table">
          <thead>
            <tr><th>Title</th><th>Status</th><th>Rubric</th><th>Applications</th><th>Ref</th><th /></tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id}>
                <td>
                  <Link to={`/jobs/${j.id}`} onClick={() => setActiveJobId(j.id)}><strong>{j.title}</strong></Link>
                  <div className="muted small">{[j.department, j.location].filter(Boolean).join(" · ")}</div>
                </td>
                <td><Badge value={j.status} /></td>
                <td>
                  {j.active_rubric ? <Badge value="approved" label={`v${j.active_rubric.version} approved`} /> : <Badge value="draft" label="not approved" />}
                  {j.description_changed_since_rubric && <div className="small warn-text">Description changed since approval</div>}
                </td>
                <td>{j.application_total}</td>
                <td className="muted">{j.external_ref ?? "—"}</td>
                <td className="right">
                  <Link className="btn" to={`/jobs/${j.id}/results`} onClick={() => setActiveJobId(j.id)}>Results</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
