import { useEffect, useState } from "react";

import ConfirmDialog from "../../components/ConfirmDialog";
import { useToast } from "../../context/ToastContext";
import useApi from "../../hooks/useApi";
import { platform } from "../../services/adminService";
import { fieldErrors, formatApiError } from "../../utils/formatError";
import { Async, Badge, Field, Notice, PageHeader, when } from "../../components/admin/ui";

const num = (v) => (v === "" || v === null || v === undefined ? null : Number(v));

export default function PlatformProviders() {
  const { showToast } = useToast();
  const settings = useApi(platform.settings);
  const [probe, setProbe] = useState(false);
  const health = useApi(() => platform.health(probe ? { probe: "smtp" } : undefined), [probe]);
  const [form, setForm] = useState(null);
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [confirm, setConfirm] = useState(null);
  useEffect(() => { const s = settings.data; if (s) setForm({ active_provider: s.active_provider, rate_per_minute: s.rate_per_minute ?? "", daily_budget: s.daily_budget ?? "", monthly_budget: s.monthly_budget ?? "", allow_company_provider_choice: !!s.allow_company_provider_choice }); }, [settings.data]);

  const submit = async () => {
    setSaving(true); setErrors({});
    try { const r = await platform.updateSettings({ active_provider: form.active_provider, rate_per_minute: num(form.rate_per_minute), daily_budget: num(form.daily_budget), monthly_budget: num(form.monthly_budget), allow_company_provider_choice: form.allow_company_provider_choice }); showToast("Settings saved.", "success"); if (r.warning) showToast(r.warning, "info"); settings.reload(); health.reload(); }
    catch (err) { setErrors({ ...fieldErrors(err), form: formatApiError(err, "Could not save settings.") }); }
    finally { setSaving(false); setConfirm(null); }
  };
  const changingProvider = settings.data && form && form.active_provider !== settings.data.active_provider;

  return (
    <div className="space-y-6">
      <PageHeader title="Providers & limits" subtitle="Brevo is the default. SMTP must be explicitly configured on the server and activated here. Secrets are never displayed." />
      <Async state={health}>{(h) => (
        <div className="grid gap-4 md:grid-cols-2">
          {Object.entries(h.providers).map(([name, p]) => (
            <div key={name} className="card p-5 space-y-2">
              <div className="flex items-center justify-between"><h2 className="font-semibold capitalize">{name}</h2>{p.active && <Badge value="active" label="Active provider" />}</div>
              <p className="text-sm">{p.ok === null ? <Badge value="pending" label="Not probed" /> : p.ok ? <Badge value="ok" label="Connection OK" /> : <Badge value="failed" label="Connection failed" />}</p>
              <p className="text-sm text-slate-600 break-words">{typeof p.detail === "string" ? p.detail : p.message || ""}</p>
              <p className="text-xs text-slate-500">A passing connection test shows the provider is reachable and credentials authenticate. It does not prove inbox delivery. Checked {when(h.checked_at)}.</p>
              {name === "smtp" && !p.active && <button className="btn-secondary" onClick={() => setProbe(true)}>Test SMTP connection (sends no mail)</button>}
            </div>))}
        </div>)}</Async>
      <Async state={settings}>{() => form && (
        <form onSubmit={(e) => { e.preventDefault(); changingProvider ? setConfirm(true) : submit(); }} className="card p-5 space-y-4 max-w-2xl">
          {errors.form && <Notice tone="error">{errors.form}</Notice>}
          <Field label="Active provider" htmlFor="ap" error={errors.active_provider} hint="Campaigns already sending keep the provider they started with. There is no automatic failover.">
            <select id="ap" className="input" value={form.active_provider} onChange={(e) => setForm({ ...form, active_provider: e.target.value })}><option value="brevo">Brevo (default)</option><option value="smtp">Self-hosted SMTP</option></select></Field>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <Field label="Rate / minute" htmlFor="rp" error={errors.rate_per_minute} hint="Software guard; blank = none"><input id="rp" type="number" min="0" className="input" value={form.rate_per_minute} onChange={(e) => setForm({ ...form, rate_per_minute: e.target.value })} /></Field>
            <Field label="Daily budget" htmlFor="db" error={errors.daily_budget}><input id="db" type="number" min="0" className="input" value={form.daily_budget} onChange={(e) => setForm({ ...form, daily_budget: e.target.value })} /></Field>
            <Field label="Monthly budget" htmlFor="mb" error={errors.monthly_budget}><input id="mb" type="number" min="0" className="input" value={form.monthly_budget} onChange={(e) => setForm({ ...form, monthly_budget: e.target.value })} /></Field>
          </div>
          <label className="text-sm flex items-center gap-2"><input type="checkbox" checked={form.allow_company_provider_choice} onChange={(e) => setForm({ ...form, allow_company_provider_choice: e.target.checked })} /> Let companies choose among their approved providers</label>
          <button className="btn-primary" disabled={saving}>{saving ? "Saving…" : "Save settings"}</button>
        </form>)}</Async>
      <ConfirmDialog open={!!confirm} onClose={() => setConfirm(null)} onConfirm={submit} loading={saving} title="Change the active provider?" message={`New campaigns will be sent through ${form?.active_provider === "smtp" ? "self-hosted SMTP" : "Brevo"}. Run the SMTP validation script and the connection test first; real delivery must be verified with controlled test recipients.`} confirmLabel="Change provider" />
    </div>
  );
}
