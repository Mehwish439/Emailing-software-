export default function StatCard({ label, value, icon, accent = "text-brand-600", onClick, active = false }) {
  const clickable = typeof onClick === "function";
  return (
    <div
      className={`card p-5 ${clickable ? "cursor-pointer transition hover:shadow-md" : ""} ${
        active ? "ring-2 ring-brand-500" : ""
      }`}
      onClick={onClick}
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
    >
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-slate-500">{label}</p>
        {icon && <span className={`${accent}`}>{icon}</span>}
      </div>
      <p className="mt-2 text-2xl font-semibold text-slate-900">{value}</p>
    </div>
  );
}
