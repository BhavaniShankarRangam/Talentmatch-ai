import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, openAuthenticatedFile } from "../api";
import { Badge, ErrorBox, Loading, MockTag, PageHeader, Score } from "../components/ui";
import { formatDate, formatScore, humanize } from "../format";
import { useApp } from "../state";
import type { ApplicationDetail } from "../types";

export default function CandidateDetailPage() {
  const { appId = "" } = useParams();
  const nav = useNavigate();
  const { shortlist, toggleSelected, can } = useApp();
  const [d, setD] = useState<ApplicationDetail | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(() => api<ApplicationDetail>(`/applications/${appId}`).then(setD).catch(setError), [appId]);
  useEffect(() => {
    load();
  }, [load]);

  if (error) return <ErrorBox error={error} />;
  if (!d) return <Loading />;
  const ev = d.current_evaluation;
  const selected = shortlist.jobId === d.job.id && shortlist.selected.includes(d.application_id);

  async function reprocess() {
    await api(`/applications/${appId}/reprocess`, { method: "POST" }).catch(setError);
    load();
  }
  async function remove() {
    if (!window.confirm("Permanently delete this application, its resume and its evaluations? This cannot be undone.")) return;
    await api(`/applications/${appId}`, { method: "DELETE" }).catch(setError);
    nav(`/jobs/${d!.job.id}/results`);
  }

  return (
    <>
      <PageHeader
        title={d.candidate?.full_name ?? "(name not detected)"}
        sub={<><Link to={`/jobs/${d.job.id}/results`}>{d.job.title}</Link> · {humanize(d.source_system)}{d.external_application_id && ` · ${d.external_application_id}`} · submitted {formatDate(d.submitted_at)}</>}
        actions={
          <>
            {d.document && <button className="btn" onClick={() => openAuthenticatedFile(`/documents/${d.document!.id}/download`).catch(setError)}>Open resume</button>}
            {can("shortlist:send") && ev && (
              <button className={`btn ${selected ? "" : "primary"}`} onClick={() => toggleSelected(d.job.id, d.application_id)}>
                {selected ? "Remove from shortlist" : "Add to shortlist"}
              </button>
            )}
            {d.can_reprocess && <button className="btn" onClick={reprocess}>Reprocess</button>}
            {d.can_delete && <button className="btn danger" onClick={remove}>Delete data</button>}
          </>
        }
      />

      <div className="summary-grid">
        <div className="card stat">
          <div className="muted small">Alignment score (rubric v{ev?.rubric_version ?? "—"})</div>
          <div className="big"><Score exact={ev?.score_exact ?? null} /><span className="muted"> / 100</span> {ev?.is_mock && <MockTag />}</div>
          {ev && <div className="muted small">Exact: {ev.score_exact}</div>}
        </div>
        <div className="card stat">
          <div className="muted small">Required criteria</div>
          <div className="big"><Badge value={ev?.required_status} /></div>
        </div>
        <div className="card stat">
          <div className="muted small">Extraction confidence (separate from score)</div>
          <div className="big">{d.document?.extraction_confidence ?? "—"}</div>
          <div className="muted small">
            {d.document?.extracted_char_count ?? 0} characters ·{" "}
            {d.document?.page_count ? `${d.document.page_count} page(s)` : "DOCX (no page numbers; references use sections)"}
          </div>
        </div>
        <div className="card stat">
          <div className="muted small">Processing status</div>
          <div className="big"><Badge value={d.status} /></div>
          {d.status_detail && <div className="small">{d.status_detail}</div>}
        </div>
      </div>

      {ev?.is_mock && (
        <div className="state state-warn small">
          <MockTag /> This evaluation was produced by the deterministic <strong>mock keyword matcher</strong> ({String(ev.model_config.model)}). It is a demo, not an AI judgement.
        </div>
      )}
      {d.flag_details.length > 0 && (
        <section className="card warn-card">
          <h2>Flags for recruiter review</h2>
          <ul>
            {d.flag_details.map((f, i) => (
              <li key={i}>
                <strong>{humanize(f.type)}</strong>
                {f.pattern && <> ({f.pattern})</>} {f.page && <>· page {f.page}</>} {f.section && <>· {f.section}</>}
                {f.excerpt && <div className="mono small">“{f.excerpt}”</div>}
                {f.detail && <div className="small">{f.detail}</div>}
                {f.other_application_id && <Link to={`/applications/${f.other_application_id}`}>View other application</Link>}
              </li>
            ))}
          </ul>
          {d.flags.includes("prompt_injection_suspected") && (
            <p className="small">Text that looked like instructions to an AI system was excluded from assessment. It did not change the score. Review the original document.</p>
          )}
        </section>
      )}
      {d.duplicate_of_id && <div className="state state-warn">Duplicate of <Link to={`/applications/${d.duplicate_of_id}`}>an earlier application</Link>; not scored separately.</div>}
      {d.document && d.document.parse_status !== "parsed" && (
        <div className="state state-warn">
          <strong>Manual review needed.</strong> {d.document.parse_error ?? d.document.extraction_notes.join(" ")} No score was assigned, so this candidate is not penalized by a misleading low score.
        </div>
      )}

      {ev?.assessments && (
        <section className="card">
          <h2>Criterion breakdown</h2>
          <p className="muted small">
            Contribution = weight × level points. Missing evidence means it was <strong>not found in the resume text</strong>; it does not necessarily mean the
            candidate lacks the qualification. Evidence references come from the document itself.
          </p>
          <table className="table breakdown">
            <thead>
              <tr><th>Criterion</th><th className="right">Weight</th><th>Assessment</th><th>Evidence found (reference)</th><th>Missing / ambiguous</th><th className="right">Contribution</th></tr>
            </thead>
            <tbody>
              {ev.assessments.map((a) => (
                <tr key={a.criterion_id}>
                  <td><strong>{a.criterion_name}</strong><div className="muted small">{a.category}</div>
                    {a.required && <div><Badge value={a.required_status} label={`Required: ${humanize(a.required_status)}`} /></div>}
                  </td>
                  <td className="right">{a.weight}%</td>
                  <td><Badge value={a.level === "strong" || a.level === "substantial" ? "supported" : a.level === "none" ? "not_supported" : "needs_clarification"} label={a.level} />
                    <div className="muted small">{Math.round(a.level_points * 100)}% of weight</div></td>
                  <td className="small">
                    {a.evidence.length === 0 && <span className="muted">No evidence found</span>}
                    {a.evidence.map((e, i) => (
                      <div key={i} className="evidence">
                        <span className="mono">“{e.quote}”</span>
                        <div className="muted">{e.page ? `Page ${e.page}` : "DOCX"} · section: {e.section}{e.term && ` · supports: ${e.term}`}</div>
                      </div>
                    ))}
                  </td>
                  <td className="small">
                    {a.missing.length > 0 && <div>Not found: {a.missing.join(", ")}</div>}
                    {a.ambiguities.map((x, i) => <div key={i} className="warn-text">{x}</div>)}
                    {a.missing.length === 0 && a.ambiguities.length === 0 && "—"}
                  </td>
                  <td className="right"><strong>{formatScore(a.contribution_exact)}</strong></td>
                </tr>
              ))}
              <tr className="total-row"><td colSpan={5} className="right">Total</td><td className="right"><strong>{formatScore(ev.score_exact)}</strong></td></tr>
            </tbody>
          </table>
          <details><summary>Assessment rationale</summary>
            <ul className="small">{ev.assessments.map((a) => <li key={a.criterion_id}><strong>{a.criterion_name}:</strong> {a.rationale}</li>)}</ul>
          </details>
        </section>
      )}

      <section className="card">
        <h2>Evaluation history</h2>
        {d.evaluation_history.length === 0 ? <p className="muted">No evaluations yet.</p> : (
          <table className="table compact">
            <thead><tr><th>When</th><th>Rubric</th><th>Score</th><th>Required</th><th>Scoring logic</th><th>Model</th><th>Current</th></tr></thead>
            <tbody>
              {d.evaluation_history.map((e) => (
                <tr key={e.id}>
                  <td className="small">{formatDate(e.created_at)}</td><td>v{e.rubric_version}</td><td><Score exact={e.score_exact} /></td>
                  <td><Badge value={e.required_status} /></td><td className="small">{e.scoring_logic_version}</td>
                  <td className="small">{String(e.model_config.provider)}:{String(e.model_config.model)}</td><td>{e.is_current ? "Yes" : "No"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted small">Recruiters make all decisions. This system does not reject candidates or make hiring decisions.</p>
      </section>
    </>
  );
}
