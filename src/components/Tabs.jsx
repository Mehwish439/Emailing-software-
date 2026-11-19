/** Underlined tab bar. tabs: [{ key, label, count? }] */
export default function Tabs({ tabs, value, onChange, className = "" }) {
  return (
    <div role="tablist" className={`flex gap-1 overflow-x-auto border-b border-slate-200 scroll-thin ${className}`}>
      {tabs.map((t) => {
        const active = t.key === value;
        return (
          <button key={t.key} role="tab" aria-selected={active} onClick={() => onChange(t.key)}
            className={`-mb-px whitespace-nowrap border-b-2 px-3 py-2.5 text-sm font-medium transition ${active ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
            {t.label}
            {t.count != null && <span className={`ml-2 rounded-full px-1.5 py-0.5 text-xs ${active ? "bg-brand-50 text-brand-700" : "bg-slate-100 text-slate-500"}`}>{t.count}</span>}
          </button>
        );
      })}
    </div>
  );
}
