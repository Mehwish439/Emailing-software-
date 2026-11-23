import { providerLabel } from "../utils/providers";
import { fmt, limitText } from "./admin/ui";

/**
 * Messages sent per email provider, from the backend's `by_provider` figures (our own quota ledger).
 * `available` (optional) marks which providers the account/company may use. `showLimits` is for the
 * platform-wide view only: provider allowances are platform guards, not per-company limits.
 */
export default function ProviderUsage({ data, available, showLimits = false, title = "Usage by provider" }) {
  if (!data) return null;
  return (
    <div className="card p-5 max-w-3xl overflow-x-auto">
      <h2 className="font-semibold mb-2">{title}</h2>
      <table className="w-full text-sm">
        <thead><tr className="text-left text-xs text-slate-500">
          <th className="pb-1">Provider</th>{available && <th>Access</th>}<th>Today</th><th>This month</th>
        </tr></thead>
        <tbody>
          {Object.entries(data).map(([name, u]) => (
            <tr key={name} className="border-t border-slate-100">
              <td className="py-1.5 font-medium">{providerLabel(name)}</td>
              {available && <td className={available.includes(name) ? "text-emerald-700" : "text-slate-400"}>{available.includes(name) ? "Assigned" : "Not assigned"}</td>}
              <td>{fmt(u.daily_used)}{showLimits ? ` / ${limitText(u.daily_limit)}` : ""}</td>
              <td>{fmt(u.monthly_used)}{showLimits ? ` / ${limitText(u.monthly_limit)}` : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {showLimits && <p className="mt-2 text-xs text-slate-500">Limits are guards you set from your provider plan (e.g. SENDPULSE_DAILY_LIMIT); “Unlimited” means none is configured.</p>}
    </div>
  );
}
