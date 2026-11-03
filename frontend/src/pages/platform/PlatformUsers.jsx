import { useState } from "react";

import ConfirmDialog from "../../components/ConfirmDialog";
import Modal from "../../components/Modal";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/ToastContext";
import useApi, { useDebounced } from "../../hooks/useApi";
import { platform } from "../../services/adminService";
import { formatApiError } from "../../utils/formatError";
import { Async, Badge, DataTable, Notice, PageFooter, PageHeader, SearchInput, when } from "../../components/admin/ui";
import { ROLE_LABELS } from "../../utils/roles";

export default function PlatformUsers() {
  const { user: me } = useAuth();
  const { showToast } = useToast();
  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  const [active, setActive] = useState("");
  const [page, setPage] = useState(1);
  const state = useApi(() => platform.users({ search: q || undefined, active: active || undefined, page }), [q, active, page]);
  const [confirm, setConfirm] = useState(null);
  const [link, setLink] = useState(null);

  const toggle = async () => {
    try { await platform.userAction(confirm.id, confirm.action); showToast("User updated.", "success"); state.reload(); } catch (err) { showToast(formatApiError(err, "Action failed."), "error"); }
    setConfirm(null);
  };
  const reset = async (u) => { try { const r = await platform.userAction(u.id, "reset-invite"); setLink({ email: u.email, url: r.invite_url, emailed: r.email_sent }); } catch (err) { showToast(formatApiError(err, "Could not create a link."), "error"); } };

  return (
    <div className="space-y-6">
      <PageHeader title="Users" subtitle="All accounts on the platform. Contact data of other companies is never shown here." />
      <div className="flex flex-wrap items-end gap-3">
        <SearchInput value={search} onChange={(v) => { setSearch(v); setPage(1); }} placeholder="Search by email" />
        <select aria-label="Status" className="input max-w-[10rem]" value={active} onChange={(e) => { setActive(e.target.value); setPage(1); }}><option value="">All</option><option value="true">Active</option><option value="false">Deactivated</option></select>
      </div>
      <div className="card"><Async state={state}>{(d) => (<><DataTable rows={d.results} empty="No users match." columns={[
        { key: "email", header: "User", render: (u) => <div><p className="font-medium">{`${u.first_name} ${u.last_name}`.trim() || u.email}</p><p className="text-xs text-slate-500">{u.email}</p></div> },
        { key: "company", header: "Company", render: (u) => u.company || "— (no company)" }, { key: "role", header: "Role", render: (u) => ROLE_LABELS[u.role] || u.role },
        { key: "s", header: "Status", render: (u) => u.invite_pending ? <Badge value="pending" label="Invite pending" /> : <Badge value={u.is_active ? "active" : "suspended"} label={u.is_active ? "Active" : "Deactivated"} /> },
        { key: "last_login", header: "Last sign-in", render: (u) => when(u.last_login) },
        { key: "a", header: "Actions", render: (u) => (<div className="flex gap-2"><button className="btn-secondary px-2 py-1" onClick={() => reset(u)}>{u.invite_pending ? "Resend invite" : "Reset link"}</button>
          {u.id !== me.id && <button className={u.is_active ? "btn-danger px-2 py-1" : "btn-secondary px-2 py-1"} onClick={() => setConfirm({ id: u.id, action: u.is_active ? "deactivate" : "activate", email: u.email })}>{u.is_active ? "Deactivate" : "Activate"}</button>}</div>) }]} /><PageFooter data={d} onPage={setPage} /></>)}</Async></div>
      <ConfirmDialog open={!!confirm} onClose={() => setConfirm(null)} onConfirm={toggle} danger={confirm?.action === "deactivate"} title={`${confirm?.action === "deactivate" ? "Deactivate" : "Activate"} user`} message={`${confirm?.action === "deactivate" ? "Deactivate" : "Activate"} ${confirm?.email}?`} confirmLabel="Confirm" />
      <Modal open={!!link} onClose={() => setLink(null)} title="Single-use link" footer={<button className="btn-primary" onClick={() => setLink(null)}>Done</button>}>
        {link && (<div className="space-y-3"><Notice tone={link.emailed ? "ok" : "warn"}>{link.emailed ? `The email provider accepted the message for ${link.email}. It can still land in spam or fail to arrive - if so, send them the link below yourself.` : `No email was sent automatically. Send this link to ${link.email} yourself.`}</Notice>
          <input readOnly aria-label="Link" className="input" value={link.url} onFocus={(e) => e.target.select()} />
          <button className="btn-secondary" onClick={() => navigator.clipboard?.writeText(link.url).then(() => showToast("Link copied.", "success"))}>Copy link</button>
          <p className="text-xs text-slate-500">Expires in 7 days; works once. Keep it private.</p></div>)}
      </Modal>
    </div>
  );
}