import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { company } from "../../services/adminService";
import useApi from "../../hooks/useApi";
import { Async, Notice, PageHeader, Tile, UsageBar, fmt, pct } from "../../components/admin/ui";

export default function CompanyOverview() {
  const state = useApi(company.overview);
  return (
    <div className="space-y-6">
      <PageHeader title="Company overview" subtitle="Usage, team and delivery for your company only." actions={<Link className="btn-primary" to="/company/members">Invite a user</Link>} />
      <Async state={state}>
        {(d) => (
          <>
            {d.company.status === "suspended" && <Notice tone="error">This company is suspended: new sends are refused and running campaigns are held. Contact your platform administrator.</Notice>}
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <Tile label="Accepted today" value={fmt(d.kpis.sent_today)} hint="Accepted by a provider ≠ inbox delivery" />
              <Tile label="Daily allowance left" value={d.kpis.daily_remaining === null ? "Unlimited" : fmt(d.kpis.daily_remaining)} />
              <Tile label="Active members" value={`${fmt(d.kpis.active_members)}${d.kpis.max_users ? ` / ${d.kpis.max_users}` : ""}`} />
              <Tile label="Campaigns running" value={fmt(d.kpis.campaigns_running)} />
            </div>
            <div className="grid gap-6 lg:grid-cols-2">
              <div className="card p-5 space-y-4">
                <h2 className="font-semibold text-slate-900">Quota</h2>
                <UsageBar label="Today" used={d.quota.daily_used} limit={d.quota.daily_limit} />
                <UsageBar label="This month" used={d.quota.monthly_used} limit={d.quota.monthly_limit} />
                <p className="text-xs text-slate-500">{fmt(d.quota.queued_messages)} message(s) queued. {d.quota.note}</p>
              </div>
              <div className="card p-5">
                <h2 className="font-semibold text-slate-900 mb-3">Last 7 days (recorded events)</h2>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>Delivery rate: <b>{pct(d.kpis.delivery_rate)}</b></div><div>Bounce rate: <b>{pct(d.kpis.bounce_rate)}</b></div>
                  <div>Open rate: <b>{pct(d.kpis.open_rate)}</b></div><div>Click rate: <b>{pct(d.kpis.click_rate)}</b></div>
                </div>
                <p className="mt-3 text-xs text-slate-500">“n/a” means no messages yet, not zero.</p>
              </div>
            </div>
            <div className="card p-5">
              <h2 className="font-semibold text-slate-900 mb-3">Messages accepted per day</h2>
              <div className="h-56" role="img" aria-label="Bar chart of messages accepted per day for the last 7 days">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={d.series}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="date" fontSize={12} /><YAxis allowDecimals={false} fontSize={12} /><Tooltip /><Bar dataKey="sent" fill="#3d63f7" radius={[4, 4, 0, 0]} /></BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </>
        )}
      </Async>
    </div>
  );
}
