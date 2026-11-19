// NEW FILE (Marketing Automation feature)
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import ConfirmDialog from "../components/ConfirmDialog";
import EmptyState from "../components/EmptyState";
import Pagination from "../components/Pagination";
import Spinner from "../components/Spinner";
import StatusBadge from "../components/StatusBadge";
import { useToast } from "../context/ToastContext";
import {
  activateAutomation,
  deleteAutomation,
  listAutomations,
  pauseAutomation,
  resumeAutomation,
} from "../services/automationService";
import { apiErrorMessage, triggerLabel } from "../utils/automation";

export default function AutomationsPage() {
  const { showToast } = useToast();
  const [automations, setAutomations] = useState([]);
  const [page, setPage] = useState(1);
  const [numPages, setNumPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listAutomations({ page });
      setAutomations(data.results || data || []);
      setNumPages(data.num_pages || 1);
    } catch (err) {
      showToast(apiErrorMessage(err, "Failed to load automations."), "error");
    } finally {
      setLoading(false);
    }
  }, [page, showToast]);

  useEffect(() => {
    load();
  }, [load]);

  const runAction = async (automation, fn, successMessage) => {
    setBusyId(automation.id);
    try {
      await fn(automation.id);
      showToast(successMessage, "success");
      await load();
    } catch (err) {
      showToast(apiErrorMessage(err, "Action failed."), "error");
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async () => {
    try {
      await deleteAutomation(confirmDelete.id);
      showToast("Automation deleted.", "success");
      setConfirmDelete(null);
      load();
    } catch (err) {
      showToast(apiErrorMessage(err, "Failed to delete automation."), "error");
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Marketing Automation</h1>
          <p className="text-sm text-slate-500">Send emails automatically when contacts sign up, join a list, or trigger an event.</p>
        </div>
        <Link to="/automations/create" className="btn-primary">
          Create Automation
        </Link>
      </div>

      <div className="card">
        {loading ? (
          <div className="flex justify-center py-16">
            <Spinner size="lg" />
          </div>
        ) : automations.length === 0 ? (
          <EmptyState
            title="No automations yet"
            description="Create a welcome series or drip campaign that runs on its own."
            action={
              <Link to="/automations/create" className="btn-primary">
                Create Automation
              </Link>
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200">
              <thead className="bg-slate-50">
                <tr>
                  {["Automation Name", "Trigger", "Status", "Contacts", "Emails Sent", "Created", ""].map((h) => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {automations.map((a) => (
                  <tr key={a.id}>
                    <td className="px-4 py-3 text-sm">
                      <Link to={`/automations/${a.id}`} className="font-medium text-slate-900 hover:text-brand-600">
                        {a.name}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-600">{triggerLabel(a.trigger_type)}</td>
                    <td className="px-4 py-3">
                      <StatusBadge status={a.status} />
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-600">{a.enrolled_count}</td>
                    <td className="px-4 py-3 text-sm text-slate-600">{a.emails_sent}</td>
                    <td className="px-4 py-3 text-sm text-slate-600">{new Date(a.created_at).toLocaleDateString()}</td>
                    <td className="px-4 py-3 text-right whitespace-nowrap space-x-3">
                      <Link to={`/automations/${a.id}`} className="text-sm text-brand-600 hover:underline">
                        View
                      </Link>
                      <Link to={`/automations/${a.id}/edit`} className="text-sm text-brand-600 hover:underline">
                        Edit
                      </Link>
                      {a.status === "draft" && (
                        <button
                          className="text-sm text-emerald-600 hover:underline"
                          disabled={busyId === a.id}
                          onClick={() => runAction(a, activateAutomation, "Automation activated.")}
                        >
                          Activate
                        </button>
                      )}
                      {a.status === "active" && (
                        <button
                          className="text-sm text-amber-600 hover:underline"
                          disabled={busyId === a.id}
                          onClick={() => runAction(a, pauseAutomation, "Automation paused.")}
                        >
                          Pause
                        </button>
                      )}
                      {a.status === "paused" && (
                        <button
                          className="text-sm text-emerald-600 hover:underline"
                          disabled={busyId === a.id}
                          onClick={() => runAction(a, resumeAutomation, "Automation resumed.")}
                        >
                          Resume
                        </button>
                      )}
                      <button className="text-sm text-red-600 hover:underline" onClick={() => setConfirmDelete(a)}>
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pagination page={page} numPages={numPages} onPageChange={setPage} />
      </div>

      <ConfirmDialog
        open={!!confirmDelete}
        onClose={() => setConfirmDelete(null)}
        onConfirm={handleDelete}
        title="Delete automation?"
        message={`"${confirmDelete?.name}" and all of its enrolled contacts and history will be permanently deleted. Contacts currently in the workflow will stop receiving its emails.`}
        confirmLabel="Delete"
      />
    </div>
  );
}
