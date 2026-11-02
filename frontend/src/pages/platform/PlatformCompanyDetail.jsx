import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import ConfirmDialog from "../../components/ConfirmDialog";
import Modal from "../../components/Modal";
import { useToast } from "../../context/ToastContext";
import useApi from "../../hooks/useApi";
import { platform } from "../../services/adminService";
import { fieldErrors, formatApiError } from "../../utils/formatError";
import { Async, Badge, DataTable, Field, Notice, PageHeader, Tile, UsageBar, fmt, pct, when } from "../../components/admin/ui";

const num = (v) => (v === "" || v === null || v === undefined ? null : Number(v));

export default function PlatformCompanyDetail() {
  const { id } = useParams();
  const { showToast } = useToast();
  const state = useApi(() => platform.company(id), [id]);
  const plans = useApi(platform.plans);
  const [edit, setEdit] = useState(null);
  const [invite, setInvite] = useState(null);
  const [link, setLink] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  useEffect(() => { setEdit(null); }, [id]);

  const call = async (fn, ok) => { try { await fn(); showToast(ok, "success"); state.reload(); } catch (err) { showToast(formatApiError(err, "Action failed."), "error"); } setConfirm(null); };

  const saveEdit = async (e) => {
    e.preventDefault(); setSaving(true); setErrors({});
    try { await platform.updateCompany(id, { name: edit.name, plan: edit.plan ? Number(edit.plan) : null, daily_quota_override: num(edit.daily_quota_override), monthly_quota_override: num(edit.monthly_quota_override), allowed_providers: edit.allowed_providers }); showToast("Company updated.", "success"); setEdit(null); state.reload(); }
    catch (err) { setErrors({ ...fieldErrors(err), form: formatApiError(err, "Could not update the company.") }); }
    finally { setSaving(false); }
  };
  const sendInvite = async (e) => {
    e.preventDefault(); setSaving(true); setErrors({});
    try { const r = await platform.inviteMember(id, invite); setInvite(null); setLink({ email: r.user.email, url: r.invite_url, emailed: r.email_sent }); state.reload(); }
    catch (err) { setErrors({ ...fieldErrors(err), form: formatApiError(err, "Could not create the invitation.") }); }
    finally { setSaving(false); }
  };
  const resetLink = async (m) => { try { const r = await platform.userAction(m.id, "reset-invite"); setLink({ email: m.email, url: r.invite_url, emailed: r.email_sent }); } catch (err) { showToast(formatApiError(err, "Could not create a link."), "error"); } };

  return (
    <Async state={state}>{(c) => (
      <div className="space-y-6">
        <PageHeader title={c.name} subtitle={<Link className="text-brand-700" to="/platform/companies">← All companies</Link>}
          actions={<>
            <button className="btn-secondary" onClick={() => { setErrors({}); setEdit({ name: c.name, plan: c.plan || "", daily_quota_override: c.daily_quota_override ?? "", monthly_quota_override: c.monthly_quota_override ?? "", allowed_providers: c.allowed_providers || [] }); }}>Edit plan & quotas</button>
            <button className="btn-primary" onClick={() => { setErrors({}); setInvite({ email: "", first_name: "", last_name: "", role: "company_admin" }); }}>Invite administrator / user</button>
            {c.status === "suspended" ? <button className="btn-secondary" onClick={() => setConfirm({ title: "Reactivate company", message: `Reactivate ${c.name}? Held campaigns resume.`, danger: false, run: () => call(() => platform.companyAction(id, "reactivate"), "Company reactivated.") })}>Reactivate</button>
              : <button className="btn-danger" onClick={() => setConfirm({ title: "Suspend company", message: `Suspend ${c.name}? New sends are refused and running campaigns are held (not deleted). Members can still sign in.`, run: () => call(() => platform.companyAction(id, "suspend", { pause_running: false }), "Company suspended.") })}>Suspend</button>}
          </>} />
        {c.status === "suspended" && <Notice tone="error">This company is suspended.</Notice>}
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Tile label="Plan" value={c.plan_name || "None"} /><Tile label="Active users" value={fmt(c.users)} />
          <Tile label="Accepted (30d)" value={fmt(c.metrics_30d.accepted)} /><Tile label="Bounce rate (30d)" value={pct(c.metrics_30d.bounce_rate)} />
        </div>
        <div className="card p-5 space-y-4 max-w-2xl"><UsageBar label="Today" used={c.daily_used} limit={c.daily_limit} /><UsageBar label="This month" used={c.monthly_used} limit={c.monthly_limit} /></div>
        <div className="card"><h2 className="px-4 pt-4 font-semibold">Members</h2>
          <DataTable rows={c.members} empty="No members yet — invite the company administrator." columns={[
            { key: "email", header: "User", render: (m) => <div><p className="font-medium">{`${m.first_name} ${m.last_name}`.trim() || m.email}</p><p className="text-xs text-slate-500">{m.email}</p></div> },
            { key: "role", header: "Role", render: (m) => <Badge value={m.role} label={m.role === "company_admin" ? "Company admin" : "User"} /> },
            { key: "st", header: "Status", render: (m) => m.invite_pending ? <Badge value="pending" label="Invite pending" /> : <Badge value={m.is_active ? "active" : "suspended"} label={m.is_active ? "Active" : "Deactivated"} /> },
            { key: "last_login", header: "Last sign-in", render: (m) => when(m.last_login) },
            { key: "a", header: "", render: (m) => <button className="btn-secondary px-2 py-1" onClick={() => resetLink(m)}>{m.invite_pending ? "Resend invite" : "Password reset link"}</button> }]} /></div>

        <Modal open={!!edit} onClose={() => setEdit(null)} title="Plan & quotas" footer={<><button className="btn-secondary" onClick={() => setEdit(null)}>Cancel</button><button className="btn-primary" form="ce-form" disabled={saving}>Save</button></>}>
          {edit && (<form id="ce-form" onSubmit={saveEdit} className="space-y-3">
            {errors.form && <Notice tone="error">{errors.form}</Notice>}
            <Field label="Name" htmlFor="ce-n" error={errors.name}><input id="ce-n" className="input" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
            <Field label="Plan" htmlFor="ce-p"><select id="ce-p" className="input" value={edit.plan} onChange={(e) => setEdit({ ...edit, plan: e.target.value })}><option value="">No plan</option>{(plans.data || []).map((p) => <option key={p.id} value={p.id}>{p.name}{p.is_active ? "" : " (archived)"}</option>)}</select></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Daily override" htmlFor="ce-d" error={errors.daily_quota_override}><input id="ce-d" type="number" min="0" className="input" value={edit.daily_quota_override} onChange={(e) => setEdit({ ...edit, daily_quota_override: e.target.value })} /></Field>
              <Field label="Monthly override" htmlFor="ce-m" error={errors.monthly_quota_override}><input id="ce-m" type="number" min="0" className="input" value={edit.monthly_quota_override} onChange={(e) => setEdit({ ...edit, monthly_quota_override: e.target.value })} /></Field>
            </div>
            <fieldset><legend className="label">Providers this company may choose</legend>
              {["brevo", "smtp"].map((p) => <label key={p} className="mr-4 text-sm"><input type="checkbox" checked={edit.allowed_providers.includes(p)} onChange={(e) => setEdit({ ...edit, allowed_providers: e.target.checked ? [...edit.allowed_providers, p] : edit.allowed_providers.filter((x) => x !== p) })} /> {p}</label>)}</fieldset>
          </form>)}
        </Modal>
        <Modal open={!!invite} onClose={() => setInvite(null)} title="Invite to this company" footer={<><button className="btn-secondary" onClick={() => setInvite(null)}>Cancel</button><button className="btn-primary" form="iv-form" disabled={saving}>Create invitation</button></>}>
          {invite && (<form id="iv-form" onSubmit={sendInvite} className="space-y-3">
            {errors.form && <Notice tone="error">{errors.form}</Notice>}
            <Field label="Email" htmlFor="iv-e" error={errors.email}><input id="iv-e" type="email" required className="input" value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} /></Field>
            <div className="grid grid-cols-2 gap-3"><Field label="First name" htmlFor="iv-f"><input id="iv-f" className="input" value={invite.first_name} onChange={(e) => setInvite({ ...invite, first_name: e.target.value })} /></Field><Field label="Last name" htmlFor="iv-l"><input id="iv-l" className="input" value={invite.last_name} onChange={(e) => setInvite({ ...invite, last_name: e.target.value })} /></Field></div>
            <Field label="Role" htmlFor="iv-r"><select id="iv-r" className="input" value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value })}><option value="company_admin">Company admin</option><option value="user">User</option></select></Field>
          </form>)}
        </Modal>
        <Modal open={!!link} onClose={() => setLink(null)} title="Single-use link" footer={<button className="btn-primary" onClick={() => setLink(null)}>Done</button>}>
          {link && (<div className="space-y-3"><Notice tone={link.emailed ? "ok" : "warn"}>{link.emailed ? `Emailed to ${link.email}.` : `No email was sent automatically. Give this link to ${link.email} yourself.`}</Notice>
            <input readOnly aria-label="Link" className="input" value={link.url} onFocus={(e) => e.target.select()} />
            <button className="btn-secondary" onClick={() => navigator.clipboard?.writeText(link.url).then(() => showToast("Link copied.", "success"))}>Copy link</button>
            <p className="text-xs text-slate-500">Expires in 7 days and works once. Shown only now.</p></div>)}
        </Modal>
        <ConfirmDialog open={!!confirm} onClose={() => setConfirm(null)} onConfirm={confirm?.run} title={confirm?.title} message={confirm?.message} danger={confirm?.danger !== false} confirmLabel="Confirm" />
      </div>)}</Async>
  );
}
