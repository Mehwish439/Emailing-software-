import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import ConfirmDialog from "../components/ConfirmDialog";
import DateTimeTimezonePicker from "../components/DateTimeTimezonePicker";
import EmptyState from "../components/EmptyState";
import Icon from "../components/Icon";
import Modal from "../components/Modal";
import PageHeader from "../components/PageHeader";
import SearchBar from "../components/SearchBar";
import { TableSkeleton } from "../components/Skeleton";
import StatusBadge from "../components/StatusBadge";
import Tabs from "../components/Tabs";
import { useToast } from "../context/ToastContext";
import { cancelSchedule, listScheduledCampaigns, updateSchedule } from "../services/schedulingService";
import { localDateTimeInZoneToUTC } from "../utils/timezone";
import { formatApiError } from "../utils/formatError";

const TABS = [
  { key: "", label: "All" },
  { key: "scheduled", label: "Upcoming" },
  { key: "sent", label: "Sent" },
  { key: "cancelled", label: "Cancelled" },
  { key: "failed", label: "Failed" },
];

export default function ScheduledCampaignsPage() {
  const { showToast } = useToast();
  const [schedules, setSchedules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [confirmCancel, setConfirmCancel] = useState(null);
  const [editSchedule, setEditSchedule] = useState(null);
  const [editValue, setEditValue] = useState({ date: "", time: "", timezone: "Asia/Karachi" });
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState("");

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
      showToast(formatApiError(err, "Failed to update schedule."), "error");
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

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return schedules.filter((s) => (!tab || s.status === tab) && (!q || String(s.campaign_name || "").toLowerCase().includes(q)));
  }, [schedules, search, tab]);

  const counts = useMemo(() => {
    const c = {};
    schedules.forEach((s) => { c[s.status] = (c[s.status] || 0) + 1; });
    return c;
  }, [schedules]);
  const tabs = TABS.map((t) => ({ ...t, count: t.key ? counts[t.key] || 0 : schedules.length }));

  const fmtDate = (iso) => new Date(iso).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", year: "numeric" });
  const fmtTime = (iso) => new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });

  return (
    <div className="space-y-6">
      <PageHeader title="Scheduled campaigns" subtitle="Upcoming and past scheduled sends. Change a time or cancel before it starts sending." />

      <div className="card overflow-hidden">
        <div className="space-y-3 px-5 pt-4">
          <SearchBar value={search} onChange={setSearch} placeholder="Search by campaign…" className="max-w-sm" />
          <Tabs tabs={tabs} value={tab} onChange={setTab} className="-mx-5 px-5" />
        </div>

        {loading ? (
          <TableSkeleton rows={5} cols={4} />
        ) : visible.length === 0 ? (
          <EmptyState
            icon="calendar"
            title={schedules.length === 0 ? "Nothing scheduled" : "No schedules match"}
            description={schedules.length === 0 ? "Schedule a campaign from the campaign creation flow and it will show up here." : "Try a different search or tab."}
            action={schedules.length === 0 && <Link to="/campaigns/create" className="btn-primary"><Icon name="plus" className="h-4 w-4" /> Create campaign</Link>}
          />
        ) : (
          <div className="table-wrap scroll-thin">
            <table className="min-w-full divide-y divide-slate-100">
              <thead className="bg-slate-50/70">
                <tr>
                  <th className="th">Campaign</th>
                  <th className="th">Send time</th>
                  <th className="th hidden sm:table-cell">Timezone</th>
                  <th className="th">Status</th>
                  <th className="px-4 py-3"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {visible.map((s) => (
                  <tr key={s.id} className="transition-colors hover:bg-slate-50/80">
                    <td className="px-4 py-3.5">
                      <Link to={`/campaigns/${s.campaign}`} className="row-link text-sm">{s.campaign_name}</Link>
                    </td>
                    <td className="px-4 py-3.5">
                      <p className="text-sm font-medium text-slate-900">{fmtDate(s.scheduled_at)}</p>
                      <p className="text-xs text-slate-500">{fmtTime(s.scheduled_at)}</p>
                    </td>
                    <td className="td hidden sm:table-cell">{s.timezone}</td>
                    <td className="px-4 py-3.5"><StatusBadge status={s.status} /></td>
                    <td className="px-4 py-3.5">
                      <div className="flex justify-end gap-1">
                        {s.status === "scheduled" && (
                          <>
                            <button className="btn-secondary btn-sm" onClick={() => openEdit(s)}><Icon name="edit" className="h-3.5 w-3.5" /> Reschedule</button>
                            <button className="btn-ghost btn-sm !text-red-600 hover:!bg-red-50" onClick={() => setConfirmCancel(s)}>Cancel</button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <Modal
        open={!!editSchedule}
        onClose={() => setEditSchedule(null)}
        title="Reschedule campaign"
        footer={
          <>
            <button className="btn-secondary" onClick={() => setEditSchedule(null)}>Cancel</button>
            <button className="btn-primary" onClick={handleUpdate} disabled={saving}>{saving ? "Saving…" : "Save schedule"}</button>
          </>
        }
      >
        <p className="mb-4 text-sm text-slate-500">Choose a new send time for <span className="font-medium text-slate-900">{editSchedule?.campaign_name}</span>.</p>
        <DateTimeTimezonePicker date={editValue.date} time={editValue.time} timezone={editValue.timezone} onChange={setEditValue} />
      </Modal>

      <ConfirmDialog
        open={!!confirmCancel}
        onClose={() => setConfirmCancel(null)}
        onConfirm={handleCancel}
        title="Cancel this scheduled send?"
        message={`“${confirmCancel?.campaign_name}” will be moved back to draft and will not send at the scheduled time.`}
        confirmLabel="Cancel schedule"
      />
    </div>
  );
}
