import { useEffect, useState } from "react";
import { api, qs } from "../api";
import { Empty, ErrorBox, Loading, PageHeader } from "../components/ui";
import { formatDate } from "../format";

interface AuditRow {
  id: string;
  created_at: string;
  actor_email: string | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  details: Record<string, unknown>;
}

const PAGE_SIZE = 50;

export default function AuditPage() {
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const [data, setData] = useState<{ total: number; items: AuditRow[] } | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    setData(null);
    api(`/audit${qs({ page, page_size: PAGE_SIZE, action })}`).then(setData).catch(setError);
  }, [page, action]);

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  return (
    <>
      <PageHeader title="Audit history" sub="Who did what and when. Entries never contain resume text or credentials." />
      <div className="card filter-bar">
        <label>Action
          <select value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }}>
            <option value="">All</option>
            {["auth", "job", "rubric", "application", "document", "candidates", "shortlist", "integration", "settings", "retention", "chat"].map((a) => (
              <option key={a} value={a}>{a}.*</option>
            ))}
          </select>
        </label>
      </div>
      <ErrorBox error={error} />
      {!data && !error && <Loading />}
      {data && data.items.length === 0 && <Empty title="No audit entries" />}
      {data && data.items.length > 0 && (
        <>
          <table className="table compact">
            <thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Entity</th><th>Details</th></tr></thead>
            <tbody>
              {data.items.map((r) => (
                <tr key={r.id}>
                  <td className="small">{formatDate(r.created_at)}</td>
                  <td className="small">{r.actor_email}</td>
                  <td><code>{r.action}</code></td>
                  <td className="small">{r.entity_type} {r.entity_id?.slice(0, 8)}</td>
                  <td className="small mono">{JSON.stringify(r.details)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="pagination">
            <button className="btn" disabled={page <= 1} onClick={() => setPage(page - 1)}>← Prev</button>
            <span>Page {page} of {pages} · {data.total} entries</span>
            <button className="btn" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next →</button>
          </div>
        </>
      )}
    </>
  );
}
