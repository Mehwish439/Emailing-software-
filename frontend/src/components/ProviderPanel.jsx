import { providerLabel } from "../utils/providers";

const STATE_LABELS = {
  queued: "Queued", submitting: "Submitting", accepted: "Accepted by provider", deferred: "Retrying later",
  delivered: "Delivered (confirmed)", bounced: "Bounced", failed: "Failed", suppressed: "Suppressed",
  cancelled: "Cancelled", needs_review: "Needs review (outcome unknown)",
};
const when = (iso) => (iso ? new Date(iso).toLocaleString() : "—");

/**
 * Provider-specific view of one campaign, from GET /campaigns/{id}/provider-log/ (our own records).
 * "Accepted" means the provider took responsibility for the message; it is not proof of inbox delivery.
 */
export default function ProviderPanel({ log }) {
  if (!log || (!log.total && !log.recent_events?.length)) return null;
  const states = Object.entries(log.states || {});
  return (
    <div className="card p-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-900">Sending provider: {providerLabel(log.provider)}</h2>
        <span className="text-xs text-slate-500">{log.frozen ? "Locked in for this campaign" : "Not started yet"}</span>
      </div>
      {states.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {states.map(([state, n]) => (
            <span key={state} className={`rounded-md border px-2 py-1 text-xs ${state === "failed" || state === "needs_review" ? "border-red-200 bg-red-50 text-red-700" : "border-slate-200 bg-slate-50 text-slate-700"}`}>
              {STATE_LABELS[state] || state}: <b>{n}</b>
            </span>
          ))}
        </div>
      )}
      {log.recent_errors?.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-slate-700 mb-1">Recent sending errors</h3>
          <ul className="space-y-1 text-xs text-slate-600">
            {log.recent_errors.map((e, i) => (
              <li key={i} className="break-words"><b>{e.recipient}</b> — {STATE_LABELS[e.state] || e.state}{e.code ? ` (${e.code})` : ""}: {e.error} <span className="text-slate-400">· {when(e.updated_at)}</span></li>
            ))}
          </ul>
        </div>
      )}
      {log.recent_events?.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-slate-700 mb-1">Recent provider events</h3>
          <ul className="space-y-1 text-xs text-slate-600">
            {log.recent_events.map((e, i) => (
              <li key={i}>{e.event} · {e.recipient} · <span className="text-slate-400">{e.outcome} · {when(e.received_at)}</span></li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
