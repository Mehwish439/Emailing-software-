import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import ConfirmDialog from "../components/ConfirmDialog";
import Dropdown, { MenuItem } from "../components/Dropdown";
import EmptyState from "../components/EmptyState";
import Icon from "../components/Icon";
import PageHeader from "../components/PageHeader";
import Pagination from "../components/Pagination";
import SearchBar from "../components/SearchBar";
import { TableSkeleton } from "../components/Skeleton";
import StatusBadge from "../components/StatusBadge";
import Tabs from "../components/Tabs";
import { useToast } from "../context/ToastContext";
import { deleteCampaign, duplicateCampaign, listCampaigns } from "../services/campaignService";
import { formatApiError } from "../utils/formatError";

const STATUS_TABS = [
  { key: "", label: "All" },
  { key: "draft", label: "Draft" },
  { key: "scheduled", label: "Scheduled" },
  { key: "processing", label: "Sending" },
  { key: "sent", label: "Sent" },
  { key: "failed", label: "Failed" },
  { key: "cancelled", label: "Cancelled" },
];

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
      const data = await listCampaigns({ page, search: search || undefined, status: statusFilter || undefined, ordering: "-created_at" });
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
      showToast(formatApiError(err, "Failed to delete campaign."), "error");
      setConfirmDelete(null);
    }
  };

  const filtered = Boolean(search || statusFilter);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Campaigns"
        subtitle="Create, send and track your email campaigns."
        actions={<button className="btn-primary" onClick={() => navigate("/campaigns/create")}><Icon name="plus" className="h-4 w-4" /> Create campaign</button>}
      />

      <div className="card overflow-hidden">
        <div className="space-y-3 px-5 pt-4">
          <SearchBar value={search} onChange={(v) => { setPage(1); setSearch(v); }} placeholder="Search campaigns…" className="max-w-sm" />
          <Tabs tabs={STATUS_TABS} value={statusFilter} onChange={(k) => { setPage(1); setStatusFilter(k); }} className="-mx-5 px-5" />
        </div>

        {loading ? (
          <TableSkeleton rows={7} cols={4} />
        ) : campaigns.length === 0 ? (
          <EmptyState
            icon="send"
            title={filtered ? "No campaigns match these filters" : "No campaigns yet"}
            description={filtered ? "Try a different search term or status." : "Create your first campaign to start reaching your audience."}
            action={!filtered && <button className="btn-primary" onClick={() => navigate("/campaigns/create")}><Icon name="plus" className="h-4 w-4" /> Create campaign</button>}
          />
        ) : (
          <>
            <div className="table-wrap scroll-thin">
              <table className="min-w-full divide-y divide-slate-100">
                <thead className="bg-slate-50/70">
                  <tr>
                    <th className="th">Campaign</th>
                    <th className="th hidden md:table-cell">Subject</th>
                    <th className="th">Recipients</th>
                    <th className="th">Status</th>
                    <th className="px-4 py-3"><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {campaigns.map((c) => (
                    <tr key={c.id} className="transition-colors hover:bg-slate-50/80">
                      <td className="px-4 py-3.5">
                        <Link to={`/campaigns/${c.id}`} className="row-link text-sm">{c.name}</Link>
                        <p className="mt-0.5 truncate text-xs text-slate-500 md:hidden">{c.subject}</p>
                      </td>
                      <td className="td hidden max-w-xs truncate md:table-cell">{c.subject}</td>
                      <td className="td tabular-nums">{Number(c.recipient_count ?? 0).toLocaleString()}</td>
                      <td className="px-4 py-3.5"><StatusBadge status={c.status} /></td>
                      <td className="px-4 py-3.5">
                        <div className="flex items-center justify-end gap-1">
                          <Link to={`/campaigns/${c.id}`} className="btn-icon" title="View report" aria-label={`View ${c.name}`}><Icon name="eye" className="h-4 w-4" /></Link>
                          {c.status === "draft" && <Link to={`/campaigns/${c.id}/edit`} className="btn-icon" title="Edit" aria-label={`Edit ${c.name}`}><Icon name="edit" className="h-4 w-4" /></Link>}
                          <Dropdown width="w-44" trigger={({ toggle }) => <button className="btn-icon" onClick={toggle} aria-haspopup="menu" aria-label={`More actions for ${c.name}`}><Icon name="more" className="h-4 w-4" /></button>}>
                            <MenuItem onClick={() => handleDuplicate(c.id)}><Icon name="copy" className="h-4 w-4" /> Duplicate</MenuItem>
                            <MenuItem danger onClick={() => setConfirmDelete(c)}><Icon name="trash" className="h-4 w-4" /> Delete</MenuItem>
                          </Dropdown>
                        </div>
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
        message={`“${confirmDelete?.name}” will be permanently removed.`}
        confirmLabel="Delete campaign"
      />
    </div>
  );
}
