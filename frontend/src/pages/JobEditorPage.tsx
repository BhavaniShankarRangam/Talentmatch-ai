import { ChangeEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { Badge, Empty, ErrorBox, Loading, MockTag, PageHeader } from "../components/ui";
import { formatDate } from "../format";
import { useApp } from "../state";
import type { Criterion, Job, Rubric } from "../types";

const CATEGORIES = ["skills", "experience", "responsibilities", "projects", "qualifications", "general", "other"];

function weightTotal(criteria: Criterion[]): number {
  // Sum in hundredths to avoid floating-point display artefacts.
  return criteria.reduce((s, c) => s + Math.round((Number(c.weight) || 0) * 100), 0) / 100;
}

export default function JobEditorPage() {
  const { jobId = "" } = useParams();
  const { can, setActiveJobId } = useApp();
  const [job, setJob] = useState<Job | null>(null);
  const [rubrics, setRubrics] = useState<Rubric[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [jdText, setJdText] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<Criterion[] | null>(null);
  const [draftError, setDraftError] = useState<unknown>(null);

  const reload = useCallback(async () => {
    try {
      const [j, r] = await Promise.all([api<Job>(`/jobs/${jobId}`), api<Rubric[]>(`/jobs/${jobId}/rubrics`)]);
      setJob(j);
      setJdText(j.description?.text ?? "");
      setRubrics(r);
      const d = r.find((x) => x.status === "draft");
      setDraft(d ? d.criteria.map((c) => ({ ...c })) : null);
    } catch (e) {
      setError(e);
    }
  }, [jobId]);

  useEffect(() => {
    setActiveJobId(jobId);
    reload();
  }, [jobId, reload, setActiveJobId]);

  const draftRubric = rubrics?.find((r) => r.status === "draft") ?? null;
  const approved = rubrics?.find((r) => r.status === "approved") ?? null;
  const editable = can("jobs:write");
  const total = useMemo(() => (draft ? weightTotal(draft) : 0), [draft]);

  /** Runs an action; if it resolves to a string, that string replaces the default success message. */
  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    setMsg(null);
    setDraftError(null);
    try {
      const result = await fn();
      setMsg(typeof result === "string" ? result : ok);
      await reload();
    } catch (e) {
      setDraftError(e);
    } finally {
      setBusy(false);
    }
  }

  const saveJd = () => run(() => api(`/jobs/${jobId}/description`, { method: "PUT", body: { text: jdText } }), "Saved as a new job description version.");
  const uploadJd = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const form = new FormData();
    form.append("file", f);
    e.target.value = "";
    run(() => api(`/jobs/${jobId}/description/upload`, { form }), `Imported "${f.name}" as a new description version.`);
  };
  const propose = () => run(() => api(`/jobs/${jobId}/rubrics/propose`, { method: "POST" }), "Proposed criteria created as a draft. Review before approving.");
  const saveDraft = () =>
    run(() => api(`/rubrics/${draftRubric!.id}`, { method: "PUT", body: { criteria: draft!.map((c) => ({ ...c, weight: Number(c.weight) })) } }), "Draft saved.");
  const approve = async () => {
    if (!window.confirm("Approve this rubric? It becomes immutable and all applications for this job will be (re)scored. Previous results are kept.")) return;
    await run(async () => {
      await api(`/rubrics/${draftRubric!.id}`, { method: "PUT", body: { criteria: draft!.map((c) => ({ ...c, weight: Number(c.weight) })) } });
      const r = await api(`/rubrics/${draftRubric!.id}/approve`, { method: "POST" });
      return `Rubric approved. ${r.rescoring_queued} existing application(s) queued for scoring.`;
    }, "Rubric approved.");
  };
  const newDraft = () => run(() => api(`/rubrics/${approved!.id}/new-draft`, { method: "POST" }), "New draft created from the approved rubric.");

  function update(i: number, patch: Partial<Criterion>) {
    setDraft((d) => d!.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  }

  if (error) return <ErrorBox error={error} />;
  if (!job || !rubrics) return <Loading />;

  return (
    <>
      <PageHeader
        title={job.title}
        sub={<>Job description and evaluation rubric · {job.external_ref ? `Ref ${job.external_ref}` : "no external ref"}</>}
        actions={<Link className="btn" to={`/jobs/${jobId}/ingestion`}>Upload resumes →</Link>}
      />
      {msg && <div className="state state-ok">{msg}</div>}
      <ErrorBox error={draftError} />

      <section className="card">
        <div className="card-head">
          <h2>Job description {job.description && <span className="muted small">v{job.description.version} · {formatDate(job.description.created_at)}</span>}</h2>
          {editable && (
            <div className="actions">
              <label className="btn">
                Upload PDF/DOCX/TXT
                <input type="file" accept=".pdf,.docx,.txt" hidden onChange={uploadJd} />
              </label>
              <button className="btn primary" onClick={saveJd} disabled={busy || !jdText.trim() || jdText === job.description?.text}>Save new version</button>
            </div>
          )}
        </div>
        <p className="muted small">Job descriptions are treated as untrusted content: they inform proposed criteria but never change system behavior.</p>
        <textarea className="mono" rows={14} value={jdText} onChange={(e) => setJdText(e.target.value)} readOnly={!editable} />
        {job.description_changed_since_rubric && (
          <div className="state state-warn">The description changed after the active rubric was approved. Propose or create a new draft rubric if criteria should change.</div>
        )}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Evaluation rubric</h2>
          {editable && (
            <div className="actions">
              {approved && !draftRubric && <button className="btn" onClick={newDraft} disabled={busy}>Edit as new version</button>}
              {!draftRubric && <button className="btn" onClick={propose} disabled={busy || !job.description}>Propose criteria from description</button>}
            </div>
          )}
        </div>
        <p className="muted small">
          Criteria must be reviewed and approved by a recruiter before scoring. Weights must total 100%. Each criterion's
          level (strong 100% · substantial 75% · partial 50% · limited 25% · none 0%) × weight gives its contribution; the total is a
          rubric alignment measure, <strong>not a hiring probability</strong>. Do not use protected characteristics, names, age, photos or school prestige.
        </p>

        {draftRubric && draft && (
          <div className="rubric-draft">
            <div className="row-between">
              <div>
                <Badge value="draft" label={`Draft v${draftRubric.version}`} /> <MockTag show={draftRubric.is_mock_proposal} />{" "}
                <span className="muted small">proposed by {draftRubric.proposed_by}</span>
              </div>
              <div className={`weight-total ${total === 100 ? "ok" : "bad"}`}>Total weight: {total}%</div>
            </div>
            {draftRubric.is_mock_proposal && (
              <div className="state state-warn small">These criteria were proposed by the <strong>mock</strong> provider (keyword vocabulary), not an AI model. Edit them as needed.</div>
            )}
            {draft.map((c, i) => (
              <div className="criterion-edit" key={i}>
                <div className="crit-grid">
                  <label className="span-2">Criterion<input value={c.name} onChange={(e) => update(i, { name: e.target.value })} disabled={!editable} /></label>
                  <label>Category
                    <select value={c.category} onChange={(e) => update(i, { category: e.target.value })} disabled={!editable}>
                      {CATEGORIES.map((x) => <option key={x}>{x}</option>)}
                    </select>
                  </label>
                  <label>Weight %<input type="number" min={0.01} max={100} step={0.01} value={c.weight} onChange={(e) => update(i, { weight: e.target.value as unknown as number })} disabled={!editable} /></label>
                  <label className="checkbox"><input type="checkbox" checked={c.required} onChange={(e) => update(i, { required: e.target.checked })} disabled={!editable} /> Required criterion</label>
                </div>
                <label>Description<textarea rows={2} value={c.description} onChange={(e) => update(i, { description: e.target.value })} disabled={!editable} /></label>
                <label>
                  Evidence terms (one per line; <code>Label: alt1|alt2</code>)
                  <textarea className="mono" rows={Math.max(2, c.evidence_terms.length)} value={c.evidence_terms.join("\n")}
                    onChange={(e) => update(i, { evidence_terms: e.target.value.split("\n") })} disabled={!editable} />
                </label>
                {editable && <button className="link danger" onClick={() => setDraft((d) => d!.filter((_, j) => j !== i))}>Remove criterion</button>}
              </div>
            ))}
            {editable && (
              <div className="actions">
                <button className="btn" onClick={() => setDraft((d) => [...d!, { name: "", category: "skills", description: "", weight: 0, required: false, evidence_terms: [] }])}>Add criterion</button>
                <button className="btn" onClick={saveDraft} disabled={busy}>Save draft</button>
                {can("rubric:approve") && <button className="btn primary" onClick={approve} disabled={busy || total !== 100}>Approve rubric</button>}
              </div>
            )}
            {draftRubric.validation_errors.length > 0 && (
              <div className="state state-warn small"><strong>Saved draft has issues:</strong><ul>{draftRubric.validation_errors.map((e) => <li key={e}>{e}</li>)}</ul></div>
            )}
          </div>
        )}

        {approved && (
          <div className="approved-rubric">
            <h3>Active: v{approved.version} <Badge value="approved" /> <MockTag show={approved.is_mock_proposal} /></h3>
            <div className="muted small">Approved {formatDate(approved.approved_at)} · scoring logic {approved.scoring_logic_version}</div>
            <table className="table compact">
              <thead><tr><th>Criterion</th><th>Category</th><th className="right">Weight</th><th>Required</th><th>Evidence terms</th></tr></thead>
              <tbody>
                {approved.criteria.map((c) => (
                  <tr key={c.id}>
                    <td>{c.name}</td><td>{c.category}</td><td className="right">{c.weight}%</td>
                    <td>{c.required ? "Yes" : "No"}</td>
                    <td className="small">{c.evidence_terms.map((t) => t.split(":")[0]).join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {!approved && !draftRubric && <Empty title="No rubric yet">Propose criteria from the job description, then review and approve them.</Empty>}

        {rubrics.length > 0 && (
          <details>
            <summary>Version history ({rubrics.length})</summary>
            <ul>
              {rubrics.map((r) => (
                <li key={r.id}>v{r.version} <Badge value={r.status} /> · {r.proposed_by} · created {formatDate(r.created_at)}{r.approved_at && ` · approved ${formatDate(r.approved_at)}`}</li>
              ))}
            </ul>
          </details>
        )}
      </section>
    </>
  );
}
