import { useState } from "react";

import ConfirmDialog from "../../components/ConfirmDialog";
import Modal from "../../components/Modal";
import { useToast } from "../../context/ToastContext";
import useApi from "../../hooks/useApi";
import { platform } from "../../services/adminService";
import { fieldErrors, formatApiError } from "../../utils/formatError";
import { Async, Badge, DataTable, Field, Notice, PageHeader, fmt } from "../../components/admin/ui";

const blank = { name: "", price_monthly: "0", max_users: 5, daily_quota: 1000, monthly_quota: 20000, analytics_level: "basic", support_tier: "Email", scheduling: true, custom_domains: 0 };

export default function PlatformPlans() {
  const { showToast } = useToast();
  const state = useApi(platform.plans);
  const quotas = useApi(platform.quotas);
  const [form, setForm] = useState(null);
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [confirm, setConfirm] = useState(null);

  const save = async (e) => {
    e.preventDefault(); setSaving(true); setErrors({});
    const body = { ...form, max_users: Number(form.max_users), daily_quota: Number(form.daily_quota), monthly_quota: Number(form.monthly_quota), custom_domains: Number(form.custom_domains) };
    try { form.id ? await platform.updatePlan(form.id, body) : await platform.createPlan(body); showToast("Plan saved.", "success"); setForm(null); state.reload(); quotas.reload(); }
    catch (err) { setErrors({ ...fieldErrors(err), form: formatApiError(err, "Could not save the plan.") }); }
    finally { setSaving(false); }
  };
  const act = async () => { try { await platform.planAction(confirm.id, confirm.action); showToast("Plan updated.", "success"); state.reload(); } catch (err) { showToast(formatApiError(err, "Action failed."), "error"); } setConfirm(null); };
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  return (
    <div className="space-y-6">
      <PageHeader title="Plans & quotas" subtitle="Plans define default quotas and seats. Changing a plan changes the limits of every company on it." actions={<button className="btn-primary" onClick={() => { setErrors({}); setForm({ ...blank }); }}>New plan</button>} />
      <Async state={quotas}>{(q) => q.overcommitted && <Notice tone="warn">{q.overcommit_message}</Notice>}</Async>
      <div className="card"><Async state={state}>{(rows) => (<DataTable rows={rows} empty="No plans yet." columns={[
        { key: "name", header: "Plan", render: (p) => <span className="font-medium">{p.name}</span> }, { key: "price_monthly", header: "Price / month", render: (p) => `$${p.price_monthly}` },
        { key: "max_users", header: "Seats" }, { key: "daily_quota", header: "Daily", render: (p) => fmt(p.daily_quota) }, { key: "monthly_quota", header: "Monthly", render: (p) => fmt(p.monthly_quota) },
        { key: "companies", header: "Companies" }, { key: "is_active", header: "Status", render: (p) => <Badge value={p.is_active ? "active" : "cancelled"} label={p.is_active ? "Active" : "Archived"} /> },
        { key: "a", header: "", render: (p) => (<div className="flex gap-2"><button className="btn-secondary px-2 py-1" onClick={() => { setErrors({}); setForm({ ...p }); }}>Edit</button><button className="btn-secondary px-2 py-1" onClick={() => setConfirm({ id: p.id, action: "duplicate", msg: `Duplicate “${p.name}”?` })}>Duplicate</button>{p.is_active && <button className="btn-danger px-2 py-1" onClick={() => setConfirm({ id: p.id, action: "archive", msg: `Archive “${p.name}”? Existing companies keep it; new companies cannot choose it.` })}>Archive</button>}</div>) }]} />)}</Async></div>
      <div className="card p-5"><h2 className="font-semibold mb-3">Company allowances vs platform budget</h2><Async state={quotas}>{(q) => (<DataTable rows={q.companies} empty="No active companies." columns={[{ key: "name", header: "Company" }, { key: "plan", header: "Plan", render: (c) => c.plan || "—" }, { key: "d", header: "Today", render: (c) => `${fmt(c.daily_used)} / ${c.daily_limit === null ? "Unlimited" : fmt(c.daily_limit)}` }, { key: "w", header: "", render: (c) => c.warning ? <Badge value="deferred" label={c.warning} /> : null }]} />)}</Async></div>
      <Modal open={!!form} onClose={() => setForm(null)} title={form?.id ? "Edit plan" : "New plan"} footer={<><button className="btn-secondary" onClick={() => setForm(null)}>Cancel</button><button className="btn-primary" form="pl-form" disabled={saving}>Save</button></>}>
        {form && (<form id="pl-form" onSubmit={save} className="space-y-3">
          {errors.form && <Notice tone="error">{errors.form}</Notice>}
          <Field label="Name" htmlFor="pl-n" error={errors.name}><input id="pl-n" required className="input" value={form.name} onChange={set("name")} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Price / month" htmlFor="pl-p" error={errors.price_monthly}><input id="pl-p" type="number" min="0" step="0.01" className="input" value={form.price_monthly} onChange={set("price_monthly")} /></Field>
            <Field label="Seats" htmlFor="pl-u" error={errors.max_users}><input id="pl-u" type="number" min="1" className="input" value={form.max_users} onChange={set("max_users")} /></Field>
            <Field label="Daily quota" htmlFor="pl-d" error={errors.daily_quota}><input id="pl-d" type="number" min="0" className="input" value={form.daily_quota} onChange={set("daily_quota")} /></Field>
            <Field label="Monthly quota" htmlFor="pl-m" error={errors.monthly_quota}><input id="pl-m" type="number" min="0" className="input" value={form.monthly_quota} onChange={set("monthly_quota")} /></Field>
            <Field label="Analytics level" htmlFor="pl-a"><select id="pl-a" className="input" value={form.analytics_level} onChange={set("analytics_level")}><option value="basic">Basic</option><option value="advanced">Advanced</option><option value="full">Full</option></select></Field>
            <Field label="Support tier" htmlFor="pl-s"><input id="pl-s" className="input" value={form.support_tier} onChange={set("support_tier")} /></Field>
          </div>
          <label className="text-sm flex items-center gap-2"><input type="checkbox" checked={!!form.scheduling} onChange={set("scheduling")} /> Scheduling enabled</label>
        </form>)}
      </Modal>
      <ConfirmDialog open={!!confirm} onClose={() => setConfirm(null)} onConfirm={act} danger={confirm?.action === "archive"} title="Confirm" message={confirm?.msg} confirmLabel="Confirm" />
    </div>
  );
}
