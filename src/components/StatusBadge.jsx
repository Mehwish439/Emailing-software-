// Status pill with a leading dot. Colours are semantic: green = good/complete, amber = waiting, blue = in progress, red = problem.
const TONE = {
  green: ["bg-emerald-50 text-emerald-700", "bg-emerald-500"],
  amber: ["bg-amber-50 text-amber-700", "bg-amber-500"],
  blue: ["bg-sky-50 text-sky-700", "bg-sky-500"],
  indigo: ["bg-indigo-50 text-indigo-700", "bg-indigo-500"],
  purple: ["bg-violet-50 text-violet-700", "bg-violet-500"],
  red: ["bg-red-50 text-red-700", "bg-red-500"],
  slate: ["bg-slate-100 text-slate-600", "bg-slate-400"],
};

const MAP = {
  draft: "slate", scheduled: "amber", processing: "blue", sent: "green", cancelled: "slate", failed: "red",
  active: "green", unsubscribed: "slate", bounced: "red", blocked: "red", spam: "red", completed: "green",
  pending: "slate", delivered: "blue", opened: "indigo", clicked: "purple",
  paused: "amber", success: "green", skipped: "slate",
};

export default function StatusBadge({ status }) {
  const [cls, dot] = TONE[MAP[status] || "slate"];
  return (
    <span className={`badge ${cls} capitalize`}>
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      {String(status ?? "").replace(/_/g, " ")}
    </span>
  );
}
