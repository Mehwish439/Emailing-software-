import { useEffect, useState } from "react";

import { fetchCurrentUser } from "../services/authService";
import { UsageBar } from "./admin/ui";

/** The signed-in user's own sending limits (read-only; set by a company or platform admin). */
export default function QuotaCard() {
  const [q, setQ] = useState(null);
  useEffect(() => { fetchCurrentUser().then((u) => setQ(u.quota)).catch(() => setQ(null)); }, []);
  if (!q) return null;
  const rows = [["Your daily limit", q.user.daily_used, q.user.daily_limit], ["Your monthly limit", q.user.monthly_used, q.user.monthly_limit]];
  if (q.company) rows.push(["Company daily allowance", q.company.daily_used, q.company.daily_limit], ["Company monthly allowance", q.company.monthly_used, q.company.monthly_limit]);
  return (
    <div className="card p-5 space-y-3 max-w-xl" aria-label="Sending usage">
      <h2 className="font-semibold text-slate-900">Sending usage</h2>
      {rows.map(([label, used, limit]) => <UsageBar key={label} label={label} used={used} limit={limit} />)}
      <p className="text-xs text-slate-500">One credit is used per recipient. A campaign that would exceed a limit is rejected before it starts. “Unlimited” means no limit has been set for you.</p>
    </div>
  );
}
