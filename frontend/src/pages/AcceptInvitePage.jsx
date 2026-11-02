import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import api from "../services/api";
import { acceptInvite } from "../services/adminService";
import { useToast } from "../context/ToastContext";
import { fieldErrors, formatApiError } from "../utils/formatError";
import { Field, Notice } from "../components/admin/ui";

/** Accepts a full invitation link or just the code (token) and returns the code. */
export function extractToken(text = "") {
  const t = text.trim();
  const m = t.match(/[?&]token=([^&\s#]+)/);
  return decodeURIComponent(m ? m[1] : t);
}

/** Used for /join (paste the link or code) and /accept-invite?token=… (arrives from the emailed link). */
export default function AcceptInvitePage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [code, setCode] = useState(params.get("token") || "");
  const [info, setInfo] = useState(null);
  const [lookupError, setLookupError] = useState("");
  const [form, setForm] = useState({ first_name: "", last_name: "", email: "", password: "", password_confirm: "" });
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const lookup = async (raw) => {
    setLookupError(""); setInfo(null);
    const token = extractToken(raw);
    if (!token) return;
    try {
      const { data } = await api.get("/auth/invite-info/", { params: { token } });
      setInfo({ ...data, token });
      setForm((f) => ({ ...f, first_name: data.first_name || f.first_name, last_name: data.last_name || f.last_name }));
    } catch (err) { setLookupError(formatApiError(err, "This invitation is invalid, expired or already used.")); }
  };
  useEffect(() => { if (params.get("token")) lookup(params.get("token")); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async (e) => {
    e.preventDefault();
    setErrors({});
    if (form.password !== form.password_confirm) return setErrors({ password_confirm: "Passwords do not match." });
    setBusy(true);
    try {
      await acceptInvite(info.token, form.password, { email: form.email.trim(), first_name: form.first_name, last_name: form.last_name });
      showToast("Account ready. Please sign in.", "success");
      navigate("/login", { replace: true });
    } catch (err) { setErrors({ ...fieldErrors(err), form: formatApiError(err, "Could not complete sign-up.") }); }
    finally { setBusy(false); }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4 py-10">
      <div className="w-full max-w-lg">
        <div className="flex justify-center mb-6"><div className="h-10 px-3 rounded-lg bg-brand-600 flex items-center text-white font-bold text-lg">QRM</div></div>
        <div className="card p-8">
          <h1 className="text-xl font-semibold text-slate-900 text-center">Join your company</h1>
          <div className="mt-5 grid grid-cols-2 gap-1 rounded-lg bg-slate-100 p-1" role="tablist" aria-label="Sign-up type">
            <Link role="tab" aria-selected="false" to="/signup" className="rounded-md px-2 py-2 text-center text-sm font-medium text-slate-600 hover:text-slate-900">Create a new company</Link>
            <span role="tab" aria-selected="true" className="rounded-md bg-white px-2 py-2 text-center text-sm font-medium text-brand-700 shadow-sm">Join an existing company</span>
          </div>

          {!info ? (
            <div className="mt-5 space-y-4">
              <p className="text-sm text-slate-600">Paste the invitation link (or code) your company administrator sent you. You cannot join without one.</p>
              {lookupError && <Notice tone="error">{lookupError}</Notice>}
              <Field label="Invitation link or code" htmlFor="jn-code"><textarea id="jn-code" rows={3} className="input" value={code} onChange={(e) => setCode(e.target.value)} /></Field>
              <button className="btn-primary w-full" onClick={() => lookup(code)} disabled={!code.trim()}>Continue</button>
            </div>
          ) : (
            <form onSubmit={submit} className="mt-5 space-y-4">
              <Notice tone="info">You are joining <b>{info.company || "your company"}</b> as a {info.role === "company_admin" ? "Company Admin" : "regular user"}. Invitation for {info.email}.</Notice>
              {errors.form && <Notice tone="error">{errors.form}</Notice>}
              <div className="grid grid-cols-2 gap-3">
                <Field label="First name" htmlFor="jn-fn"><input id="jn-fn" required className="input" value={form.first_name} onChange={set("first_name")} /></Field>
                <Field label="Last name" htmlFor="jn-ln"><input id="jn-ln" className="input" value={form.last_name} onChange={set("last_name")} /></Field>
              </div>
              <Field label="Work email" htmlFor="jn-em" error={errors.email} hint="Must match the email the invitation was sent to."><input id="jn-em" type="email" required className="input" autoComplete="email" value={form.email} onChange={set("email")} /></Field>
              <Field label="Password" htmlFor="jn-pw" error={errors.password}><input id="jn-pw" type="password" required minLength={8} className="input" autoComplete="new-password" value={form.password} onChange={set("password")} /></Field>
              <Field label="Confirm password" htmlFor="jn-pc" error={errors.password_confirm}><input id="jn-pc" type="password" required className="input" autoComplete="new-password" value={form.password_confirm} onChange={set("password_confirm")} /></Field>
              <button className="btn-primary w-full" disabled={busy}>{busy ? "Saving…" : "Join company"}</button>
            </form>
          )}
          <p className="mt-5 text-center text-sm text-slate-500">Already have an account? <Link to="/login" className="text-brand-600 font-medium hover:underline">Sign in</Link></p>
        </div>
      </div>
    </div>
  );
}
