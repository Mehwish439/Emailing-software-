import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import ConfirmDialog from "../components/ConfirmDialog";
import EmptyState from "../components/EmptyState";
import Pagination from "../components/Pagination";
import Spinner from "../components/Spinner";
import StatusBadge from "../components/StatusBadge";
import { useToast } from "../context/ToastContext";
import { deleteCampaign, duplicateCampaign, listCampaigns } from "../services/campaignService";

export default function CampaignsPage() {
  const { showToast } = useToast();
  const navigate = useNavigate();
  const [campaigns, setCampaigns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(1);
  const [numPages, setNumPages] = useState(1);
  const [confirmDelete, setConfirmDelete] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const data = await listCampaigns({
        page,
        search: search || undefined,
        status: statusFilter || undefined,
        ordering: "-created_at",
      });
      setCampaigns(data.results || []);
      setNumPages(data.num_pages || 1);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const t = setTimeout(load, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, search, statusFilter]);

  const handleDuplicate = async (id) => {
    try {
      await duplicateCampaign(id);
      showToast("Campaign duplicated.", "success");
      load();
    } catch {
      showToast("Failed to duplicate campaign.", "error");
    }
  };

  const handleDelete = async () => {
    try {
      await deleteCampaign(confirmDelete.id);
      showToast("Campaign deleted.", "success");
      setConfirmDelete(null);
      load();
    } catch (err) {
      showToast(err.response?.data?.detail || "Failed to delete campaign.", "error");
      setConfirmDelete(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Campaigns</h1>
          <p className="text-sm text-slate-500">Create, send, and track your email campaigns.</p>
        </div>
        <button className="btn-primary" onClick={() => navigate("/campaigns/create")}>
          Create Campaign
        </button>
      </div>

      <div className="card">
        <div className="flex flex-wrap items-center gap-3 px-5 py-4 border-b border-slate-200">
          <input
            className="input max-w-xs"
            placeholder="Search campaigns…"
            value={search}
            onChange={(e) => {
              setPage(1);
              setSearch(e.target.value);
            }}
          />
          <select
            className="input max-w-[160px]"
            value={statusFilter}
            onChange={(e) => {
              setPage(1);
              setStatusFilter(e.target.value);
            }}
          >
            <option value="">All statuses</option>
            <option value="draft">Draft</option>
            <option value="scheduled">Scheduled</option>
            <option value="processing">Processing</option>
            <option value="sent">Sent</option>
            <option value="cancelled">Cancelled</option>
            <option value="failed">Failed</option>
          </select>
        </div>

        {loading ? (
          <div className="flex justify-center py-16">
            <Spinner size="lg" />
          </div>
        ) : campaigns.length === 0 ? (
          <EmptyState
            title="No campaigns yet"
            description="Create your first campaign to start reaching your audience."
            action={
              <button className="btn-primary" onClick={() => navigate("/campaigns/create")}>
                Create Campaign
              </button>
            }
          />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200">
                <thead className="bg-slate-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase">Name</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase">Subject</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase">Recipients</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase">Status</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {campaigns.map((c) => (
                    <tr key={c.id} className="hover:bg-slate-50">
                      <td className="px-4 py-3">
                        <Link to={`/campaigns/${c.id}`} className="text-sm font-medium text-slate-900 hover:text-brand-600">
                          {c.name}
                        </Link>
                      </td>
                      <td className="px-4 py-3 text-sm text-slate-600">{c.subject}</td>
                      <td className="px-4 py-3 text-sm text-slate-600">{c.recipient_count}</td>
                      <td className="px-4 py-3">
                        <StatusBadge status={c.status} />
                      </td>
                      <td className="px-4 py-3 text-right space-x-3">
                        <Link to={`/campaigns/${c.id}`} className="text-sm text-brand-600 hover:underline">
                          View
                        </Link>
                        {c.status === "draft" && (
                          <Link to={`/campaigns/${c.id}/edit`} className="text-sm text-brand-600 hover:underline">
                            Edit
                          </Link>
                        )}
                        <button className="text-sm text-slate-600 hover:underline" onClick={() => handleDuplicate(c.id)}>
                          Duplicate
                        </button>
                        <button className="text-sm text-red-600 hover:underline" onClick={() => setConfirmDelete(c)}>
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={page} numPages={numPages} onPageChange={setPage} />
          </>
        )}
      </div>

      <ConfirmDialog
        open={!!confirmDelete}
        onClose={() => setConfirmDelete(null)}
        onConfirm={handleDelete}
        title="Delete this campaign?"
        message={`"${confirmDelete?.name}" will be permanently removed.`}
        confirmLabel="Delete"
      />
    </div>
  );
}
