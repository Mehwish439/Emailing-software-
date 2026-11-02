import { Link } from "react-router-dom";

import useApi from "../../hooks/useApi";
import { platform } from "../../services/adminService";
import { Async, Notice, PageHeader, Tile, UsageBar, fmt, pct } from "../../components/admin/ui";

export default function PlatformOverview() {
  const state = useApi(platform.overview);
  return (
    <div className="space-y-6">
      <PageHeader title="Platform overview" subtitle="Capacity and activity across every company." actions={<Link to="/platform/companies" className="btn-primary">Manage companies</Link>} />
      <Async state={state}>{(d) => (<>
        {d.capacity.queue_paused && <Notice tone="error">The sending queue is PAUSED. Nothing is being submitted. <Link className="underline" to="/platform/queue">Open queue</Link></Notice>}
        {(d.capacity.needs_review > 0 || d.capacity.failed > 0) && <Notice tone="warn">{fmt(d.capacity.needs_review)} message(s) need review and {fmt(d.capacity.failed)} failed. <Link className="underline" to="/platform/queue">Review</Link></Notice>}
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Tile label="Companies" value={`${fmt(d.kpis.active_companies)} active / ${fmt(d.kpis.companies)}`} />
          <Tile label="Active users" value={fmt(d.kpis.users)} />
          <Tile label="Credits used today" value={fmt(d.kpis.processed_today)} />
          <Tile label="Campaigns running" value={fmt(d.kpis.active_campaigns)} />
          <Tile label="Queue backlog" value={fmt(d.kpis.queue_backlog)} />
          <Tile label="Delivery rate (24h)" value={pct(d.kpis.delivery_rate)} />
          <Tile label="Bounce rate (24h)" value={pct(d.kpis.bounce_rate)} />
          <Tile label="Complaints (24h)" value={fmt(d.kpis.complaints)} />
        </div>
        <div className="card p-5 space-y-4 max-w-3xl">
          <h2 className="font-semibold">Capacity</h2>
          <UsageBar label="Daily budget" used={d.capacity.daily_used} limit={d.capacity.daily_budget} />
          <UsageBar label="Monthly budget" used={d.capacity.monthly_used} limit={d.capacity.monthly_budget} />
          <p className="text-sm text-slate-600">Rate: {d.capacity.configured_rate_per_minute ? `${fmt(d.capacity.processed_this_minute)} of ${fmt(d.capacity.configured_rate_per_minute)} this minute` : "no software rate limit set"}{d.capacity.eta_minutes ? ` · backlog ETA ≈ ${fmt(d.capacity.eta_minutes)} min` : ""}</p>
          <p className="text-xs text-slate-500">{d.capacity.warning}</p>
        </div>
      </>)}</Async>
    </div>
  );
}
