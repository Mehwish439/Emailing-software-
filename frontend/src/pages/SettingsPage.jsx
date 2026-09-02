import { useState } from "react";

import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { updateProfile } from "../services/authService";

export default function SettingsPage() {
  const { user, setUser } = useAuth();
  const { showToast } = useToast();
  const [form, setForm] = useState({
    first_name: user?.first_name || "",
    last_name: user?.last_name || "",
    company_name: user?.company_name || "",
  });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const updated = await updateProfile(form);
      setUser(updated);
      showToast("Profile updated.", "success");
    } catch {
      showToast("Failed to update profile.", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6 max-w-xl">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Settings</h1>
        <p className="text-sm text-slate-500">Manage your account details.</p>
      </div>

      <form className="card p-6 space-y-4" onSubmit={handleSubmit}>
        <div>
          <label className="label">Username</label>
          <input className="input bg-slate-50" value={user?.username || ""} disabled />
        </div>
        <div>
          <label className="label">Email</label>
          <input className="input bg-slate-50" value={user?.email || ""} disabled />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label">First name</label>
            <input
              className="input"
              value={form.first_name}
              onChange={(e) => setForm({ ...form, first_name: e.target.value })}
            />
          </div>
          <div>
            <label className="label">Last name</label>
            <input
              className="input"
              value={form.last_name}
              onChange={(e) => setForm({ ...form, last_name: e.target.value })}
            />
          </div>
        </div>
        <div>
          <label className="label">Company name</label>
          <input
            className="input"
            value={form.company_name}
            onChange={(e) => setForm({ ...form, company_name: e.target.value })}
          />
        </div>
        <div className="flex justify-end">
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? "Saving…" : "Save Changes"}
          </button>
        </div>
      </form>
    </div>
  );
}
