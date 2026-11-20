const COLORS = ["bg-indigo-100 text-indigo-700", "bg-sky-100 text-sky-700", "bg-emerald-100 text-emerald-700", "bg-violet-100 text-violet-700", "bg-amber-100 text-amber-700", "bg-rose-100 text-rose-700"];

export default function Avatar({ name = "?", size = "h-9 w-9", text = "text-sm" }) {
  const letter = (name || "?").trim()[0]?.toUpperCase() || "?";
  const color = COLORS[(letter.charCodeAt(0) || 0) % COLORS.length];
  return <div className={`${size} ${text} ${color} flex shrink-0 items-center justify-center rounded-full font-semibold`} aria-hidden="true">{letter}</div>;
}
