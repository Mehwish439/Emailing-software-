import { useState } from "react";

import ConfirmDialog from "../../components/ConfirmDialog";
import Modal from "../../components/Modal";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/ToastContext";
import useApi, { useDebounced } from "../../hooks/useApi";
import { company } from "../../services/adminService";
import { fieldErrors, formatApiError } from "../../utils/formatError";
import { Async, Badge, DataTable, Field, Notice, PageFooter, PageHeader, SearchInput, fmt, limitText, when } from "../../components/admin/ui";

const blankInvite = { email: "", first_name: "", last_name: "", role: "user", daily_quota: "", monthly_quota: "" };
const toQuota = (v) => (v === "" || v === null || v === undefined ? null : Number(v));

export default function CompanyMembers() {
  const { user: me } = useAuth();
  const { showToast } = useToast();
  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  const [page, setPage] = useState(1);
  const state = useApi(() => company.members({ search: q || undefined, page }), [q, page]);

  const [invite, setInvite] = useState(null);       // form object or null
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [link, setLink] = useState(null);           // { email, url, emailed }
  const [edit, setEdit] = useState(null);
  const [confirm, setConfirm] = useState(null);     // { title, message, run }

  const submitInvite = async (e) => {
    e.preventDefault();
    setSaving(true); setErrors({});
    try {
      const r = await company.invite({ ...invite, email: invite.email.trim(), daily_quota: toQuota(invite.daily_quota), monthly_quota: toQuota(invite.monthly_quota) });
      setInvite(null); setLink({ email: r.user.email, url: r.invite_url, emailed: r.email_sent });
      state.reload();
    } catch (err) { setErrors({ ...fieldErrors(err), form: formatApiError(err, "Could not send the invitation.") }); }
    finally { setSaving(false); }
  };

  const submitEdit = async (e) => {
    e.preventDefault();
    setSaving(true); setErrors({});
    try {
      await company.updateMember(edit.id, { first_name: edit.first_name, last_name: edit.last_name, role: edit.role, daily_quota: toQuota(edit.daily_quota), monthly_quota: toQuota(edit.monthly_quota) });
      showToast("Member updated.", "success"); setEdit(null); state.reload();
    } catch (err) { setErrors({ form: formatApiError(err, "Could not update the member.") }); }
    finally { setSaving(false); }
  };

  const run = async (fn, okMsg) => {
    try { await fn(); showToast(okMsg, "success"); state.reload(); } catch (err) { showToast(formatApiError(err, "Action failed."), "error"); }
    setConfirm(null);
  };
  const resend = async (m) => {
    try { const r = await company.resendInvite(m.id); setLink({ email: m.email, url: r.invite_url, emailed: r.email_sent }); }
    catch (err) { showToast(formatApiError(err, "Could not resend the invitation."), "error"); }
  };

  const columns = [
    { key: "email", header: "User", render: (m) => (<div><p className="font-medium text-slate-900">{`${m.first_name} ${m.last_name}`.trim() || m.email}</p><p className="text-xs text-slate-500">{m.email}</p></div>) },
    { key: "role", header: "Role", render: (m) => <Badge value={m.role} label={m.role === "company_admin" ? "Company admin" : "User"} /> },
    { key: "is_active", header: "Status", render: (m) => m.invite_pending ? <Badge value="pending" label="Invite pending" /> : <Badge value={m.is_active ? "active" : "suspended"} label={m.is_active ? "Active" : "Deactivated"} /> },
    { key: "daily", header: "Today", render: (m) => `${fmt(m.daily_used)} / ${limitText(m.daily_quota)}` },
    { key: "monthly", header: "Month", render: (m) => `${fmt(m.monthly_used)} / ${limitText(m.monthly_quota)}` },
    { key: "last_login", header: "Last sign-in", render: (m) => when(m.last_login) },
    { key: "actions", header: "Actions", render: (m) => (
      <div className="flex flex-wrap gap-2">
        <button className="btn-secondary px-2 py-1" onClick={() => { setErrors({}); setEdit({ ...m, daily_quota: m.daily_quota ?? "", monthly_quota: m.monthly_quota ?? "" }); }}>Edit</button>
        {m.invite_pending && <button className="btn-secondary px-2 py-1" onClick={() => resend(m)}>Resend invite</button>}
        {m.active_campaigns > 0 && <button className="btn-secondary px-2 py-1" onClick={() => setConfirm({ title: "Pause campaigns", message: `Pause all running campaigns for ${m.email}?`, run: () => run(() => company.memberCampaigns(m.id, "pause"), "Campaigns paused.") })}>Pause campaigns</button>}
        {m.id !== me.id && <button className={m.is_active ? "btn-danger px-2 py-1" : "btn-secondary px-2 py-1"} onClick={() => setConfirm({ title: m.is_active ? "Deactivate user" : "Reactivate user", message: m.is_active ? `${m.email} will no longer be able to sign in. Their data is kept.` : `Reactivate ${m.email}? This uses a seat on your plan.`, danger: m.is_active, run: () => run(() => company.updateMember(m.id, { is_active: !m.is_active }), m.is_active ? "User deactivated." : "User reactivated.") })}>{m.is_active ? "Deactivate" : "Reactivate"}</button>}
      </div>) },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="Members & invitations" subtitle="Invite people to your company, set roles and per-user quotas. Per-user quotas are sub-limits inside your company allowance." actions={<button className="btn-primary" onClick={() => { setErrors({}); setInvite({ ...blankInvite }); }}>Invite user</button>} />
      <SearchInput value={search} onChange={(v) => { setSearch(v); setPage(1); }} placeholder="Search by name or email" />
      <div className="card"><Async state={state}>{(d) => (<><DataTable columns={columns} rows={d.results} empty="No members match." /><PageFooter data={d} onPage={setPage} /></>)}</Async></div>

      <Modal open={!!invite} onClose={() => setInvite(null)} title="Invite a user" footer={<><button className="btn-secondary" onClick={() => setInvite(null)}>Cancel</button><button className="btn-primary" form="invite-form" disabled={saving}>{saving ? "Sending…" : "Create invitation"}</button></>}>
        {invite && (
          <form id="invite-form" onSubmit={submitInvite} className="space-y-3">
            {errors.form && <Notice tone="error">{errors.form}</Notice>}
            <Field label="Email" htmlFor="inv-email" error={errors.email}><input id="inv-email" type="email" required className="input" value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="First name" htmlFor="inv-fn"><input id="inv-fn" className="input" value={invite.first_name} onChange={(e) => setInvite({ ...invite, first_name: e.target.value })} /></Field>
              <Field label="Last name" htmlFor="inv-ln"><input id="inv-ln" className="input" value={invite.last_name} onChange={(e) => setInvite({ ...invite, last_name: e.target.value })} /></Field>
            </div>
            <Field label="Role" htmlFor="inv-role"><select id="inv-role" className="input" value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value })}><option value="user">User</option><option value="company_admin">Company admin</option></select></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Daily quota" htmlFor="inv-dq" hint="Blank = no individual limit"><input id="inv-dq" type="number" min="0" className="input" value={invite.daily_quota} onChange={(e) => setInvite({ ...invite, daily_quota: e.target.value })} /></Field>
              <Field label="Monthly quota" htmlFor="inv-mq"><input id="inv-mq" type="number" min="0" className="input" value={invite.monthly_quota} onChange={(e) => setInvite({ ...invite, monthly_quota: e.target.value })} /></Field>
            </div>
          </form>)}
      </Modal>

      <Modal open={!!edit} onClose={() => setEdit(null)} title={`Edit ${edit?.email || ""}`} footer={<><button className="btn-secondary" onClick={() => setEdit(null)}>Cancel</button><button className="btn-primary" form="edit-form" disabled={saving}>{saving ? "Saving…" : "Save"}</button></>}>
        {edit && (
          <form id="edit-form" onSubmit={submitEdit} className="space-y-3">
            {errors.form && <Notice tone="error">{errors.form}</Notice>}
            <div className="grid grid-cols-2 gap-3">
              <Field label="First name" htmlFor="ed-fn"><input id="ed-fn" className="input" value={edit.first_name} onChange={(e) => setEdit({ ...edit, first_name: e.target.value })} /></Field>
              <Field label="Last name" htmlFor="ed-ln"><input id="ed-ln" className="input" value={edit.last_name} onChange={(e) => setEdit({ ...edit, last_name: e.target.value })} /></Field>
            </div>
            <Field label="Role" htmlFor="ed-role"><select id="ed-role" className="input" value={edit.role} onChange={(e) => setEdit({ ...edit, role: e.target.value })}><option value="user">User</option><option value="company_admin">Company admin</option></select></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Daily quota" htmlFor="ed-dq" hint="Blank = unlimited"><input id="ed-dq" type="number" min="0" className="input" value={edit.daily_quota} onChange={(e) => setEdit({ ...edit, daily_quota: e.target.value })} /></Field>
              <Field label="Monthly quota" htmlFor="ed-mq"><input id="ed-mq" type="number" min="0" className="input" value={edit.monthly_quota} onChange={(e) => setEdit({ ...edit, monthly_quota: e.target.value })} /></Field>
            </div>
          </form>)}
      </Modal>

      <Modal open={!!link} onClose={() => setLink(null)} title="Invitation link" footer={<button className="btn-primary" onClick={() => setLink(null)}>Done</button>}>
        {link && (<div className="space-y-3">
          <Notice tone={link.emailed ? "ok" : "warn"}>{link.emailed ? `An invitation email was sent to ${link.email}.` : `No email was sent automatically. Share this single-use link with ${link.email} yourself.`}</Notice>
          <input readOnly className="input" aria-label="Invitation link" value={link.url} onFocus={(e) => e.target.select()} />
          <button className="btn-secondary" onClick={() => navigator.clipboard?.writeText(link.url).then(() => showToast("Link copied.", "success"))}>Copy link</button>
          <p className="text-xs text-slate-500">The link expires after 7 days and stops working once the password is set. Treat it like a password: it is shown only once, and only when the email could not be sent.</p>
        </div>)}
      </Modal>

      <ConfirmDialog open={!!confirm} onClose={() => setConfirm(null)} onConfirm={confirm?.run} title={confirm?.title} message={confirm?.message} danger={confirm?.danger !== false} confirmLabel="Confirm" />
    </div>
  );
}
