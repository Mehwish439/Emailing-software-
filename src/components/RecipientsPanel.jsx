import Icon from "./Icon";
import { TableSkeleton } from "./Skeleton";
import StatusBadge from "./StatusBadge";

// Shared recipients table used wherever a stat card can be clicked to
// drill down into the matching recipients — currently DashboardPage and
// AnalyticsPage (both list recipients across ALL campaigns, so
// showCampaignColumn defaults to true so it's clear which campaign each
// row belongs to).
export default function RecipientsPanel({
  recipients,
  statusFilter,
  onClear,
  hasMore,
  loadingMore,
  onLoadMore,
  loading = false,
  totalCount,
  showCampaignColumn = true,
  emptyMessage = "No recipients match this filter yet.",
}) {
  return (
    <div className="card">
      <div className="card-header">
        <h2 className="card-title">
          Recipients ({recipients.length}
          {hasMore ? "+" : ""}
          {totalCount != null ? ` of ${totalCount}` : ""})
        </h2>
        {statusFilter && (
          <button type="button" className="btn-ghost btn-sm" onClick={onClear}><Icon name="x" className="h-3.5 w-3.5" /> Clear filter</button>
        )}
      </div>
      {loading ? (
        <TableSkeleton rows={4} cols={3} />
      ) : recipients.length === 0 ? (
        <p className="px-5 py-8 text-sm text-slate-500 text-center">{emptyMessage}</p>
      ) : (
        <div className="table-wrap scroll-thin"><table className="min-w-full divide-y divide-slate-100">
          <thead className="bg-slate-50/70">
            <tr>
              <th className="th">Contact</th>
              {showCampaignColumn && (
                <th className="th">Campaign</th>
              )}
              <th className="th">Status</th>
              <th className="th">Sent At</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {recipients.map((r) => (
              <tr key={r.id}>
                <td className="px-4 py-3 text-sm text-slate-900">
                  <span className="font-medium">{r.contact_name}</span> <span className="text-slate-500">{r.contact_email}</span>
                </td>
                {showCampaignColumn && (
                  <td className="px-4 py-3 text-sm text-slate-500">{r.campaign_name}</td>
                )}
                <td className="px-4 py-3">
                  <StatusBadge status={r.status} />
                </td>
                <td className="px-4 py-3 text-sm text-slate-500">
                  {r.sent_at ? new Date(r.sent_at).toLocaleString() : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
      {hasMore && (
        <div className="px-5 py-4 border-t border-slate-100 text-center">
          <button
            type="button"
            className="btn-secondary btn-sm"
            onClick={onLoadMore}
            disabled={loadingMore}
          >
            {loadingMore
              ? "Loading…"
              : `Load more (showing ${recipients.length}${totalCount != null ? ` of ${totalCount}` : ""})`}
          </button>
        </div>
      )}
    </div>
  );
}
