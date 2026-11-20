import { useState } from "react";

import useApi, { useDebounced } from "../../hooks/useApi";
import { platform } from "../../services/adminService";
import { toDisplayText } from "../../utils/formatError";
import { Async, DataTable, PageFooter, PageHeader, SearchInput, when } from "../../components/admin/ui";

export default function PlatformAudit() {
  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  const [page, setPage] = useState(1);
  const state = useApi(() => platform.audit({ search: q || undefined, page }), [q, page]);
  return (
    <div className="space-y-6">
      <PageHeader title="Audit log" subtitle="Administrative actions across the platform." />
      <SearchInput value={search} onChange={(v) => { setSearch(v); setPage(1); }} placeholder="Filter by action, e.g. company.suspended" />
      <div className="card"><Async state={state}>{(d) => (<><DataTable rows={d.results} empty="No entries." columns={[
        { key: "created_at", header: "When", render: (r) => when(r.created_at) }, { key: "actor_email", header: "By" }, { key: "company_name", header: "Company", render: (r) => r.company_name || "—" }, { key: "action", header: "Action" },
        { key: "target", header: "Target", render: (r) => r.target_type ? `${r.target_type} #${r.target_id}` : "—" }, { key: "detail", header: "Detail", render: (r) => <code className="text-xs break-all">{toDisplayText(JSON.stringify(r.detail || {}))}</code> }]} /><PageFooter data={d} onPage={setPage} /></>)}</Async></div>
    </div>
  );
}
