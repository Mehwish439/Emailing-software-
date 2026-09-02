const COLOR_MAP = {
  draft: "bg-slate-100 text-slate-700",
  scheduled: "bg-amber-100 text-amber-800",
  processing: "bg-blue-100 text-blue-800",
  sent: "bg-emerald-100 text-emerald-800",
  cancelled: "bg-slate-100 text-slate-500",
  failed: "bg-red-100 text-red-700",
  active: "bg-emerald-100 text-emerald-800",
  unsubscribed: "bg-slate-100 text-slate-600",
  bounced: "bg-red-100 text-red-700",
  blocked: "bg-red-100 text-red-700",
  spam: "bg-red-100 text-red-700",
  completed: "bg-emerald-100 text-emerald-800",
  pending: "bg-slate-100 text-slate-600",
  delivered: "bg-blue-100 text-blue-800",
  opened: "bg-indigo-100 text-indigo-800",
  clicked: "bg-purple-100 text-purple-800",
};

export default function StatusBadge({ status }) {
  const color = COLOR_MAP[status] || "bg-slate-100 text-slate-700";
  return <span className={`badge ${color} capitalize`}>{status}</span>;
}
