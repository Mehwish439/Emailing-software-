import { useState } from "react";

import ConfirmDialog from "../../components/ConfirmDialog";
import { useToast } from "../../context/ToastContext";
import useApi from "../../hooks/useApi";
import { platform } from "../../services/adminService";
import { formatApiError } from "../../utils/formatError";
import { Async, Badge, DataTable, PageFooter, PageHeader, fmt } from "../../components/admin/ui";

const STATUSES = ["", "draft", "scheduled", "processing", "paused", "sent", "failed", "cancelled"];

export default function PlatformCampaigns() {
  const { showToast } = useToast();
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const state = useApi(() => platform.campaigns({ status: status || undefined, page }), [status, page]);
  const [confirm, setConfirm] = useState(null);
  const run = async () => { try { await platform.campaignAction(confirm.id, confirm.action, confirm.body); showToast("Done.", "success"); state.reload(); } catch (err) { showToast(formatApiError(err, "Action failed."), "error"); } setConfirm(null); };
  return (
    <div className="space-y-6">
      <PageHeader title="Campaign monitor" subtitle="Campaign names and counts only. Contact data of other companies is not exposed." />
      <select aria-label="Status" className="input max-w-xs" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>{STATUSES.map((s) => <option key={s} value={s}>{s || "All statuses"}</option>)}</select>
      <div className="card"><Async state={state}>{(d) => (<><DataTable rows={d.results} empty="No campaigns match." columns={[
        { key: "name", header: "Campaign", render: (c) => <div><p className="font-medium">{c.name}</p><p className="text-xs text-slate-500">{c.owner}</p></div> }, { key: "company", header: "Company", render: (c) => c.company || "—" },
        { key: "status", header: "Status", render: (c) => <Badge value={c.status} /> }, { key: "provider", header: "Provider", render: (c) => c.provider || "—" }, { key: "recipients", header: "Recipients", render: (c) => fmt(c.recipients) },
        { key: "a", header: "", render: (c) => c.status === "processing" ? <button className="btn-secondary px-2 py-1" onClick={() => setConfirm({ id: c.id, action: "pause", name: c.name })}>Pause</button> : c.status === "paused" ? <button className="btn-secondary px-2 py-1" onClick={() => setConfirm({ id: c.id, action: "resume", name: c.name })}>Resume</button> : null }]} /><PageFooter data={d} onPage={setPage} /></>)}</Async></div>
      <ConfirmDialog open={!!confirm} onClose={() => setConfirm(null)} onConfirm={run} danger={false} title={`${confirm?.action === "pause" ? "Pause" : "Resume"} campaign`} message={`${confirm?.action === "pause" ? "Pause" : "Resume"} “${confirm?.name}”?`} confirmLabel="Confirm" />
    </div>
  );
}
