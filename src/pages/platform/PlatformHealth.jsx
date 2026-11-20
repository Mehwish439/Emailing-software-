import useApi from "../../hooks/useApi";
import { platform } from "../../services/adminService";
import { Async, Badge, DataTable, Notice, PageHeader, when } from "../../components/admin/ui";

export default function PlatformHealth() {
  const state = useApi(platform.health);
  return (
    <div className="space-y-6">
      <PageHeader title="System health" subtitle="Live checks of this deployment's own dependencies." actions={<button className="btn-secondary" onClick={state.reload}>Refresh</button>} />
      <Async state={state}>{(h) => (<>
        {h.alerts.length === 0 ? <Notice tone="ok">No operational alerts.</Notice> : h.alerts.map((a) => <Notice key={a.message} tone="warn">{a.count} {a.message}</Notice>)}
        <div className="grid gap-4 md:grid-cols-3">
          <div className="card p-5"><h2 className="font-semibold">Database</h2><p className="mt-2">{h.database.ok ? <Badge value="ok" label="Connected" /> : <Badge value="failed" label="Unavailable" />}</p>{h.database.detail && <p className="text-xs text-red-700 mt-1">{h.database.detail}</p>}</div>
          <div className="card p-5"><h2 className="font-semibold">Celery / Redis (optional)</h2><p className="mt-2">{!h.broker.configured ? <Badge value="pending" label="Not configured" /> : h.broker.ok ? <Badge value="ok" label="Reachable" /> : <Badge value="failed" label="Unreachable" />}</p><p className="text-xs text-slate-500 mt-1">{h.broker.detail}</p></div>
          <div className="card p-5"><h2 className="font-semibold">Providers</h2>{Object.entries(h.providers).map(([n, p]) => <p key={n} className="mt-2 text-sm capitalize">{n}: {p.ok === null ? "not probed" : p.ok ? "OK" : "failing"}{p.active ? " (active)" : ""}</p>)}</div>
        </div>
        <div className="card"><h2 className="px-4 pt-4 font-semibold">Background jobs</h2><DataTable rows={h.jobs} rowKey="name" empty="No job has reported yet. If you rely on cron, confirm it is calling the scheduler." columns={[
          { key: "name", header: "Job" }, { key: "last_run_at", header: "Last run", render: (j) => when(j.last_run_at) }, { key: "status", header: "Result", render: (j) => <Badge value={j.status === "ok" ? "ok" : "failed"} label={j.status} /> },
          { key: "stale", header: "Freshness", render: (j) => j.stale ? <Badge value="deferred" label="Stale (>10 min)" /> : <Badge value="ok" label="Recent" /> }, { key: "detail", header: "Detail" }]} /></div>
        <p className="text-xs text-slate-500">{h.label} Checked {when(h.checked_at)}.</p>
      </>)}</Async>
    </div>
  );
}
