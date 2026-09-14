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
      <div className="px-5 py-4 border-b border-slate-200 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-900">
          Recipients ({recipients.length}
          {hasMore ? "+" : ""}
          {totalCount != null ? ` of ${totalCount}` : ""})
        </h2>
        {statusFilter && (
          <button type="button" className="text-xs text-brand-600 hover:underline" onClick={onClear}>
            Clear filter
          </button>
        )}
      </div>
      {loading ? (
        <p className="px-5 py-8 text-sm text-slate-500 text-center">Loading…</p>
      ) : recipients.length === 0 ? (
        <p className="px-5 py-8 text-sm text-slate-500 text-center">{emptyMessage}</p>
      ) : (
        <table className="min-w-full divide-y divide-slate-200">
          <thead className="bg-slate-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase">Contact</th>
              {showCampaignColumn && (
                <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase">Campaign</th>
              )}
              <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase">Status</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase">Sent At</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {recipients.map((r) => (
              <tr key={r.id}>
                <td className="px-4 py-3 text-sm text-slate-900">
                  {r.contact_name} <span className="text-slate-400">({r.contact_email})</span>
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
        </table>
      )}
      {hasMore && (
        <div className="px-5 py-4 border-t border-slate-100 text-center">
          <button
            type="button"
            className="text-sm font-medium text-brand-600 hover:underline disabled:opacity-50"
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
