import { useEffect, useState } from "react";

import { fetchCurrentUser } from "../services/authService";
import { UsageBar } from "./admin/ui";
import Icon from "./Icon";
import { Skeleton } from "./Skeleton";

/** The signed-in user's own sending limits (read-only; set by a company or platform admin). */
export default function QuotaCard({ className = "" }) {
  const [q, setQ] = useState(undefined);
  useEffect(() => { fetchCurrentUser().then((u) => setQ(u.quota || null)).catch(() => setQ(null)); }, []);
  if (q === null) return null;
  if (q === undefined) return <div className={`card p-5 space-y-3 ${className}`}><Skeleton className="h-4 w-1/3" /><Skeleton className="h-2 w-full" /><Skeleton className="h-2 w-full" /></div>;
  const rows = [["Your daily limit", q.user.daily_used, q.user.daily_limit], ["Your monthly limit", q.user.monthly_used, q.user.monthly_limit]];
  if (q.company) rows.push(["Company daily allowance", q.company.daily_used, q.company.daily_limit], ["Company monthly allowance", q.company.monthly_used, q.company.monthly_limit]);
  return (
    <div className={`card ${className}`} aria-label="Sending usage">
      <div className="card-header">
        <h2 className="card-title">Sending quota &amp; usage</h2>
        <Icon name="activity" className="h-4 w-4 text-slate-400" />
      </div>
      <div className="space-y-4 p-5">
        {rows.map(([label, used, limit]) => <UsageBar key={label} label={label} used={used} limit={limit} />)}
        <p className="text-xs text-slate-500">One credit is used per recipient. A campaign that would exceed a limit is rejected before it starts. “Unlimited” means no limit has been set.</p>
      </div>
    </div>
  );
}
