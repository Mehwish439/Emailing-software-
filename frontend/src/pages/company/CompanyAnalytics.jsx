import { useState } from "react";

import useApi from "../../hooks/useApi";
import { company } from "../../services/adminService";
import { Async, DataTable, Notice, PageHeader, Tile, fmt, pct } from "../../components/admin/ui";

export default function CompanyAnalytics() {
  const [days, setDays] = useState(30);
  const state = useApi(() => company.analytics({ days }), [days]);
  const cols = [
    { key: "accepted", header: "Accepted", render: (r) => fmt(r.accepted) }, { key: "delivered", header: "Delivered", render: (r) => fmt(r.delivered) },
    { key: "bounced", header: "Bounced", render: (r) => fmt(r.bounced) }, { key: "open_rate", header: "Open rate", render: (r) => pct(r.open_rate) },
    { key: "click_rate", header: "Click rate", render: (r) => pct(r.click_rate) }, { key: "complaints", header: "Complaints", render: (r) => fmt(r.complaints) },
  ];
  return (
    <div className="space-y-6">
      <PageHeader title="Company analytics" actions={<select aria-label="Period" className="input" value={days} onChange={(e) => setDays(Number(e.target.value))}>{[7, 30, 90, 365].map((d) => <option key={d} value={d}>Last {d} days</option>)}</select>} />
      <Async state={state}>{(d) => (<>
        <Notice>{d.note}</Notice>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Tile label="Accepted by provider" value={fmt(d.totals.accepted)} /><Tile label="Delivered (events)" value={fmt(d.totals.delivered)} hint={pct(d.totals.delivery_rate)} />
          <Tile label="Bounced" value={fmt(d.totals.bounced)} hint={`${fmt(d.totals.hard_bounces)} hard · ${fmt(d.totals.soft_bounces)} soft`} /><Tile label="Unsubscribes / complaints" value={`${fmt(d.totals.unsubscribes)} / ${fmt(d.totals.complaints)}`} />
        </div>
        <div className="card"><h2 className="px-4 pt-4 font-semibold">By user</h2><DataTable rows={d.by_user} empty="No activity in this period." rowKey="user" columns={[{ key: "user", header: "User" }, ...cols]} /></div>
        <div className="card"><h2 className="px-4 pt-4 font-semibold">Top campaigns by open rate</h2><DataTable rows={d.campaigns} empty="No campaigns in this period." rowKey="campaign" columns={[{ key: "campaign", header: "Campaign" }, { key: "owner", header: "Owner" }, ...cols]} /></div>
      </>)}</Async>
    </div>
  );
}
