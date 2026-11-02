import { company } from "../../services/adminService";
import useApi from "../../hooks/useApi";
import { Async, DataTable, Notice, PageHeader, Tile, UsageBar, fmt, limitText } from "../../components/admin/ui";

export default function CompanyQuotas() {
  const state = useApi(company.quotas);
  return (
    <div className="space-y-6">
      <PageHeader title="Quotas & usage" subtitle="One credit is used per recipient message. Credits are reserved when a campaign starts and released if a message is never submitted." />
      <Async state={state}>
        {(d) => (
          <>
            {d.over_allocated && <Notice tone="warn">Assigned user quotas exceed your company allowance. Lower some individual quotas.</Notice>}
            <div className="grid gap-4 sm:grid-cols-3">
              <Tile label="Company daily allowance" value={limitText(d.daily_limit)} />
              <Tile label="Assigned to users (daily)" value={fmt(d.assigned_daily)} />
              <Tile label="Unallocated (daily)" value={d.unallocated_daily === null ? "Unlimited" : fmt(d.unallocated_daily)} />
            </div>
            <div className="card p-5 space-y-4">
              <UsageBar label="Company — today" used={d.daily_used} limit={d.daily_limit} />
              <UsageBar label="Company — this month" used={d.monthly_used} limit={d.monthly_limit} />
              <ul className="text-xs text-slate-500 list-disc pl-5 space-y-1">{d.rules.map((r) => <li key={r}>{r}</li>)}</ul>
            </div>
            <div className="card">
              <DataTable rows={d.users} empty="No active members."
                columns={[
                  { key: "name", header: "User", render: (u) => <div><p className="font-medium">{u.name}</p><p className="text-xs text-slate-500">{u.email}</p></div> },
                  { key: "d", header: "Today", render: (u) => <div className="w-44"><UsageBar label="" used={u.daily_used} limit={u.daily_quota} /></div> },
                  { key: "m", header: "This month", render: (u) => <div className="w-44"><UsageBar label="" used={u.monthly_used} limit={u.monthly_quota} /></div> },
                ]} />
            </div>
          </>
        )}
      </Async>
    </div>
  );
}
