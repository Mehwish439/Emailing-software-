import Icon from "./Icon";

export function BrandMark({ className = "" }) {
  return (
    <div className={`flex items-center justify-center gap-2.5 ${className}`}>
      <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-base font-bold text-white shadow-sm">Q</div>
      <span className="text-lg font-semibold tracking-tight text-slate-900">QRM Campaigns</span>
    </div>
  );
}

const POINTS = [
  { icon: "send", title: "Campaigns that reach the inbox", text: "Build, preview, schedule and send from one place." },
  { icon: "users", title: "Audiences you control", text: "Lists, tags and segments keep every send relevant." },
  { icon: "bolt", title: "Automation that runs itself", text: "Trigger follow-ups from sign-ups and behaviour." },
  { icon: "chart", title: "Clear reporting", text: "Delivery, opens, clicks and bounces per campaign." },
];

/** Split-screen frame for the public auth pages: brand panel on large screens, the page's own form on the right. */
export default function AuthBackdrop({ children }) {
  return (
    <div className="min-h-screen bg-white lg:grid lg:grid-cols-[5fr_6fr]">
      <aside className="relative hidden overflow-hidden bg-brand-900 p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="pointer-events-none absolute -right-24 -top-24 h-96 w-96 rounded-full bg-brand-600/40 blur-3xl" aria-hidden="true" />
        <div className="pointer-events-none absolute -bottom-32 -left-16 h-96 w-96 rounded-full bg-brand-500/30 blur-3xl" aria-hidden="true" />
        <div className="relative flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-white/15 text-base font-bold ring-1 ring-white/25">Q</div>
          <span className="text-lg font-semibold tracking-tight">QRM Campaigns</span>
        </div>
        <div className="relative max-w-md">
          <h2 className="text-3xl font-semibold leading-tight tracking-tight">Email marketing your whole team can run.</h2>
          <ul className="mt-8 space-y-5">
            {POINTS.map((p) => (
              <li key={p.title} className="flex gap-3.5">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white/10 ring-1 ring-white/20"><Icon name={p.icon} className="h-4.5 w-4.5" /></span>
                <div><p className="text-sm font-medium">{p.title}</p><p className="text-sm text-brand-200">{p.text}</p></div>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-brand-300">Quality Resource Marketing</p>
      </aside>
      <div className="min-w-0 bg-slate-50 lg:bg-white">{children}</div>
    </div>
  );
}
