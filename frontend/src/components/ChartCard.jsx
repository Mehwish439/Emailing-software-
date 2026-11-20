/** Consistent container for Recharts visuals: title, optional subtitle/actions, fixed-height body. */
export default function ChartCard({ title, subtitle, actions, height = "h-72", children, empty, className = "" }) {
  return (
    <div className={`card ${className}`}>
      <div className="card-header">
        <div>
          <h2 className="card-title">{title}</h2>
          {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
        </div>
        {actions}
      </div>
      <div className={`p-5 ${height}`}>
        {empty ? <div className="flex h-full items-center justify-center text-sm text-slate-500">{empty}</div> : children}
      </div>
    </div>
  );
}

export const CHART_COLORS = { primary: "#4f46e5", sky: "#0ea5e9", green: "#10b981", amber: "#f59e0b", red: "#ef4444", violet: "#8b5cf6", slate: "#94a3b8", grid: "#e2e8f0" };

export const chartTooltipStyle = { borderRadius: 10, border: "1px solid #e2e8f0", boxShadow: "0 10px 30px -8px rgba(15,23,42,0.18)", fontSize: 12 };
