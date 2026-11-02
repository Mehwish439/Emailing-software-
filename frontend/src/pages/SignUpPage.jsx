import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { fieldErrors, formatApiError } from "../utils/formatError";
import { homePathFor } from "../utils/roles";
import { Field, Notice } from "../components/admin/ui";

const blank = { company_name: "", first_name: "", last_name: "", email: "", password: "", password_confirm: "" };

export default function SignUpPage() {
  const { registerCompany } = useAuth();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const [form, setForm] = useState(blank);
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErrors({});
    try {
      const user = await registerCompany({ ...form, email: form.email.trim() });
      showToast("Company created. Welcome!", "success");
      navigate(homePathFor(user), { replace: true });
    } catch (err) {
      setErrors({ ...fieldErrors(err), form: formatApiError(err, "Could not create the company.") });
    } finally { setBusy(false); }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4 py-10">
      <div className="w-full max-w-lg">
        <div className="flex justify-center mb-6"><div className="h-10 px-3 rounded-lg bg-brand-600 flex items-center text-white font-bold text-lg">QRM</div></div>
        <div className="card p-8">
          <h1 className="text-xl font-semibold text-slate-900 text-center">Create your account</h1>
          <div className="mt-5 grid grid-cols-2 gap-1 rounded-lg bg-slate-100 p-1" role="tablist" aria-label="Sign-up type">
            <span role="tab" aria-selected="true" className="rounded-md bg-white px-2 py-2 text-center text-sm font-medium text-brand-700 shadow-sm">Create a new company</span>
            <Link role="tab" aria-selected="false" to="/join" className="rounded-md px-2 py-2 text-center text-sm font-medium text-slate-600 hover:text-slate-900">Join an existing company</Link>
          </div>
          <p className="mt-3 text-xs text-slate-500 text-center">You become the Company Admin and start on a limited trial plan.</p>
          <form onSubmit={submit} className="mt-5 space-y-4">
            {errors.form && <Notice tone="error">{errors.form}</Notice>}
            <Field label="Company name" htmlFor="su-co" error={errors.company_name}><input id="su-co" required className="input" value={form.company_name} onChange={set("company_name")} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Your first name" htmlFor="su-fn" error={errors.first_name}><input id="su-fn" required className="input" autoComplete="given-name" value={form.first_name} onChange={set("first_name")} /></Field>
              <Field label="Last name" htmlFor="su-ln"><input id="su-ln" className="input" autoComplete="family-name" value={form.last_name} onChange={set("last_name")} /></Field>
            </div>
            <Field label="Work email" htmlFor="su-em" error={errors.email}><input id="su-em" type="email" required className="input" autoComplete="email" value={form.email} onChange={set("email")} /></Field>
            <Field label="Password" htmlFor="su-pw" error={errors.password}><input id="su-pw" type="password" required className="input" autoComplete="new-password" value={form.password} onChange={set("password")} /></Field>
            <Field label="Confirm password" htmlFor="su-pc" error={errors.password_confirm}><input id="su-pc" type="password" required className="input" autoComplete="new-password" value={form.password_confirm} onChange={set("password_confirm")} /></Field>
            <button className="btn-primary w-full" disabled={busy}>{busy ? "Creating…" : "Create company"}</button>
          </form>
          <p className="mt-5 text-center text-sm text-slate-500">Already have an account? <Link to="/login" className="text-brand-600 font-medium hover:underline">Sign in</Link></p>
        </div>
      </div>
    </div>
  );
}
