import { useState } from "react";
import { Link } from "react-router-dom";

import Modal from "../../components/Modal";
import { useToast } from "../../context/ToastContext";
import useApi, { useDebounced } from "../../hooks/useApi";
import { platform } from "../../services/adminService";
import { fieldErrors, formatApiError } from "../../utils/formatError";
import { Async, Badge, DataTable, Field, Notice, PageFooter, PageHeader, SearchInput, fmt, limitText } from "../../components/admin/ui";

const blank = { name: "", plan: "", timezone: "UTC", daily_quota_override: "", monthly_quota_override: "" };
const num = (v) => (v === "" ? null : Number(v));

export default function PlatformCompanies() {
  const { showToast } = useToast();
  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  const [page, setPage] = useState(1);
  const state = useApi(() => platform.companies({ search: q || undefined, page }), [q, page]);
  const plans = useApi(platform.plans);
  const [form, setForm] = useState(null);
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);

  const create = async (e) => {
    e.preventDefault(); setSaving(true); setErrors({});
    try {
      await platform.createCompany({ name: form.name.trim(), plan: form.plan ? Number(form.plan) : null, timezone: form.timezone, daily_quota_override: num(form.daily_quota_override), monthly_quota_override: num(form.monthly_quota_override) });
      showToast("Company created. Now invite its administrator from the company page.", "success"); setForm(null); state.reload();
    } catch (err) { setErrors({ ...fieldErrors(err), form: formatApiError(err, "Could not create the company.") }); }
    finally { setSaving(false); }
  };

  return (
    <div className="space-y-6">
      <PageHeader title="Companies" subtitle="Each company is an isolated tenant with its own plan, quotas and members." actions={<button className="btn-primary" onClick={() => { setErrors({}); setForm({ ...blank }); }}>New company</button>} />
      <SearchInput value={search} onChange={(v) => { setSearch(v); setPage(1); }} placeholder="Search companies" />
      <div className="card"><Async state={state}>{(d) => (<><DataTable rows={d.results} empty="No companies yet. Create the first one." columns={[
        { key: "name", header: "Company", render: (c) => <Link className="font-medium text-brand-700 hover:underline" to={`/platform/companies/${c.id}`}>{c.name}</Link> },
        { key: "plan_name", header: "Plan", render: (c) => c.plan_name || "—" }, { key: "status", header: "Status", render: (c) => <Badge value={c.status} /> },
        { key: "users", header: "Users", render: (c) => fmt(c.users) },
        { key: "daily", header: "Daily used / limit", render: (c) => `${fmt(c.daily_used)} / ${limitText(c.daily_limit)}` },
        { key: "monthly", header: "Monthly used / limit", render: (c) => `${fmt(c.monthly_used)} / ${limitText(c.monthly_limit)}` }]} /><PageFooter data={d} onPage={setPage} /></>)}</Async></div>

      <Modal open={!!form} onClose={() => setForm(null)} title="New company" footer={<><button className="btn-secondary" onClick={() => setForm(null)}>Cancel</button><button className="btn-primary" form="co-form" disabled={saving}>{saving ? "Creating…" : "Create company"}</button></>}>
        {form && (<form id="co-form" onSubmit={create} className="space-y-3">
          {errors.form && <Notice tone="error">{errors.form}</Notice>}
          <Field label="Company name" htmlFor="co-n" error={errors.name}><input id="co-n" required className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Plan" htmlFor="co-p" error={errors.plan} hint="Plan quotas apply unless overridden below.">
            <select id="co-p" className="input" value={form.plan} onChange={(e) => setForm({ ...form, plan: e.target.value })}><option value="">No plan</option>{(plans.data || []).filter((p) => p.is_active).map((p) => <option key={p.id} value={p.id}>{p.name} — {fmt(p.daily_quota)}/day, {p.max_users} users</option>)}</select></Field>
          <Field label="Time zone" htmlFor="co-tz"><input id="co-tz" className="input" value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Daily quota override" htmlFor="co-dq" hint="Blank = use plan"><input id="co-dq" type="number" min="0" className="input" value={form.daily_quota_override} onChange={(e) => setForm({ ...form, daily_quota_override: e.target.value })} /></Field>
            <Field label="Monthly quota override" htmlFor="co-mq"><input id="co-mq" type="number" min="0" className="input" value={form.monthly_quota_override} onChange={(e) => setForm({ ...form, monthly_quota_override: e.target.value })} /></Field>
          </div></form>)}
      </Modal>
    </div>
  );
}
