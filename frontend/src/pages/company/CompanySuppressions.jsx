import { useState } from "react";

import useApi from "../../hooks/useApi";
import { company } from "../../services/adminService";
import { Async, Badge, DataTable, Notice, PageFooter, PageHeader, when } from "../../components/admin/ui";

export default function CompanySuppressions() {
  const [reason, setReason] = useState("");
  const [page, setPage] = useState(1);
  const state = useApi(() => company.suppressions({ reason: reason || undefined, page }), [reason, page]);
  return (
    <div className="space-y-6">
      <PageHeader title="Suppressions" subtitle="Addresses that will never be emailed (bounces, complaints, unsubscribes). Only addresses that match your own contacts are shown." />
      <Notice>Suppression is platform-wide for safety: an address suppressed by any company is not emailed by any company.</Notice>
      <div><label className="label" htmlFor="reason">Reason</label>
        <select id="reason" className="input max-w-xs" value={reason} onChange={(e) => { setReason(e.target.value); setPage(1); }}>
          <option value="">All reasons</option>{["hard_bounce", "soft_bounce_limit", "unsubscribed", "spam_complaint", "manual", "blocked"].map((r) => <option key={r} value={r}>{r.replace(/_/g, " ")}</option>)}</select></div>
      <div className="card"><Async state={state}>{(d) => (<><DataTable rows={d.results} rowKey="email" empty="No suppressed addresses." columns={[
        { key: "email", header: "Email" }, { key: "reason", header: "Reason", render: (r) => <Badge value={r.reason} /> }, { key: "created_at", header: "Added", render: (r) => when(r.created_at) }]} /><PageFooter data={d} onPage={setPage} /></>)}</Async></div>
    </div>
  );
}
