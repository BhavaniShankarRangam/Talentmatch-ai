import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Badge, Empty, ErrorBox, MockTag, PageHeader, Score } from "../components/ui";
import { formatDate } from "../format";
import { useApp } from "../state";
import type { EmailSend, Job, Preview } from "../types";

interface OutboxMsg {
  id: string;
  email_send_id: string;
  from: string;
  to: string[];
  cc: string[];
  subject: string;
  body: string;
  attachments: string[];
  created_at: string;
}

function newKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export default function ShortlistPage() {
  const { shortlist, setSelected, setDraft } = useApp();
  const jobId = shortlist.jobId;
  const [job, setJob] = useState<Job | null>(null);
  const [to, setTo] = useState("");
  const [cc, setCc] = useState("");
  const [subject, setSubject] = useState(shortlist.draft.subject ?? "Candidate shortlist for review");
  const [message, setMessage] = useState(shortlist.draft.message ?? "Hello,\n\nPlease review the following shortlisted candidates.\n\nThanks,");
  const [attach, setAttach] = useState(false);
  const [confirmExternal, setConfirmExternal] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewError, setPreviewError] = useState<unknown>(null);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<unknown>(null);
  const [lastSend, setLastSend] = useState<EmailSend | null>(null);
  const [sends, setSends] = useState<EmailSend[]>([]);
  const [outbox, setOutbox] = useState<OutboxMsg[]>([]);
  const idemKey = useRef<string>(newKey());

  const loadHistory = useCallback(() => {
    api<EmailSend[]>("/shortlists/sends").then(setSends).catch(() => {});
    api<OutboxMsg[]>("/outbox").then(setOutbox).catch(() => {});
  }, []);

  useEffect(() => {
    if (jobId) api<Job>(`/jobs/${jobId}`).then(setJob).catch(() => setJob(null));
    loadHistory();
  }, [jobId, loadHistory]);

  // Any edit invalidates the preview and starts a new idempotency key: a changed email is a new send.
  useEffect(() => {
    setPreview(null);
    setConfirmExternal(false);
    idemKey.current = newKey();
  }, [to, cc, subject, message, attach, shortlist.selected]);

  useEffect(() => setDraft({ subject, message }), [subject, message, setDraft]);

  const body = () => ({
    job_id: jobId,
    application_ids: shortlist.selected,
    to,
    cc,
    subject,
    message,
    include_attachments: attach,
    score_min: shortlist.minScore === "" ? null : Number(shortlist.minScore),
    score_max: shortlist.maxScore === "" ? null : Number(shortlist.maxScore),
    confirm_external_recipients: confirmExternal,
  });

  async function doPreview() {
    setPreviewError(null);
    setSendError(null);
    setLastSend(null);
    try {
      setPreview(await api<Preview>("/shortlists/preview", { body: body() }));
    } catch (e) {
      setPreviewError(e);
    }
  }

  async function pollSend(id: string) {
    for (let i = 0; i < 20; i++) {
      const s = await api<EmailSend>(`/shortlists/sends/${id}`);
      setLastSend(s);
      if (s.status === "accepted" || s.status === "failed") break;
      await new Promise((r) => setTimeout(r, 1000));
    }
    loadHistory();
  }

  async function doSend() {
    if (!preview?.valid || sending) return;
    setSending(true); // blocks double-clicks; the idempotency key blocks retries/duplicates server-side
    setSendError(null);
    try {
      const r = await api<{ send: EmailSend; duplicate_request: boolean }>("/shortlists/send", {
        body: body(),
        headers: { "Idempotency-Key": idemKey.current },
      });
      setLastSend(r.send);
      await pollSend(r.send.id);
    } catch (e) {
      setSendError(e);
    } finally {
      setSending(false);
    }
  }

  const canSend = Boolean(preview?.valid) && (!preview?.requires_external_confirmation || confirmExternal) && !sending &&
    !(lastSend && lastSend.status !== "failed");

  return (
    <>
      <PageHeader title="Shortlist & email" sub="Review the selected candidates, preview the email, then send it yourself." />
      {!jobId || shortlist.selected.length === 0 ? (
        <Empty title="No candidates selected">
          Select candidates with the checkboxes on the <Link to={jobId ? `/jobs/${jobId}/results` : "/jobs"}>candidate results</Link> page.
        </Empty>
      ) : (
        <div className="two-col">
          <section className="card">
            <h2>Compose</h2>
            <div className="muted small">
              Job: <strong>{job?.title ?? "…"}</strong> · {shortlist.selected.length} candidate(s) selected ·
              Active score range: {shortlist.minScore !== "" ? `${shortlist.minScore} – ${shortlist.maxScore} (inclusive)` : "none"}
              {" · "}<button className="link" onClick={() => setSelected(jobId, [])}>Clear selection</button>
            </div>
            <label>To (one or more, separated by commas)<input value={to} onChange={(e) => setTo(e.target.value)} placeholder="hiring.lead@acme.example" /></label>
            <label>CC (optional)<input value={cc} onChange={(e) => setCc(e.target.value)} /></label>
            <label>Subject<input value={subject} maxLength={300} onChange={(e) => setSubject(e.target.value)} /></label>
            <label>Message<textarea rows={6} value={message} onChange={(e) => setMessage(e.target.value)} /></label>
            <label className="checkbox">
              <input type="checkbox" checked={attach} onChange={(e) => setAttach(e.target.checked)} />
              Attach resumes (only if your organization allows it; default is secure sign-in links)
            </label>
            <div className="actions"><button className="btn primary" onClick={doPreview}>Preview email</button></div>
            <ErrorBox error={previewError} />
          </section>

          <section className="card">
            <h2>Preview</h2>
            {!preview && <p className="muted">Click “Preview email” to review exactly what will be sent.</p>}
            {preview && (
              <>
                {preview.errors.length > 0 && (
                  <div className="state state-error"><strong>Fix before sending:</strong><ul>{preview.errors.map((e) => <li key={e}>{e}</li>)}</ul></div>
                )}
                {preview.warnings.length > 0 && (
                  <div className="state state-warn"><ul>{preview.warnings.map((w) => <li key={w}>{w}</li>)}</ul></div>
                )}
                <dl className="kv">
                  <dt>To</dt><dd>{preview.to.join(", ") || "—"}</dd>
                  <dt>CC</dt><dd>{preview.cc.join(", ") || "—"}</dd>
                  <dt>Job</dt><dd>{preview.job.title}</dd>
                  <dt>Score range</dt><dd>{preview.score_range.min !== null ? `${preview.score_range.min} – ${preview.score_range.max}` : "none"}</dd>
                  <dt>Candidates</dt><dd>{preview.candidate_count}</dd>
                  <dt>Delivery</dt><dd>{preview.delivery_mode === "attachments" ? "Resume attachments" : "Secure application links (sign-in required)"}</dd>
                </dl>
                <table className="table compact">
                  <thead><tr><th>Candidate</th><th>Score</th><th>Required</th><th>Link / attachment</th></tr></thead>
                  <tbody>
                    {preview.candidates.map((c) => (
                      <tr key={c.application_id}>
                        <td>{c.candidate_name}<div className="muted small">{c.supported_skills.join(", ")}</div></td>
                        <td><Score exact={c.score_exact} /> {c.is_mock && <MockTag />}</td>
                        <td><Badge value={c.required_status} /></td>
                        <td className="small">{c.attachment ?? c.link}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <details open><summary>Rendered email body</summary><pre className="email-body">{preview.rendered_text}</pre></details>
                {preview.requires_external_confirmation && (
                  <label className="checkbox warn-text">
                    <input type="checkbox" checked={confirmExternal} onChange={(e) => setConfirmExternal(e.target.checked)} />
                    I confirm sending candidate data to recipients outside our organization: {preview.external_recipients.join(", ")}
                  </label>
                )}
                <div className="actions">
                  <button className="btn primary" disabled={!canSend} onClick={doSend}>{sending ? "Sending…" : "Send Shortlist"}</button>
                </div>
              </>
            )}
            <ErrorBox error={sendError} />
            {lastSend && (
              <div className={`state ${lastSend.status === "failed" ? "state-error" : "state-ok"}`}>
                Send status: <Badge value={lastSend.status} /> · delivery: {lastSend.delivery_status}
                {lastSend.status_note && <div className="small">{lastSend.status_note}</div>}
                {lastSend.failure_detail && <div className="small">{lastSend.failure_detail}</div>}
              </div>
            )}
          </section>
        </div>
      )}

      <section className="card">
        <h2>Send history</h2>
        {sends.length === 0 ? <p className="muted">No shortlist emails sent yet.</p> : (
          <table className="table compact">
            <thead><tr><th>Requested</th><th>Sender</th><th>Recipients</th><th>Candidates</th><th>Status</th><th>Delivery</th><th>Provider</th></tr></thead>
            <tbody>
              {sends.map((s) => (
                <tr key={s.id}>
                  <td className="small">{formatDate(s.created_at)}</td><td className="small">{s.sender_email}</td>
                  <td className="small">{[...s.to, ...s.cc].join(", ")}{s.external_recipients.length > 0 && <div className="warn-text">external: {s.external_recipients.join(", ")}</div>}</td>
                  <td>{s.application_ids.length}</td><td><Badge value={s.status} /></td>
                  <td className="small">{s.delivery_status === "unknown" ? "not confirmed" : s.delivery_status}</td>
                  <td className="small">{s.provider}{s.failure_detail && <div className="bad-text">{s.failure_detail}</div>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <h2>Mock outbox <MockTag /></h2>
        <p className="muted small">Milestone 1 does not send real email. Messages “sent” here are stored in the demo outbox only.</p>
        {outbox.length === 0 ? <p className="muted">Outbox is empty.</p> : outbox.map((m) => (
          <details key={m.id} className="outbox-msg">
            <summary>{formatDate(m.created_at)} — <strong>{m.subject}</strong> → {m.to.join(", ")}</summary>
            <div className="small muted">From {m.from}{m.cc.length > 0 && ` · CC ${m.cc.join(", ")}`}{m.attachments.length > 0 && ` · Attachments: ${m.attachments.join(", ")}`}</div>
            <pre className="email-body">{m.body}</pre>
          </details>
        ))}
      </section>
    </>
  );
}
