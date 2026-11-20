import { useState } from "react";

import ConfirmDialog from "../../components/ConfirmDialog";
import { useToast } from "../../context/ToastContext";
import useApi, { useDebounced } from "../../hooks/useApi";
import { platform } from "../../services/adminService";
import { formatApiError } from "../../utils/formatError";
import { Async, Badge, DataTable, Notice, PageFooter, PageHeader, SearchInput, Tile, fmt, when } from "../../components/admin/ui";

const STATES = ["", "queued", "submitting", "accepted", "deferred", "delivered", "bounced", "failed", "suppressed", "cancelled", "needs_review"];

export default function PlatformQueue() {
  const { showToast } = useToast();
  const queue = useApi(platform.queue);
  const [state, setState] = useState("needs_review");
  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  const [page, setPage] = useState(1);
  const msgs = useApi(() => platform.queueMessages({ state: state || undefined, search: q || undefined, page }), [state, q, page]);
  const [confirm, setConfirm] = useState(null);

  const refresh = () => { queue.reload(); msgs.reload(); };
  const run = async () => {
    try { await confirm.fn(); showToast(confirm.ok, "success"); refresh(); } catch (err) { showToast(formatApiError(err, "Action failed."), "error"); }
    setConfirm(null);
  };

  return (
    <div className="space-y-6">
      <PageHeader title="Queue & failed jobs" subtitle="Message states are kept honest: “accepted” means a provider took the message, not that it reached an inbox."
        actions={<Async state={queue}>{(d) => <button className={d.paused ? "btn-primary" : "btn-danger"} onClick={() => setConfirm({ title: d.paused ? "Resume queue" : "Pause the whole queue", message: d.paused ? "Resume submitting messages for ALL companies?" : "Stop submitting new messages for ALL companies? Messages already in flight will finish.", danger: !d.paused, fn: () => platform.setQueuePaused(!d.paused), ok: d.paused ? "Queue resumed." : "Queue paused." })}>{d.paused ? "Resume queue" : "Pause queue"}</button>}</Async>} />
      <Async state={queue}>{(d) => (<>
        {d.paused && <Notice tone="error">The queue is paused. Nothing is being submitted.</Notice>}
        {d.stuck_submitting > 0 && <Notice tone="warn">{d.stuck_submitting} message(s) have been “submitting” for over 10 minutes. Their outcome is unknown; they will move to needs review and must not be blindly resent.</Notice>}
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Tile label="Queued" value={fmt(d.states.queued || 0)} /><Tile label="Deferred" value={fmt(d.states.deferred || 0)} /><Tile label="Failed" value={fmt(d.states.failed || 0)} /><Tile label="Needs review" value={fmt(d.states.needs_review || 0)} hint={`Oldest waiting: ${Math.round(d.oldest_age_seconds / 60)} min`} />
        </div></>)}</Async>
      <div className="flex flex-wrap items-end gap-3">
        <select aria-label="State" className="input max-w-[12rem]" value={state} onChange={(e) => { setState(e.target.value); setPage(1); }}>{STATES.map((s) => <option key={s} value={s}>{s ? s.replace("_", " ") : "All states"}</option>)}</select>
        <SearchInput value={search} onChange={(v) => { setSearch(v); setPage(1); }} placeholder="Search recipient email" />
      </div>
      <div className="card"><Async state={msgs}>{(d) => (<><DataTable rows={d.results} empty="No messages in this state." columns={[
        { key: "recipient", header: "Recipient" }, { key: "campaign", header: "Campaign", render: (m) => <div><p>{m.campaign}</p><p className="text-xs text-slate-500">{m.company || "—"}</p></div> },
        { key: "state", header: "State", render: (m) => <Badge value={m.state} /> }, { key: "provider", header: "Provider" }, { key: "attempts", header: "Tries" },
        { key: "last_error", header: "Last error", render: (m) => <span className="text-xs break-words">{m.last_error || "—"}</span> }, { key: "updated_at", header: "Updated", render: (m) => when(m.updated_at) },
        { key: "a", header: "", render: (m) => m.state === "failed" ? <button className="btn-secondary px-2 py-1" onClick={() => setConfirm({ title: "Retry message", message: `Retry ${m.recipient}? Only failed messages with a temporary error can be retried.`, danger: false, fn: () => platform.messageAction(m.id, "retry"), ok: "Message queued for retry." })}>Retry</button>
          : m.state === "needs_review" ? (<div className="flex gap-2">
            <button className="btn-secondary px-2 py-1" onClick={() => setConfirm({ title: "Mark as sent", message: `Only choose this if you have PROOF (provider log) that ${m.recipient} was accepted. The message will never be resent.`, danger: false, fn: () => platform.messageAction(m.id, "resolve", { outcome: "sent" }), ok: "Marked as sent." })}>Was sent</button>
            <button className="btn-secondary px-2 py-1" onClick={() => setConfirm({ title: "Allow resend", message: `Only choose this if you have confirmed ${m.recipient} was NOT accepted. The message will be sent again.`, fn: () => platform.messageAction(m.id, "resolve", { outcome: "retry" }), ok: "Message queued for resend." })}>Resend</button></div>) : null }]} /><PageFooter data={d} onPage={setPage} /></>)}</Async></div>
      <ConfirmDialog open={!!confirm} onClose={() => setConfirm(null)} onConfirm={run} danger={confirm?.danger !== false} title={confirm?.title} message={confirm?.message} confirmLabel="Confirm" />
    </div>
  );
}
