import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, openAuthenticatedFile, qs } from "../api";
import { Badge, Empty, ErrorBox, Loading, MockTag, PageHeader, Score } from "../components/ui";
import { humanize, scoreBoundError } from "../format";
import { useApp } from "../state";
import type { CandidateRow, Job } from "../types";

const PAGE_SIZE = 10;

export default function ResultsPage() {
  const { jobId = "" } = useParams();
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const { setActiveJobId, shortlist, toggleSelected, setSelected, setRange, can } = useApp();

  const applied = {
    min: sp.get("min") ?? "",
    max: sp.get("max") ?? "",
    req: sp.get("req") ?? "",
    q: sp.get("q") ?? "",
    status: sp.get("status") ?? "",
    order: sp.get("order") === "asc" ? "asc" : "desc",
    page: Math.max(1, Number(sp.get("page") ?? 1) || 1),
  };
  const [minIn, setMinIn] = useState(applied.min);
  const [maxIn, setMaxIn] = useState(applied.max);
  const [reqIn, setReqIn] = useState(applied.req);
  const [qIn, setQIn] = useState(applied.q);
  const [statusIn, setStatusIn] = useState(applied.status);
  const [formErrors, setFormErrors] = useState<string[]>([]);

  const [job, setJob] = useState<Job | null>(null);
  const [data, setData] = useState<{ items: CandidateRow[]; total: number } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setActiveJobId(jobId);
    api<Job>(`/jobs/${jobId}`).then(setJob).catch(setError);
  }, [jobId, setActiveJobId]);

  // keep inputs in sync when the URL changes (e.g. chatbot "filter between 98 and 100")
  useEffect(() => {
    setMinIn(applied.min);
    setMaxIn(applied.max);
  }, [applied.min, applied.max]);

  const query = qs({
    min_score: applied.min, max_score: applied.max, required_status: applied.req, search: applied.q,
    status: applied.status, sort: "score", order: applied.order, page: applied.page, page_size: PAGE_SIZE,
  });
  useEffect(() => {
    setLoading(true);
    setError(null);
    api(`/jobs/${jobId}/candidates${query}`)
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [jobId, query]);

  function apply(e?: FormEvent) {
    e?.preventDefault();
    const errs = [scoreBoundError("Minimum score", minIn), scoreBoundError("Maximum score", maxIn)].filter(Boolean) as string[];
    if ((minIn === "") !== (maxIn === "")) errs.push("Enter both a minimum and a maximum score, or neither.");
    if (minIn !== "" && maxIn !== "" && Number(minIn) > Number(maxIn)) errs.push("Minimum score cannot be greater than maximum score.");
    setFormErrors(errs);
    if (errs.length) return;
    const next: Record<string, string> = {};
    if (minIn !== "") next.min = minIn.trim();
    if (maxIn !== "") next.max = maxIn.trim();
    if (reqIn) next.req = reqIn;
    if (qIn.trim()) next.q = qIn.trim();
    if (statusIn) next.status = statusIn;
    if (applied.order === "asc") next.order = "asc";
    setSp(next);
    setRange(jobId, next.min ?? "", next.max ?? "");
  }

  function clear() {
    setMinIn(""); setMaxIn(""); setReqIn(""); setQIn(""); setStatusIn(""); setFormErrors([]);
    setSp({});
    setRange(jobId, "", "");
  }

  function setParam(k: string, v: string | null) {
    const n = new URLSearchParams(sp);
    if (v === null) n.delete(k); else n.set(k, v);
    if (k !== "page") n.delete("page");
    setSp(n);
  }

  const selected = shortlist.jobId === jobId ? shortlist.selected : [];
  const pageIds = data?.items.map((i) => i.application_id) ?? [];
  const allOnPage = pageIds.length > 0 && pageIds.every((id) => selected.includes(id));
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const rangeActive = applied.min !== "" && applied.max !== "";
  const anyMock = data?.items.some((i) => i.is_mock);

  return (
    <>
      <PageHeader
        title="Candidate results"
        sub={job ? <>{job.title}{job.active_rubric ? ` · rubric v${job.active_rubric.version}` : " · no approved rubric yet"}</> : "…"}
        actions={
          <>
            <button className="btn" disabled={!data?.total}
              onClick={() => openAuthenticatedFile(`/jobs/${jobId}/candidates/export.csv${qs({ min_score: applied.min, max_score: applied.max, required_status: applied.req, search: applied.q, status: applied.status, order: applied.order })}`, "candidates.csv").catch(setError)}>
              Export CSV
            </button>
            {can("shortlist:send") && (
              <button className="btn primary" disabled={selected.length === 0} onClick={() => nav("/shortlist")}>
                Shortlist ({selected.length}) →
              </button>
            )}
          </>
        }
      />

      <form className="card filter-bar" onSubmit={apply}>
        <label>Min score<input inputMode="decimal" value={minIn} onChange={(e) => setMinIn(e.target.value)} placeholder="0" aria-label="Minimum score" /></label>
        <label>Max score<input inputMode="decimal" value={maxIn} onChange={(e) => setMaxIn(e.target.value)} placeholder="100" aria-label="Maximum score" /></label>
        <label>Required criteria
          <select value={reqIn} onChange={(e) => setReqIn(e.target.value)}>
            <option value="">Any</option>
            <option value="all_supported">All supported</option>
            <option value="needs_clarification">Needs clarification</option>
            <option value="not_supported">Not supported</option>
            <option value="none_required">None required</option>
          </select>
        </label>
        <label>Processing status
          <select value={statusIn} onChange={(e) => setStatusIn(e.target.value)}>
            <option value="">Any</option>
            {["scored", "awaiting_rubric", "needs_manual_review", "duplicate", "processing", "scoring", "received"].map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
          </select>
        </label>
        <label className="grow">Search<input value={qIn} onChange={(e) => setQIn(e.target.value)} placeholder="Name, email or file" /></label>
        <div className="filter-actions">
          <button className="btn primary" type="submit">Apply Filter</button>
          <button className="btn" type="button" onClick={clear}>Clear</button>
        </div>
        {formErrors.length > 0 && <ul className="bad-text small span-all">{formErrors.map((e) => <li key={e}>{e}</li>)}</ul>}
        <p className="muted small span-all">
          Range filters are inclusive and use the exact unrounded score; applications without a score (manual review, duplicates, awaiting rubric) are
          excluded from range filters but remain visible when no range is set. The score is a rubric alignment measure, not a hiring probability.
        </p>
      </form>

      {anyMock && <div className="state state-warn small"><MockTag /> Scores on this page come from the deterministic mock keyword matcher, not an AI evaluation.</div>}
      <ErrorBox error={error} />
      {loading && !data && <Loading />}
      {data && data.items.length === 0 && (
        <Empty title={rangeActive ? `No candidates scored between ${applied.min} and ${applied.max}` : "No applications match"}>
          {rangeActive ? "No scores were adjusted and no lower-scoring candidates were added." : "Upload resumes or change the filters."}
        </Empty>
      )}
      {data && data.items.length > 0 && (
        <>
          <div className="muted small">{data.total} result(s){rangeActive && ` in range ${applied.min}–${applied.max} (inclusive)`} · {selected.length} selected for shortlist</div>
          <table className="table results">
            <thead>
              <tr>
                <th><input type="checkbox" aria-label="Select all on page" checked={allOnPage}
                  onChange={() => setSelected(jobId, allOnPage ? selected.filter((s) => !pageIds.includes(s)) : [...new Set([...selected, ...pageIds])])} /></th>
                <th>Candidate</th>
                <th>Job</th>
                <th className="sortable" onClick={() => setParam("order", applied.order === "desc" ? "asc" : "desc")}>
                  Alignment score {applied.order === "desc" ? "▼" : "▲"}
                </th>
                <th>Required criteria</th>
                <th>Supported skills</th>
                <th>Missing / unclear evidence</th>
                <th>Status</th>
                <th>Resume</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((r) => (
                <tr key={r.application_id} className={selected.includes(r.application_id) ? "selected" : ""}>
                  <td><input type="checkbox" aria-label={`Shortlist ${r.candidate_name}`} checked={selected.includes(r.application_id)} onChange={() => toggleSelected(jobId, r.application_id)} /></td>
                  <td><Link to={`/applications/${r.application_id}`}><strong>{r.candidate_name}</strong></Link>
                    {r.flags.length > 0 && <div>{r.flags.map((f) => <Badge key={f} value="needs_clarification" label={humanize(f)} />)}</div>}
                  </td>
                  <td className="small">{r.job_title}</td>
                  <td><Score exact={r.score_exact} /> {r.is_mock && <MockTag />}</td>
                  <td><Badge value={r.required_status} /></td>
                  <td className="small">{r.supported_skills.join(", ") || "—"}</td>
                  <td className="small">{r.missing_or_unclear.slice(0, 4).join(", ") || "—"}{r.missing_or_unclear.length > 4 && ` +${r.missing_or_unclear.length - 4}`}</td>
                  <td><Badge value={r.status} /></td>
                  <td>{r.document_id && <button className="link" onClick={() => openAuthenticatedFile(`/documents/${r.document_id}/download`).catch(setError)}>Open</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="pagination">
            <button className="btn" disabled={applied.page <= 1} onClick={() => setParam("page", String(applied.page - 1))}>← Prev</button>
            <span>Page {applied.page} of {pages}</span>
            <button className="btn" disabled={applied.page >= pages} onClick={() => setParam("page", String(applied.page + 1))}>Next →</button>
          </div>
        </>
      )}
    </>
  );
}
