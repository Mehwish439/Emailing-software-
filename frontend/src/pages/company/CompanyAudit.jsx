import { useState } from "react";

import useApi, { useDebounced } from "../../hooks/useApi";
import { company } from "../../services/adminService";
import { toDisplayText } from "../../utils/formatError";
import { Async, DataTable, PageFooter, PageHeader, SearchInput, when } from "../../components/admin/ui";

export default function CompanyAudit() {
  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  const [page, setPage] = useState(1);
  const state = useApi(() => company.audit({ search: q || undefined, page }), [q, page]);
  return (
    <div className="space-y-6">
      <PageHeader title="Activity log" subtitle="Administrative actions within your company." />
      <SearchInput value={search} onChange={(v) => { setSearch(v); setPage(1); }} placeholder="Filter by action, e.g. user.invited" />
      <div className="card"><Async state={state}>{(d) => (<><DataTable rows={d.results} empty="No activity recorded." columns={[
        { key: "created_at", header: "When", render: (r) => when(r.created_at) }, { key: "actor_email", header: "By" }, { key: "action", header: "Action" },
        { key: "target_type", header: "Target", render: (r) => r.target_type ? `${r.target_type} #${r.target_id}` : "—" },
        { key: "detail", header: "Detail", render: (r) => <code className="text-xs break-all">{toDisplayText(JSON.stringify(r.detail || {}))}</code> }]} /><PageFooter data={d} onPage={setPage} /></>)}</Async></div>
    </div>
  );
}
