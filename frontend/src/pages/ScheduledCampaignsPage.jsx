import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import ConfirmDialog from "../components/ConfirmDialog";
import DateTimeTimezonePicker from "../components/DateTimeTimezonePicker";
import EmptyState from "../components/EmptyState";
import Modal from "../components/Modal";
import Spinner from "../components/Spinner";
import StatusBadge from "../components/StatusBadge";
import { useToast } from "../context/ToastContext";
import { cancelSchedule, listScheduledCampaigns, updateSchedule } from "../services/schedulingService";
import { localDateTimeInZoneToUTC } from "../utils/timezone";

export default function ScheduledCampaignsPage() {
  const { showToast } = useToast();
  const [schedules, setSchedules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [confirmCancel, setConfirmCancel] = useState(null);
  const [editSchedule, setEditSchedule] = useState(null);
  const [editValue, setEditValue] = useState({ date: "", time: "", timezone: "Asia/Karachi" });
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const data = await listScheduledCampaigns();
      setSchedules(data.results || data || []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const openEdit = (schedule) => {
    const d = new Date(schedule.scheduled_at);
    setEditSchedule(schedule);
    setEditValue({
      date: d.toISOString().split("T")[0],
      time: d.toISOString().split("T")[1].slice(0, 5),
      timezone: schedule.timezone,
    });
  };

  const handleUpdate = async () => {
    setSaving(true);
    try {
      const scheduledAtUTC = localDateTimeInZoneToUTC(editValue.date, editValue.time, editValue.timezone);
      await updateSchedule(editSchedule.id, { scheduled_at: scheduledAtUTC, timezone: editValue.timezone });
      showToast("Schedule updated.", "success");
      setEditSchedule(null);
      load();
    } catch (err) {
      showToast(err.response?.data?.detail || "Failed to update schedule.", "error");
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = async () => {
    try {
      await cancelSchedule(confirmCancel.id);
      showToast("Schedule cancelled.", "success");
      setConfirmCancel(null);
      load();
    } catch {
      showToast("Failed to cancel schedule.", "error");
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Scheduled Campaigns</h1>
        <p className="text-sm text-slate-500">Upcoming and past scheduled sends.</p>
      </div>

      <div className="card">
        {loading ? (
          <div className="flex justify-center py-16">
            <Spinner size="lg" />
          </div>
        ) : schedules.length === 0 ? (
          <EmptyState title="Nothing scheduled" description="Schedule a campaign from the campaign creation flow." />
        ) : (
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase">Campaign</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase">Scheduled At</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase">Timezone</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase">Status</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {schedules.map((s) => (
                <tr key={s.id}>
                  <td className="px-4 py-3 text-sm">
                    <Link to={`/campaigns/${s.campaign}`} className="font-medium text-slate-900 hover:text-brand-600">
                      {s.campaign_name}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-600">{new Date(s.scheduled_at).toLocaleString()}</td>
                  <td className="px-4 py-3 text-sm text-slate-600">{s.timezone}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={s.status} />
                  </td>
                  <td className="px-4 py-3 text-right space-x-3">
                    {s.status === "scheduled" && (
                      <>
                        <button className="text-sm text-brand-600 hover:underline" onClick={() => openEdit(s)}>
                          Edit
                        </button>
                        <button className="text-sm text-red-600 hover:underline" onClick={() => setConfirmCancel(s)}>
                          Cancel
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <Modal
        open={!!editSchedule}
        onClose={() => setEditSchedule(null)}
        title="Edit Schedule"
        footer={
          <>
            <button className="btn-secondary" onClick={() => setEditSchedule(null)}>
              Cancel
            </button>
            <button className="btn-primary" onClick={handleUpdate} disabled={saving}>
              {saving ? "Saving…" : "Save"}
            </button>
          </>
        }
      >
        <DateTimeTimezonePicker
          date={editValue.date}
          time={editValue.time}
          timezone={editValue.timezone}
          onChange={setEditValue}
        />
      </Modal>

      <ConfirmDialog
        open={!!confirmCancel}
        onClose={() => setConfirmCancel(null)}
        onConfirm={handleCancel}
        title="Cancel this scheduled campaign?"
        message={`"${confirmCancel?.campaign_name}" will be moved back to draft.`}
        confirmLabel="Cancel Schedule"
      />
    </div>
  );
}
