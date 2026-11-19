import Icon from "./Icon";

const TONES = {
  brand: "bg-brand-50 text-brand-600",
  green: "bg-emerald-50 text-emerald-600",
  amber: "bg-amber-50 text-amber-600",
  red: "bg-red-50 text-red-600",
  slate: "bg-slate-100 text-slate-600",
  sky: "bg-sky-50 text-sky-600",
  violet: "bg-violet-50 text-violet-600",
};

/**
 * Metric card. `icon` may be an Icon name (string) or any node. `hint` is a small caption under the value.
 * When `onClick` is given the card behaves as a button (keyboard accessible) and `active` highlights it.
 */
export default function StatCard({ label, value, icon, tone = "brand", hint, onClick, active = false, accent }) {
  const clickable = typeof onClick === "function";
  const props = clickable
    ? { role: "button", tabIndex: 0, onClick, onKeyDown: (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onClick(e)) }
    : {};
  return (
    <div
      {...props}
      className={`card p-4 sm:p-5 transition ${clickable ? "cursor-pointer hover:border-brand-300 hover:shadow-pop focus-visible:ring-2" : ""} ${active ? "border-brand-500 ring-2 ring-brand-500/30" : ""}`}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-[13px] font-medium text-slate-500">{label}</p>
        {icon && (
          <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${TONES[tone] || TONES.brand} ${accent || ""}`}>
            {typeof icon === "string" ? <Icon name={icon} className="h-4 w-4" /> : icon}
          </span>
        )}
      </div>
      <p className="mt-2 text-2xl font-semibold tabular-nums text-slate-900">{typeof value === "number" ? value.toLocaleString() : value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}
