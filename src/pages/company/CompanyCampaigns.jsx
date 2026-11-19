import { useState } from "react";

import ConfirmDialog from "../../components/ConfirmDialog";
import { useToast } from "../../context/ToastContext";
import useApi from "../../hooks/useApi";
import { company } from "../../services/adminService";
import { formatApiError } from "../../utils/formatError";
import { Async, Badge, DataTable, PageFooter, PageHeader, fmt, pct } from "../../components/admin/ui";

const STATUSES = ["", "draft", "scheduled", "processing", "paused", "sent", "failed", "cancelled"];

export default function CompanyCampaigns() {
  const { showToast } = useToast();
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [confirm, setConfirm] = useState(null);
  const state = useApi(() => company.campaigns({ status: status || undefined, page }), [status, page]);

  const act = async () => {
    try { await company.campaignAction(confirm.id, confirm.action); showToast(`Campaign ${confirm.action}d.`, "success"); state.reload(); }
    catch (err) { showToast(formatApiError(err, "Action failed."), "error"); }
    setConfirm(null);
  };

  return (
    <div className="space-y-6">
      <PageHeader title="Campaign activity" subtitle="Every campaign created by members of your company. Failed or stalled campaigns appear here." />
      <div><label className="label" htmlFor="st">Status</label>
        <select id="st" className="input max-w-xs" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          {STATUSES.map((s) => <option key={s} value={s}>{s ? s : "All statuses"}</option>)}</select></div>
      <div className="card"><Async state={state}>{(d) => (<>
        <DataTable rows={d.results} empty="No campaigns match this filter." columns={[
          { key: "name", header: "Campaign", render: (c) => <div><p className="font-medium text-slate-900">{c.name}</p><p className="text-xs text-slate-500">{c.owner}</p></div> },
          { key: "status", header: "Status", render: (c) => <Badge value={c.status} /> },
          { key: "provider", header: "Provider", render: (c) => c.provider || "—" },
          { key: "recipients", header: "Recipients", render: (c) => fmt(c.recipients) },
          { key: "progress", header: "Progress", render: (c) => pct(c.progress) },
          { key: "accepted", header: "Accepted", render: (c) => fmt(c.accepted) },
          { key: "bounced", header: "Bounced", render: (c) => fmt(c.bounced) },
          { key: "open_rate", header: "Open rate", render: (c) => pct(c.open_rate) },
          { key: "a", header: "", render: (c) => c.status === "processing" ? <button className="btn-secondary px-2 py-1" onClick={() => setConfirm({ id: c.id, action: "pause", name: c.name })}>Pause</button> : c.status === "paused" ? <button className="btn-secondary px-2 py-1" onClick={() => setConfirm({ id: c.id, action: "resume", name: c.name })}>Resume</button> : null },
        ]} /><PageFooter data={d} onPage={setPage} /></>)}</Async></div>
      <ConfirmDialog open={!!confirm} onClose={() => setConfirm(null)} onConfirm={act} danger={false} title={`${confirm?.action === "pause" ? "Pause" : "Resume"} campaign`} message={`${confirm?.action === "pause" ? "Pause" : "Resume"} “${confirm?.name}”? Messages already submitted are not recalled.`} confirmLabel="Confirm" />
    </div>
  );
}
