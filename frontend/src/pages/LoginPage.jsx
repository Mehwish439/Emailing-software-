import { useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { formatApiError } from "../utils/formatError";
import { ACCOUNT_TYPES, DASHBOARD_NAMES, canAccessPath, homePathFor } from "../utils/roles";

export default function LoginPage() {
  const { login } = useAuth();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const [form, setForm] = useState({ username: "", password: "" });
  const [error, setError] = useState(params.get("expired") ? "Your session has expired. Please sign in again." : "");
  const [loading, setLoading] = useState(false);
  const [accountType, setAccountType] = useState(ACCOUNT_TYPES[1].key);

  const from = location.state?.from?.pathname;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const loggedIn = await login(form);
      // The tab is only a hint. The role comes from the server; if they differ we say so and use the real one.
      if (loggedIn.role !== accountType) {
        showToast(`This is a ${DASHBOARD_NAMES[loggedIn.role].replace(" dashboard", "")} account — opening your ${DASHBOARD_NAMES[loggedIn.role]}.`, "info");
      } else {
        showToast("Welcome back!", "success");
      }
      // Role-based redirect: honour the page they were sent from only if their role may open it.
      navigate(from && from !== "/" && canAccessPath(loggedIn, from) ? from : homePathFor(loggedIn), { replace: true });
    } catch (err) {
      setError(formatApiError(err, "Invalid username/email or password."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md">
        <div className="flex justify-center mb-6">
          <div className="h-10 px-3 rounded-lg bg-brand-600 flex items-center justify-center text-white font-bold text-lg">
            QRM
          </div>
        </div>
        <div className="card p-8">
          <h1 className="text-xl font-semibold text-slate-900 text-center">Sign in to your account</h1>
          <p className="text-sm text-slate-500 text-center mt-1">Manage your email campaigns</p>

          <div role="tablist" aria-label="Account type" className="mt-5 grid grid-cols-3 gap-1 rounded-lg bg-slate-100 p-1">
            {ACCOUNT_TYPES.map((t) => (
              <button key={t.key} type="button" role="tab" aria-selected={accountType === t.key}
                onClick={() => setAccountType(t.key)}
                className={`rounded-md px-2 py-2 text-xs font-medium leading-tight ${accountType === t.key ? "bg-white text-brand-700 shadow-sm" : "text-slate-600 hover:text-slate-900"}`}>
                {t.label}
              </button>
            ))}
          </div>
          <p className="mt-2 text-center text-xs text-slate-500">{ACCOUNT_TYPES.find((t) => t.key === accountType).hint}</p>

          {error && (
            <div className="mt-4 rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}

          <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
            <div>
              <label className="label">Username or email</label>
              <input
                className="input"
                type="text"
                required
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
                autoComplete="username"
              />
            </div>
            <div>
              <label className="label">Password</label>
              <input
                className="input"
                type="password"
                required
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                autoComplete="current-password"
              />
            </div>
            <button type="submit" className="btn-primary w-full" disabled={loading}>
              {loading ? "Signing in…" : "Sign in"}
            </button>
          </form>

          <p className="mt-4 text-center text-sm">
            <Link to="/forgot-password" className="text-brand-600 hover:underline">Forgot your password?</Link>
          </p>
          <p className="mt-3 text-center text-sm text-slate-500">
            Don&apos;t have an account?{" "}
            <Link to="/signup" className="text-brand-600 font-medium hover:underline">
              Create one
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
