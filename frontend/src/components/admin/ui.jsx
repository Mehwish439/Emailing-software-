import Spinner from "../Spinner";
import EmptyState from "../EmptyState";
import { toDisplayText } from "../../utils/formatError";

export function PageHeader({ title, subtitle, actions }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">{title}</h1>
        {subtitle && <p className="text-sm text-slate-500 mt-1 max-w-3xl">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

/** Wraps a useApi result: spinner, actionable error with Retry, then children(data). */
export function Async({ state, children }) {
  if (state.loading && !state.data) return <div className="flex justify-center py-16"><Spinner size="lg" /></div>;
  if (state.error && !state.data) {
    return (
      <div className="card p-6 text-center" role="alert">
        <p className="text-sm text-red-700">{state.error}</p>
        <button className="btn-secondary mt-3" onClick={state.reload}>Retry</button>
      </div>
    );
  }
  return state.data ? children(state.data) : null;
}

export const fmt = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString());
export const pct = (n) => (n === null || n === undefined ? "n/a" : `${n}%`);
export const when = (iso) => (iso ? new Date(iso).toLocaleString() : "—");
export const limitText = (n) => (n === null || n === undefined ? "Unlimited" : Number(n).toLocaleString());

export function Notice({ tone = "info", children }) {
  const tones = { info: "bg-blue-50 border-blue-200 text-blue-800", warn: "bg-amber-50 border-amber-200 text-amber-800", error: "bg-red-50 border-red-200 text-red-700", ok: "bg-emerald-50 border-emerald-200 text-emerald-800" };
  return <div role={tone === "error" ? "alert" : "status"} className={`rounded-lg border px-4 py-3 text-sm ${tones[tone]}`}>{children}</div>;
}

export function Tile({ label, value, hint }) {
  return (
    <div className="card p-5">
      <p className="text-sm font-medium text-slate-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-slate-900">{toDisplayText(value, "—")}</p>
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
    </div>
  );
}

/** Usage bar: used vs limit. Unlimited (null) shows only the count. */
export function UsageBar({ label, used, limit }) {
  const unlimited = limit === null || limit === undefined;
  const p = unlimited || !limit ? 0 : Math.min(100, Math.round((100 * used) / limit));
  const color = p >= 90 ? "bg-red-500" : p >= 70 ? "bg-amber-500" : "bg-brand-500";
  return (
    <div>
      <div className="flex justify-between text-sm"><span className="text-slate-600">{label}</span>
        <span className="text-slate-900 font-medium">{fmt(used)} / {limitText(limit)}</span></div>
      <div className="mt-1 h-2 rounded-full bg-slate-100" role="progressbar" aria-valuenow={p} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
        <div className={`h-2 rounded-full ${unlimited ? "bg-slate-300" : color}`} style={{ width: unlimited ? "100%" : `${p}%` }} />
      </div>
    </div>
  );
}

const BADGES = {
  active: "bg-emerald-100 text-emerald-800", suspended: "bg-red-100 text-red-700", trial: "bg-amber-100 text-amber-800",
  queued: "bg-slate-100 text-slate-700", submitting: "bg-blue-100 text-blue-800", accepted: "bg-indigo-100 text-indigo-800",
  deferred: "bg-amber-100 text-amber-800", delivered: "bg-emerald-100 text-emerald-800", bounced: "bg-red-100 text-red-700",
  failed: "bg-red-100 text-red-700", suppressed: "bg-slate-200 text-slate-700", cancelled: "bg-slate-100 text-slate-500",
  needs_review: "bg-orange-100 text-orange-800", processing: "bg-blue-100 text-blue-800", paused: "bg-amber-100 text-amber-800",
  sent: "bg-emerald-100 text-emerald-800", draft: "bg-slate-100 text-slate-700", scheduled: "bg-amber-100 text-amber-800",
  pending: "bg-amber-100 text-amber-800", ok: "bg-emerald-100 text-emerald-800", down: "bg-red-100 text-red-700",
};
export function Badge({ value, label }) {
  const key = String(value ?? "").toLowerCase();
  return <span className={`badge ${BADGES[key] || "bg-slate-100 text-slate-700"}`}>{label || key.replace(/_/g, " ") || "—"}</span>;
}

/** Responsive table: scrolls horizontally on small screens. columns: [{key, header, render?, className?}] */
export function DataTable({ columns, rows, empty = "Nothing to show yet.", rowKey = "id" }) {
  if (!rows?.length) return <EmptyState title={empty} />;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
            {columns.map((c) => <th key={c.key} scope="col" className={`px-4 py-3 font-semibold ${c.className || ""}`}>{c.header}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r, i) => (
            <tr key={r[rowKey] ?? i} className="hover:bg-slate-50">
              {columns.map((c) => <td key={c.key} className={`px-4 py-3 align-middle text-slate-700 ${c.className || ""}`}>{c.render ? c.render(r) : toDisplayText(r[c.key], "—")}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Server-paginated footer for { count, page, page_size } responses. */
export function PageFooter({ data, onPage }) {
  if (!data || data.count <= data.page_size) return null;
  const pages = Math.ceil(data.count / data.page_size);
  return (
    <div className="flex items-center justify-between border-t border-slate-200 px-4 py-3">
      <button className="btn-secondary" disabled={data.page <= 1} onClick={() => onPage(data.page - 1)}>Previous</button>
      <span className="text-sm text-slate-500">Page {data.page} of {pages} · {data.count.toLocaleString()} total</span>
      <button className="btn-secondary" disabled={data.page >= pages} onClick={() => onPage(data.page + 1)}>Next</button>
    </div>
  );
}

export function SearchInput({ value, onChange, placeholder = "Search…" }) {
  return <input type="search" aria-label={placeholder} className="input max-w-xs" placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)} />;
}

export function Field({ label, error, hint, children, htmlFor }) {
  return (
    <div>
      <label className="label" htmlFor={htmlFor}>{label}</label>
      {children}
      {hint && !error && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
      {error && <p className="mt-1 text-xs text-red-600" role="alert">{error}</p>}
    </div>
  );
}
