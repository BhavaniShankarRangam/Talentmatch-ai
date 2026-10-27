import { FormEvent, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../state";

interface Msg {
  role: "user" | "assistant";
  text: string;
  mode?: string;
}

const SUGGESTIONS = [
  "Show applications for the AI Engineer opening",
  "Filter candidates between 98 and 100",
  "Explain why this candidate received this score",
  "Compare these two candidates",
  "Prepare an email with my selected shortlist",
];

export default function ChatPanel() {
  const { activeJobId, shortlist, setRange, setActiveJobId, setDraft } = useApp();
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();
  const loc = useLocation();
  const listRef = useRef<HTMLDivElement>(null);

  const appMatch = loc.pathname.match(/^\/applications\/([a-f0-9]+)/);
  const jobMatch = loc.pathname.match(/^\/jobs\/([a-f0-9]+)/);
  const jobId = jobMatch?.[1] ?? activeJobId;

  async function send(text: string) {
    if (!text.trim() || busy) return;
    setMsgs((m) => [...m, { role: "user", text }]);
    setInput("");
    setBusy(true);
    try {
      const r = await api("/chat", {
        body: {
          message: text,
          context: {
            job_id: jobId,
            application_id: appMatch?.[1] ?? null,
            selected_application_ids: shortlist.jobId === jobId ? shortlist.selected : [],
          },
        },
      });
      setMsgs((m) => [...m, { role: "assistant", text: r.reply, mode: r.mode }]);
      for (const a of r.actions ?? []) {
        if (a.type === "set_filter") {
          setActiveJobId(a.job_id);
          setRange(a.job_id, String(a.min_score), String(a.max_score));
          nav(`/jobs/${a.job_id}/results?min=${a.min_score}&max=${a.max_score}`);
        } else if (a.type === "prefill_email") {
          setDraft({ subject: a.subject, message: a.message });
        } else if (a.type === "navigate") {
          nav(a.to);
        }
      }
    } catch (e: any) {
      setMsgs((m) => [...m, { role: "assistant", text: `Error: ${e.message}` }]);
    } finally {
      setBusy(false);
      setTimeout(() => listRef.current?.scrollTo(0, listRef.current.scrollHeight), 0);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    send(input);
  }

  if (!open) {
    return (
      <button className="chat-fab" onClick={() => setOpen(true)} aria-label="Open recruiter assistant">
        Assistant
      </button>
    );
  }
  return (
    <section className="chat-panel" aria-label="Recruiter assistant">
      <header>
        <div>
          <strong>Recruiter assistant</strong>
          <div className="muted small">Demo: rule-based intent router over tenant-scoped tools (no LLM). Never sends email.</div>
        </div>
        <button className="link" onClick={() => setOpen(false)} aria-label="Close assistant">✕</button>
      </header>
      <div className="chat-messages" ref={listRef}>
        {msgs.length === 0 && (
          <div className="chat-suggestions">
            {SUGGESTIONS.map((s) => (
              <button key={s} className="chip" onClick={() => send(s)}>{s}</button>
            ))}
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`chat-msg ${m.role}`}>
            <pre>{m.text}</pre>
          </div>
        ))}
        {busy && <div className="chat-msg assistant muted">…</div>}
      </div>
      <form onSubmit={onSubmit} className="chat-input">
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask about candidates…" maxLength={2000} />
        <button className="btn primary" disabled={busy || !input.trim()}>Send</button>
      </form>
    </section>
  );
}
