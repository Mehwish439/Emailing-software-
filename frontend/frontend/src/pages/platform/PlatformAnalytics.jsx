import { useState } from "react";

import useApi from "../../hooks/useApi";
import { platform } from "../../services/adminService";
import { Async, DataTable, PageHeader, Tile, fmt, pct } from "../../components/admin/ui";

export default function PlatformAnalytics() {
  const [days, setDays] = useState(30);
  const state = useApi(() => platform.analytics({ days }), [days]);
  return (
    <div className="space-y-6">
      <PageHeader title="Platform analytics" actions={<select aria-label="Period" className="input" value={days} onChange={(e) => setDays(Number(e.target.value))}>{[7, 30, 90, 365].map((d) => <option key={d} value={d}>Last {d} days</option>)}</select>} />
      <Async state={state}>{(d) => (<>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Tile label="Accepted" value={fmt(d.totals.accepted)} /><Tile label="Delivered (events)" value={fmt(d.totals.delivered)} hint={pct(d.totals.delivery_rate)} />
          <Tile label="Bounce rate" value={pct(d.totals.bounce_rate)} /><Tile label="Complaints" value={fmt(d.totals.complaints)} />
        </div>
        <div className="card"><h2 className="px-4 pt-4 font-semibold">By company</h2><DataTable rows={d.companies} rowKey="company" empty="No data." columns={[
          { key: "company", header: "Company" }, { key: "accepted", header: "Accepted", render: (r) => fmt(r.accepted) }, { key: "delivered", header: "Delivered", render: (r) => fmt(r.delivered) },
          { key: "bounce_rate", header: "Bounce rate", render: (r) => pct(r.bounce_rate) }, { key: "open_rate", header: "Open rate", render: (r) => pct(r.open_rate) }, { key: "complaints", header: "Complaints", render: (r) => fmt(r.complaints) }]} /></div>
      </>)}</Async>
    </div>
  );
}
