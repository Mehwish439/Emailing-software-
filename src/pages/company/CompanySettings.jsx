import { useEffect, useState } from "react";

import { useToast } from "../../context/ToastContext";
import useApi from "../../hooks/useApi";
import { company } from "../../services/adminService";
import { fieldErrors, formatApiError } from "../../utils/formatError";
import { Async, Badge, Field, Notice, PageHeader, UsageBar, limitText } from "../../components/admin/ui";

export default function CompanySettings() {
  const { showToast } = useToast();
  const settings = useApi(company.settings);
  const sub = useApi(company.subscription);
  const [form, setForm] = useState(null);
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (settings.data) setForm({ name: settings.data.name, timezone: settings.data.timezone || "", allow_overallocation: !!settings.data.allow_overallocation, preferred_provider: settings.data.preferred_provider || "" }); }, [settings.data]);

  const save = async (e) => {
    e.preventDefault(); setSaving(true); setErrors({});
    try { await company.updateSettings({ ...form, preferred_provider: form.preferred_provider || null }); showToast("Settings saved.", "success"); settings.reload(); }
    catch (err) { setErrors({ ...fieldErrors(err), form: formatApiError(err, "Could not save settings.") }); }
    finally { setSaving(false); }
  };

  return (
    <div className="space-y-6">
      <PageHeader title="Company & plan" />
      <Async state={settings}>{(s) => form && (
        <form onSubmit={save} className="card p-5 space-y-4 max-w-2xl">
          {errors.form && <Notice tone="error">{errors.form}</Notice>}
          <Field label="Company name" htmlFor="cn" error={errors.name}><input id="cn" className="input" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Time zone" htmlFor="tz" hint="IANA name, e.g. Asia/Karachi"><input id="tz" className="input" value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} /></Field>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.allow_overallocation} onChange={(e) => setForm({ ...form, allow_overallocation: e.target.checked })} /> Allow user quotas to total more than the company allowance</label>
          <Field label="Email provider" htmlFor="pp" hint="Providers are approved by the platform administrator. Credentials are never shown here.">
            <select id="pp" className="input" value={form.preferred_provider} onChange={(e) => setForm({ ...form, preferred_provider: e.target.value })}>
              <option value="">Platform default</option>{(s.allowed_providers || []).map((p) => <option key={p} value={p}>{p}</option>)}</select></Field>
          <button className="btn-primary" disabled={saving}>{saving ? "Saving…" : "Save changes"}</button>
        </form>)}</Async>
      <Async state={sub}>{(d) => (
        <div className="card p-5 space-y-4 max-w-2xl">
          <div className="flex items-center justify-between"><h2 className="font-semibold">Plan: {d.plan?.name || "None assigned"}</h2><Badge value={d.status} /></div>
          {d.plan && <dl className="grid grid-cols-2 gap-2 text-sm"><dt className="text-slate-500">Seats</dt><dd>{d.seats_used} / {d.plan.max_users}</dd><dt className="text-slate-500">Daily limit</dt><dd>{limitText(d.daily_limit)}</dd><dt className="text-slate-500">Monthly limit</dt><dd>{limitText(d.monthly_limit)}</dd><dt className="text-slate-500">Analytics</dt><dd>{d.plan.analytics_level}</dd><dt className="text-slate-500">Support</dt><dd>{d.plan.support_tier}</dd></dl>}
          <UsageBar label="Today" used={d.daily_used} limit={d.daily_limit} /><UsageBar label="This month" used={d.monthly_used} limit={d.monthly_limit} />
          <p className="text-xs text-slate-500">{d.note} Plan changes are made by your platform administrator.</p>
        </div>)}</Async>
    </div>
  );
}
