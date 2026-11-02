import { useState } from "react";
import { Link } from "react-router-dom";

import api from "../services/api";
import { formatApiError } from "../utils/formatError";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError("");
    try { await api.post("/auth/forgot-password/", { email }); setDone(true); }
    catch (err) { setError(formatApiError(err, "Could not send the request. Please try again.")); }
    finally { setBusy(false); }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md card p-8">
        <h1 className="text-xl font-semibold text-slate-900 text-center">Reset your password</h1>
        {done ? (
          <p className="mt-4 text-sm text-slate-600 text-center" role="status">If an account exists for that email, a reset link has been sent. The link works once and expires in 7 days.</p>
        ) : (
          <form onSubmit={submit} className="mt-6 space-y-4">
            <div><label className="label" htmlFor="fp-email">Email</label>
              <input id="fp-email" type="email" required className="input" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
            {error && <p className="text-sm text-red-700" role="alert">{error}</p>}
            <button className="btn-primary w-full" disabled={busy}>{busy ? "Sending…" : "Send reset link"}</button>
          </form>
        )}
        <p className="mt-4 text-center text-sm"><Link className="text-brand-600" to="/login">Back to sign in</Link></p>
      </div>
    </div>
  );
}
