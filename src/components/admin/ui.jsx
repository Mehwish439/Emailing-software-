import { PageSkeleton } from "../Skeleton";
import Icon from "../Icon";
import SearchBar from "../SearchBar";
import EmptyState from "../EmptyState";
import { toDisplayText } from "../../utils/formatError";

export { default as PageHeader } from "../PageHeader";

/** Wraps a useApi result: spinner, actionable error with Retry, then children(data). */
export function Async({ state, children }) {
  if (state.loading && !state.data) return <PageSkeleton />;
  if (state.error && !state.data) {
    return (
      <div className="card p-8 text-center" role="alert">
        <span className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-red-50 text-red-600"><Icon name="alert" className="h-5 w-5" /></span>
        <p className="text-sm font-medium text-slate-900">We couldn’t load this page</p>
        <p className="mt-1 text-sm text-slate-500">{state.error}</p>
        <button className="btn-secondary mt-4" onClick={state.reload}><Icon name="refresh" className="h-4 w-4" /> Try again</button>
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
  const tones = { info: ["bg-sky-50 border-sky-200 text-sky-800", "info"], warn: ["bg-amber-50 border-amber-200 text-amber-800", "alert"], error: ["bg-red-50 border-red-200 text-red-700", "alert"], ok: ["bg-emerald-50 border-emerald-200 text-emerald-800", "checkCircle"] };
  const [cls, icon] = tones[tone] || tones.info;
  return <div role={tone === "error" ? "alert" : "status"} className={`flex items-start gap-3 rounded-xl border px-4 py-3 text-sm ${cls}`}><Icon name={icon} className="mt-0.5 h-4 w-4" /><div className="min-w-0 flex-1">{children}</div></div>;
}

export function Tile({ label, value, hint }) {
  return (
    <div className="card p-4 sm:p-5">
      <p className="text-[13px] font-medium text-slate-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold tabular-nums text-slate-900">{toDisplayText(value, "—")}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
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
        <span className="font-medium tabular-nums text-slate-900">{fmt(used)} / {limitText(limit)}</span></div>
      <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-slate-100" role="progressbar" aria-valuenow={p} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
        <div className={`h-2 rounded-full ${unlimited ? "bg-slate-200" : color} transition-all duration-500`} style={{ width: unlimited ? "100%" : `${Math.max(p, used ? 2 : 0)}%` }} />
      </div>
    </div>
  );
}

const G = "bg-emerald-50 text-emerald-700", A = "bg-amber-50 text-amber-700", B = "bg-sky-50 text-sky-700", R = "bg-red-50 text-red-700", S = "bg-slate-100 text-slate-600";
const BADGES = {
  active: G, suspended: R, trial: A, queued: S, submitting: B, accepted: "bg-indigo-50 text-indigo-700",
  deferred: A, delivered: G, bounced: R, failed: R, suppressed: "bg-slate-200 text-slate-700", cancelled: S,
  needs_review: "bg-orange-50 text-orange-700", processing: B, paused: A, sent: G, draft: S, scheduled: A, pending: A, ok: G, down: R,
};
export function Badge({ value, label }) {
  const key = String(value ?? "").toLowerCase();
  return <span className={`badge capitalize ${BADGES[key] || S}`}><span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" />{label || key.replace(/_/g, " ") || "—"}</span>;
}

/** Responsive table: scrolls horizontally on small screens. columns: [{key, header, render?, className?}] */
export function DataTable({ columns, rows, empty = "Nothing to show yet.", rowKey = "id" }) {
  if (!rows?.length) return <EmptyState title={empty} />;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 bg-slate-50/70 text-left text-xs text-slate-500">
            {columns.map((c) => <th key={c.key} scope="col" className={`px-4 py-3 font-medium whitespace-nowrap ${c.className || ""}`}>{c.header}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r, i) => (
            <tr key={r[rowKey] ?? i} className="transition-colors hover:bg-slate-50/80">
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
    <div className="flex items-center justify-between gap-3 border-t border-slate-100 px-4 py-3">
      <button className="btn-secondary btn-sm" disabled={data.page <= 1} onClick={() => onPage(data.page - 1)}><Icon name="chevronLeft" className="h-3.5 w-3.5" /> Previous</button>
      <span className="text-sm text-slate-500">Page {data.page} of {pages} · {data.count.toLocaleString()} total</span>
      <button className="btn-secondary btn-sm" disabled={data.page >= pages} onClick={() => onPage(data.page + 1)}>Next <Icon name="chevronRight" className="h-3.5 w-3.5" /></button>
    </div>
  );
}

export function SearchInput({ value, onChange, placeholder = "Search…" }) {
  return <SearchBar value={value} onChange={onChange} placeholder={placeholder} />;
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
