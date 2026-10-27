import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ErrorBox } from "../components/ui";
import { useApp } from "../state";

const DEMO_ACCOUNTS = [
  ["recruiter@acme.example", "Recruiter (Acme)"],
  ["admin@acme.example", "Administrator (Acme)"],
  ["manager@acme.example", "Hiring manager (Acme, read-only)"],
  ["admin@globex.example", "Administrator (Globex — separate tenant)"],
];

export default function LoginPage() {
  const { login, demoMode } = useApp();
  const nav = useNavigate();
  const [email, setEmail] = useState("recruiter@acme.example");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      nav("/jobs");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="card login" onSubmit={onSubmit}>
        <h1>
          TalentMatch <span className="accent">AI</span>
        </h1>
        <p className="muted">Enterprise sign-in</p>
        <label>
          Work email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required />
        </label>
        <label>
          Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </label>
        <ErrorBox error={error} />
        <button className="btn primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        <p className="muted small">
          Milestone 1 uses local email/password accounts. Enterprise SSO (OIDC/SAML) is planned production work.
        </p>
        {demoMode && (
          <div className="demo-accounts">
            <strong>Synthetic demo accounts</strong> (password <code>TalentMatch-Demo-2026!</code>):
            <ul>
              {DEMO_ACCOUNTS.map(([e, l]) => (
                <li key={e}>
                  <button type="button" className="link" onClick={() => setEmail(e)}>{e}</button> — {l}
                </li>
              ))}
            </ul>
          </div>
        )}
      </form>
    </div>
  );
}
