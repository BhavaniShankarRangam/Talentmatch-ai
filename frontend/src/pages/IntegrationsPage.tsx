import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import MailboxPanel from "../components/MailboxPanel";
import { Badge, ErrorBox, Loading, MockTag, PageHeader } from "../components/ui";
import { formatDate, humanize } from "../format";
import { useApp } from "../state";

interface Integration {
  kind: string;
  name: string;
  implemented: boolean;
  is_mock: boolean;
  enabled: boolean;
  status: string;
  needs?: string;
  last_sync_at: string | null;
  last_result: Record<string, number>;
}
interface TenantSettings {
  name: string;
  allowed_email_domains: string[];
  allow_resume_attachments: boolean;
  retention_days: number;
}

export default function IntegrationsPage() {
  const { can } = useApp();
  const [data, setData] = useState<{ integrations: Integration[]; runtime: Record<string, unknown> } | null>(null);
  const [settings, setSettings] = useState<TenantSettings | null>(null);
  const [domains, setDomains] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = () => {
    api("/integrations").then(setData).catch(setError);
    api<TenantSettings>("/settings/tenant").then((s) => {
      setSettings(s);
      setDomains(s.allowed_email_domains.join(", "));
    }).catch(setError);
  };
  useEffect(load, []);

  async function save(e: FormEvent) {
    e.preventDefault();
    setMsg(null);
    try {
      const s = await api<TenantSettings>("/settings/tenant", {
        method: "PUT",
        body: { allowed_email_domains: domains.split(/[,\s]+/).filter(Boolean), allow_resume_attachments: settings!.allow_resume_attachments, retention_days: Number(settings!.retention_days) },
      });
      setSettings(s);
      setMsg("Settings saved.");
    } catch (err) {
      setError(err);
    }
  }

  async function sync() {
    setMsg(null);
    try {
      const r = await api("/integrations/mock-ats/sync", { method: "POST" });
      setMsg(`Mock ATS sync: ${r.records_found} found, ${r.queued} queued, ${r.skipped_existing} already imported.`);
      load();
    } catch (err) {
      setError(err);
    }
  }

  async function retention() {
    if (!window.confirm(`Delete all applications submitted more than ${settings?.retention_days} days ago? This cannot be undone.`)) return;
    try {
      const r = await api("/admin/retention/run", { method: "POST" });
      setMsg(`Retention run deleted ${r.deleted_applications} application(s).`);
    } catch (err) {
      setError(err);
    }
  }

  const admin = can("settings:write");
  return (
    <>
      <PageHeader title="Integrations & settings" sub="Connected sources, providers and organization policies." />
      {msg && <div className="state state-ok">{msg}</div>}
      <ErrorBox error={error} />
      {!data ? <Loading /> : (
        <section className="card">
          <h2>Integrations</h2>
          <p className="muted small">
            Runtime: LLM provider <strong>{String(data.runtime.llm_provider)}</strong>, email provider <strong>{String(data.runtime.email_provider)}</strong>,
            task mode {String(data.runtime.task_mode)}. Credentials are configured server-side only and are never shown here.
          </p>
          <table className="table">
            <thead><tr><th>Integration</th><th>Status</th><th>Last sync</th><th>Notes</th><th /></tr></thead>
            <tbody>
              {data.integrations.map((i) => (
                <tr key={i.kind}>
                  <td><strong>{i.name}</strong> {i.is_mock && <MockTag />}</td>
                  <td>{i.implemented ? <Badge value={i.enabled ? "approved" : "draft"} label={humanize(i.status)} /> : <Badge value="superseded" label="not implemented" />}</td>
                  <td className="small">{formatDate(i.last_sync_at)}{i.last_result?.records_found !== undefined && <div className="muted">{i.last_result.records_found} found / {i.last_result.queued} queued</div>}</td>
                  <td className="small">{i.needs ?? (i.implemented ? "Available in milestone 1" : "")}</td>
                  <td>{i.kind === "mock_ats" && i.enabled && can("integrations:sync") && <button className="btn small" onClick={sync}>Sync now</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <MailboxPanel />

      {settings && (
        <form className="card form-grid" onSubmit={save}>
          <h2 className="span-2">Organization policies — {settings.name}</h2>
          <label className="span-2">
            Internal email domains (recipients outside these trigger a confirmation warning)
            <input value={domains} onChange={(e) => setDomains(e.target.value)} disabled={!admin} />
          </label>
          <label className="checkbox">
            <input type="checkbox" checked={settings.allow_resume_attachments} disabled={!admin}
              onChange={(e) => setSettings({ ...settings, allow_resume_attachments: e.target.checked })} />
            Allow resume attachments in shortlist emails
          </label>
          <label>
            Data retention (days, 30–3650)
            <input type="number" min={30} max={3650} value={settings.retention_days} disabled={!admin}
              onChange={(e) => setSettings({ ...settings, retention_days: Number(e.target.value) })} />
          </label>
          {admin ? (
            <div className="actions span-2">
              <button className="btn primary">Save settings</button>
              <button type="button" className="btn danger" onClick={retention}>Run retention now</button>
            </div>
          ) : <p className="muted small span-2">Only administrators can change these settings.</p>}
        </form>
      )}
    </>
  );
}
