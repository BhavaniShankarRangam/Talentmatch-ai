import { ReactNode } from "react";
import { ApiError } from "../api";
import { formatScore, humanize } from "../format";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="state state-loading" role="status">
      <span className="spinner" aria-hidden /> {label}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state state-empty">
      <strong>{title}</strong>
      {children && <div className="muted">{children}</div>}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const e = error as ApiError;
  return (
    <div className="state state-error" role="alert">
      <strong>{e.message ?? "Something went wrong"}</strong>
      {e.errors?.length > 0 && (
        <ul>
          {e.errors.map((x) => (
            <li key={x}>{x}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

const STATUS_TONE: Record<string, string> = {
  scored: "ok",
  all_supported: "ok",
  supported: "ok",
  accepted: "ok",
  approved: "ok",
  needs_clarification: "warn",
  awaiting_rubric: "info",
  draft: "info",
  processing: "info",
  scoring: "info",
  received: "info",
  queued: "info",
  sending: "info",
  running: "info",
  needs_manual_review: "warn",
  duplicate: "muted",
  superseded: "muted",
  none_required: "muted",
  not_supported: "bad",
  failed: "bad",
};

export function Badge({ value, label }: { value: string | null | undefined; label?: string }) {
  if (!value) return <span className="muted">—</span>;
  return <span className={`badge tone-${STATUS_TONE[value] ?? "muted"}`}>{label ?? humanize(value)}</span>;
}

export function Score({ exact }: { exact: string | null }) {
  return (
    <span className="score" title={exact ? `Exact stored score: ${exact}` : "Not scored"}>
      {formatScore(exact)}
    </span>
  );
}

export function MockTag({ show = true }: { show?: boolean | null }) {
  if (!show) return null;
  return (
    <span className="badge tone-mock" title="Produced by deterministic mock keyword matching, not by an AI model">
      MOCK
    </span>
  );
}

export function PageHeader({ title, sub, actions }: { title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {sub && <div className="muted">{sub}</div>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </div>
  );
}
