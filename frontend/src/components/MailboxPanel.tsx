import { ChangeEvent, FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../state";
import type { Job } from "../types";
import { formatDate, humanize } from "../format";
import { Badge, ErrorBox } from "./ui";

interface MailMsg {
  id: string;
  source: string;
  sender_email: string | null;
  subject: string;
  received_at: string | null;
  outcome: string;
  detail: string | null;
  job_id: string | null;
  application_ids: string[];
  filename?: string;
}
interface ImapStatus {
  configured: boolean;
  enabled: boolean;
  status: string;
  settings: { host?: string; port?: number; username?: string; folder?: string; since_days?: number };
  last_sync_at: string | null;
  last_result: Record<string, unknown>;
  password_configured_on_server: boolean;
  tested_against_real_mailbox: boolean;
}

const OUTCOME_TONE: Record<string, string> = {
  imported: "approved",
  duplicate_message: "superseded",
  no_resume_attachment: "needs_clarification",
  unmapped_job: "needs_clarification",
  rejected_file: "failed",
  rejected_message: "failed",
};

export default function MailboxPanel() {
  const { can } = useApp();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobId, setJobId] = useState("");
  const [messages, setMessages] = useState<MailMsg[]>([]);
  const [imap, setImap] = useState<ImapStatus | null>(null);
  const [form, setForm] = useState({ enabled: false, host: "", port: 993, username: "", folder: "INBOX", since_days: 30 });
  const [results, setResults] = useState<MailMsg[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api<MailMsg[]>("/integrations/mailbox/messages").then(setMessages).catch(setError);
    api<ImapStatus>("/integrations/imap").then((s) => {
      setImap(s);
      if (s.configured) setForm({ enabled: s.enabled, host: s.settings.host ?? "", port: s.settings.port ?? 993, username: s.settings.username ?? "", folder: s.settings.folder ?? "INBOX", since_days: s.settings.since_days ?? 30 });
    }).catch(setError);
  }, []);
  useEffect(() => {
    api<Job[]>("/jobs").then(setJobs).catch(() => {});
    load();
  }, [load]);

  async function importEml(e: ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files?.length) return;
    const fd = new FormData();
    Array.from(files).forEach((f) => fd.append("files", f));
    if (jobId) fd.append("job_id", jobId);
    e.target.value = "";
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ results: MailMsg[] }>("/integrations/mailbox/import-eml", { form: fd });
      setResults(r.results);
      load();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function saveImap(e: FormEvent) {
    e.preventDefault();
    setMsg(null);
    try {
      setImap(await api<ImapStatus>("/integrations/imap", { method: "PUT", body: { ...form, port: Number(form.port), since_days: Number(form.since_days) } }));
      setMsg("Mailbox settings saved.");
    } catch (err) {
      setError(err);
    }
  }

  async function syncImap() {
    setMsg(null);
    try {
      await api("/integrations/imap/sync", { method: "POST" });
      setMsg("Mailbox sync queued. Refresh in a few seconds to see results.");
      setTimeout(load, 3000);
    } catch (err) {
      setError(err);
    }
  }

  const jobTitle = (id: string | null) => {
    const j = jobs.find((x) => x.id === id);
    return j ? `${j.title}${j.external_ref ? ` (${j.external_ref})` : ""}` : "—";
  };
  const admin = can("settings:write");

  return (
    <section className="card">
      <h2>Recruitment mailbox</h2>
      <p className="muted small">
        For employers whose careers page asks applicants to email a resume. Only PDF/DOCX attachments are scored; the subject is used
        only to route the email to a job (requisition reference such as <code>REQ-1001</code>, or an exact unique job title). Email
        bodies are never scored. Sender addresses are not authenticated.
      </p>
      {msg && <div className="state state-ok small">{msg}</div>}
      <ErrorBox error={error} />

      {can("applications:upload") && (
        <div className="mailbox-import">
          <h3>Import exported emails (.eml)</h3>
          <div className="actions">
            <label>
              Assign to job (optional; otherwise routed by subject)
              <select value={jobId} onChange={(e) => setJobId(e.target.value)}>
                <option value="">Route by subject</option>
                {jobs.map((j) => <option key={j.id} value={j.id}>{j.title}{j.external_ref ? ` (${j.external_ref})` : ""}</option>)}
              </select>
            </label>
            <label className="btn primary">
              {busy ? "Importing…" : "Choose .eml files"}
              <input type="file" accept=".eml,message/rfc822" multiple hidden disabled={busy} onChange={importEml} />
            </label>
          </div>
          {results && (
            <ul className="upload-results">
              {results.map((r, i) => (
                <li key={i}>{r.filename}: <Badge value={OUTCOME_TONE[r.outcome] ?? "superseded"} label={humanize(r.outcome)} /> {r.detail}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <h3>Read-only IMAP sync</h3>
      <div className="state state-warn small">
        Implemented and tested against a simulated IMAP server only. It has <strong>not</strong> been tested against a real mailbox.
        It needs written authorization from the mailbox owner, IMAP enabled on the account, and an app password set on the server as
        <code> MAILBOX_IMAP_PASSWORD</code> (never entered here). Messages are opened read-only and are not marked as read.
      </div>
      {imap && (
        <div className="muted small">
          Status: <Badge value={imap.enabled ? "approved" : "draft"} label={humanize(imap.status)} /> · server secret{" "}
          {imap.password_configured_on_server ? "configured" : "not configured"} · last sync {formatDate(imap.last_sync_at)}
          {Object.keys(imap.last_result ?? {}).length > 0 && <> · {JSON.stringify(imap.last_result)}</>}
        </div>
      )}
      {admin ? (
        <form className="form-grid top-gap" onSubmit={saveImap}>
          <label>IMAP host<input value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} placeholder="imap.gmail.com or imap.titan.email" /></label>
          <label>Port<input type="number" value={form.port} onChange={(e) => setForm({ ...form, port: Number(e.target.value) })} /></label>
          <label>Mailbox username<input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} placeholder="careers@yourcompany.com" /></label>
          <label>Folder<input value={form.folder} onChange={(e) => setForm({ ...form, folder: e.target.value })} /></label>
          <label>Look back (days)<input type="number" min={1} max={365} value={form.since_days} onChange={(e) => setForm({ ...form, since_days: Number(e.target.value) })} /></label>
          <label className="checkbox"><input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} /> Enabled</label>
          <div className="actions span-2">
            <button className="btn">Save mailbox settings</button>
            <button type="button" className="btn primary" onClick={syncImap} disabled={!imap?.enabled || !imap?.password_configured_on_server}>Sync mailbox now</button>
          </div>
        </form>
      ) : (
        imap?.enabled && can("integrations:sync") && <button className="btn top-gap" onClick={syncImap}>Sync mailbox now</button>
      )}

      <h3>Processed messages ({messages.length})</h3>
      {messages.length === 0 ? <p className="muted">No mailbox messages processed yet.</p> : (
        <table className="table compact">
          <thead><tr><th>Received</th><th>Sender</th><th>Subject</th><th>Source</th><th>Outcome</th><th>Job</th><th>Details</th></tr></thead>
          <tbody>
            {messages.map((m) => (
              <tr key={m.id}>
                <td className="small">{formatDate(m.received_at)}</td>
                <td className="small">{m.sender_email ?? "—"}</td>
                <td className="small">{m.subject}</td>
                <td className="small">{humanize(m.source)}</td>
                <td><Badge value={OUTCOME_TONE[m.outcome] ?? "superseded"} label={humanize(m.outcome)} /></td>
                <td className="small">{jobTitle(m.job_id)}</td>
                <td className="small">
                  {m.detail}
                  {m.application_ids.map((a) => <div key={a}><Link to={`/applications/${a}`}>View application</Link></div>)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
