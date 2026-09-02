import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

const initialForm = {
  username: "",
  email: "",
  password: "",
  password_confirm: "",
  first_name: "",
  last_name: "",
  company_name: "",
};

export default function RegisterPage() {
  const { register } = useAuth();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const [form, setForm] = useState(initialForm);
  const [errors, setErrors] = useState({});
  const [loading, setLoading] = useState(false);

  const update = (field) => (e) => setForm({ ...form, [field]: e.target.value });

  const handleSubmit = async (e) => {
    e.preventDefault();
    setErrors({});
    setLoading(true);
    try {
      await register(form);
      showToast("Account created! Welcome aboard.", "success");
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setErrors(err.response?.data || { detail: "Registration failed. Please try again." });
    } finally {
      setLoading(false);
    }
  };

  const fieldError = (name) => (Array.isArray(errors[name]) ? errors[name][0] : errors[name]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4 py-10">
      <div className="w-full max-w-md">
        <div className="flex justify-center mb-6">
          <div className="h-10 w-10 rounded-lg bg-brand-600 flex items-center justify-center text-white font-bold text-lg">
            C
          </div>
        </div>
        <div className="card p-8">
          <h1 className="text-xl font-semibold text-slate-900 text-center">Create your account</h1>
          <p className="text-sm text-slate-500 text-center mt-1">Start sending campaigns in minutes</p>

          {errors.detail && (
            <div className="mt-4 rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
              {errors.detail}
            </div>
          )}

          <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">First name</label>
                <input className="input" value={form.first_name} onChange={update("first_name")} />
              </div>
              <div>
                <label className="label">Last name</label>
                <input className="input" value={form.last_name} onChange={update("last_name")} />
              </div>
            </div>
            <div>
              <label className="label">Username</label>
              <input className="input" required value={form.username} onChange={update("username")} />
              {fieldError("username") && <p className="mt-1 text-xs text-red-600">{fieldError("username")}</p>}
            </div>
            <div>
              <label className="label">Email</label>
              <input className="input" type="email" required value={form.email} onChange={update("email")} />
              {fieldError("email") && <p className="mt-1 text-xs text-red-600">{fieldError("email")}</p>}
            </div>
            <div>
              <label className="label">Company name (optional)</label>
              <input className="input" value={form.company_name} onChange={update("company_name")} />
            </div>
            <div>
              <label className="label">Password</label>
              <input className="input" type="password" required value={form.password} onChange={update("password")} />
              {fieldError("password") && <p className="mt-1 text-xs text-red-600">{fieldError("password")}</p>}
            </div>
            <div>
              <label className="label">Confirm password</label>
              <input
                className="input"
                type="password"
                required
                value={form.password_confirm}
                onChange={update("password_confirm")}
              />
              {fieldError("password_confirm") && (
                <p className="mt-1 text-xs text-red-600">{fieldError("password_confirm")}</p>
              )}
            </div>
            <button type="submit" className="btn-primary w-full" disabled={loading}>
              {loading ? "Creating account…" : "Create account"}
            </button>
          </form>

          <p className="mt-6 text-center text-sm text-slate-500">
            Already have an account?{" "}
            <Link to="/login" className="text-brand-600 font-medium hover:underline">
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
