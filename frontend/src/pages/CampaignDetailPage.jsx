import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import ConfirmDialog from "../components/ConfirmDialog";
import DateTimeTimezonePicker from "../components/DateTimeTimezonePicker";
import Modal from "../components/Modal";
import Spinner from "../components/Spinner";
import StatCard from "../components/StatCard";
import StatusBadge from "../components/StatusBadge";
import { useToast } from "../context/ToastContext";
import { getCampaignAnalytics } from "../services/analyticsService";
import {
  downloadCampaignReportPdf,
  getCampaign,
  getCampaignRecipients,
  sendCampaignNow,
  sendTestEmail,
} from "../services/campaignService";
import { cancelSchedule, createSchedule, listScheduledCampaigns } from "../services/schedulingService";
import { localDateTimeInZoneToUTC } from "../utils/timezone";

function defaultDate() {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d.toISOString().split("T")[0];
}

export default function CampaignDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { showToast } = useToast();

  const [campaign, setCampaign] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [recipients, setRecipients] = useState([]);
  const [recipientsPage, setRecipientsPage] = useState(1);
  const [recipientsHasMore, setRecipientsHasMore] = useState(false);
  const [loadingMoreRecipients, setLoadingMoreRecipients] = useState(false);
  // Which stat card is currently "active" as a filter on the recipients
  // table below — null means "show everyone" (the default). Comma-joined
  // for stats like Delivered that map to more than one underlying status
  // (see campaigns/views.py's recipients action).
  const [statusFilter, setStatusFilter] = useState(null);
  const [downloadingPdf, setDownloadingPdf] = useState(false);
  const [schedule, setSchedule] = useState(null);
  const [loading, setLoading] = useState(true);

  const [testModalOpen, setTestModalOpen] = useState(false);
  const [testEmail, setTestEmail] = useState("");
  const [sendingTest, setSendingTest] = useState(false);

  const [scheduleModalOpen, setScheduleModalOpen] = useState(false);
  const [scheduleValue, setScheduleValue] = useState({ date: defaultDate(), time: "10:00", timezone: "Asia/Karachi" });
  const [scheduling, setScheduling] = useState(false);

  const [confirmSend, setConfirmSend] = useState(false);
  const [confirmCancelSchedule, setConfirmCancelSchedule] = useState(false);
  const [sendingNow, setSendingNow] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      // All three independent requests fire in parallel (not one-after-
      // another) so the page's total load time is roughly the SLOWEST of
      // the three, not the sum of all three — this matters a lot on a
      // backend/database pairing with real network latency between them.
      // listScheduledCampaigns used to only be fetched afterward (and only
      // for scheduled/processing campaigns), adding a full extra sequential
      // round trip; fetching it here unconditionally costs nothing when
      // it's not needed, since setSchedule below only actually uses it for
      // those statuses.
      const [campaignData, recipientsData, schedulesData] = await Promise.all([
        getCampaign(id),
        // 50 per page (not the previous hardcoded 10) so most campaigns show
        // everyone at a glance; "Load more" below fetches further pages for
        // anything bigger, using the same page_size/next-page pattern the
        // backend already supports (see common/pagination.py).
        getCampaignRecipients(id, { page: 1, page_size: 50 }),
        listScheduledCampaigns().catch(() => null),
      ]);
      setCampaign(campaignData);
      setRecipients(recipientsData.results || []);
      setRecipientsPage(1);
      setRecipientsHasMore(Boolean(recipientsData.next));
      setStatusFilter(null);

      if (campaignData.status !== "draft") {
        getCampaignAnalytics(id).then(setAnalytics).catch(() => {});
      }
      if (["scheduled", "processing"].includes(campaignData.status) && schedulesData) {
        const active = (schedulesData.results || schedulesData || []).find(
          (s) => String(s.campaign) === String(id) && s.status === "scheduled"
        );
        setSchedule(active || null);
      }
    } finally {
      setLoading(false);
    }
  };

  const applyStatusFilter = async (statusValue) => {
    setStatusFilter(statusValue);
    const params = { page: 1, page_size: 50 };
    if (statusValue) params.status = statusValue;
    try {
      const data = await getCampaignRecipients(id, params);
      setRecipients(data.results || []);
      setRecipientsPage(1);
      setRecipientsHasMore(Boolean(data.next));
    } catch {
      showToast("Failed to filter recipients.", "error");
    }
  };

  // Clicking the same stat again clears the filter (shows everyone).
  const handleStatCardClick = (statusValue) => {
    applyStatusFilter(statusFilter === statusValue ? null : statusValue);
  };

  const handleDownloadPdf = async () => {
    setDownloadingPdf(true);
    try {
      await downloadCampaignReportPdf(id, campaign.name);
    } catch {
      showToast("Failed to generate PDF report.", "error");
    } finally {
      setDownloadingPdf(false);
    }
  };

  const loadMoreRecipients = async () => {
    setLoadingMoreRecipients(true);
    try {
      const nextPage = recipientsPage + 1;
      const params = { page: nextPage, page_size: 50 };
      if (statusFilter) params.status = statusFilter;
      const data = await getCampaignRecipients(id, params);
      setRecipients((prev) => [...prev, ...(data.results || [])]);
      setRecipientsPage(nextPage);
      setRecipientsHasMore(Boolean(data.next));
    } catch {
      showToast("Failed to load more recipients.", "error");
    } finally {
      setLoadingMoreRecipients(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const handleSendTest = async () => {
    setSendingTest(true);
    try {
      await sendTestEmail(id, testEmail);
      showToast(`Test email sent to ${testEmail}.`, "success");
      setTestModalOpen(false);
      setTestEmail("");
    } catch (err) {
      showToast(err.response?.data?.detail || "Failed to send test email.", "error");
    } finally {
      setSendingTest(false);
    }
  };

  const handleSendNow = async () => {
    setSendingNow(true);
    try {
      await sendCampaignNow(id);
      showToast("Campaign is sending now!", "success");
      setConfirmSend(false);
      load();
    } catch (err) {
      showToast(err.response?.data?.detail || "Failed to send campaign.", "error");
      setConfirmSend(false);
    } finally {
      setSendingNow(false);
    }
  };

  const handleSchedule = async () => {
    setScheduling(true);
    try {
      const scheduledAtUTC = localDateTimeInZoneToUTC(scheduleValue.date, scheduleValue.time, scheduleValue.timezone);
      await createSchedule({ campaign: id, scheduled_at: scheduledAtUTC, timezone: scheduleValue.timezone });
      showToast("Campaign scheduled!", "success");
      setScheduleModalOpen(false);
      load();
    } catch (err) {
      showToast(err.response?.data?.detail || "Failed to schedule campaign.", "error");
    } finally {
      setScheduling(false);
    }
  };

  const handleCancelSchedule = async () => {
    try {
      await cancelSchedule(schedule.id);
      showToast("Schedule cancelled.", "success");
      setConfirmCancelSchedule(false);
      load();
    } catch {
      showToast("Failed to cancel schedule.", "error");
    }
  };

  if (loading || !campaign) {
    return (
      <div className="flex justify-center py-24">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold text-slate-900">{campaign.name}</h1>
            <StatusBadge status={campaign.status} />
          </div>
          <p className="text-sm text-slate-500">{campaign.subject}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn-secondary" onClick={() => setTestModalOpen(true)}>
            Send Test Email
          </button>
          {campaign.status === "draft" && (
            <>
              <Link to={`/campaigns/${id}/edit`} className="btn-secondary">
                Edit
              </Link>
              <button className="btn-secondary" onClick={() => setScheduleModalOpen(true)} disabled={!campaign.eligible_recipient_count}>
                Schedule
              </button>
              <button className="btn-primary" onClick={() => setConfirmSend(true)} disabled={!campaign.eligible_recipient_count}>
                Send Now
              </button>
            </>
          )}
          {campaign.status === "scheduled" && schedule && (
            <button className="btn-danger" onClick={() => setConfirmCancelSchedule(true)}>
              Cancel Scheduled Send
            </button>
          )}
        </div>
      </div>

      {schedule && campaign.status === "scheduled" && (
        <div className="card p-4 flex items-center justify-between bg-amber-50 border-amber-200">
          <p className="text-sm text-amber-800">
            Scheduled for <span className="font-semibold">{new Date(schedule.scheduled_at).toLocaleString()}</span> (
            {schedule.timezone})
          </p>
        </div>
      )}

      {campaign.failure_reason && (
        <div className="card p-4 bg-red-50 border-red-200">
          <p className="text-sm text-red-700">{campaign.failure_reason}</p>
        </div>
      )}

      {analytics && (
        <>
          <div className="flex items-center justify-between">
            <p className="text-xs text-slate-400">Click a stat to filter recipients by it — click again to clear.</p>
            <button className="btn-secondary text-sm" onClick={handleDownloadPdf} disabled={downloadingPdf}>
              {downloadingPdf ? "Generating…" : "Download PDF Report"}
            </button>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
            <StatCard
              label="Sent"
              value={analytics.sent}
              onClick={() => handleStatCardClick("sent,delivered,opened,clicked,bounced,blocked,unsubscribed,spam,failed")}
              active={statusFilter === "sent,delivered,opened,clicked,bounced,blocked,unsubscribed,spam,failed"}
            />
            <StatCard
              label="Delivered"
              value={analytics.delivered}
              onClick={() => handleStatCardClick("delivered,opened,clicked")}
              active={statusFilter === "delivered,opened,clicked"}
            />
            <StatCard
              label="Opened"
              value={analytics.opened}
              onClick={() => handleStatCardClick("opened,clicked")}
              active={statusFilter === "opened,clicked"}
            />
            <StatCard
              label="Clicked"
              value={analytics.clicked}
              onClick={() => handleStatCardClick("clicked")}
              active={statusFilter === "clicked"}
            />
            <StatCard
              label="Bounced"
              value={analytics.soft_bounced + analytics.hard_bounced}
              onClick={() => handleStatCardClick("bounced")}
              active={statusFilter === "bounced"}
            />
            <StatCard
              label="Unsubscribed"
              value={analytics.unsubscribed}
              onClick={() => handleStatCardClick("unsubscribed")}
              active={statusFilter === "unsubscribed"}
            />
            <StatCard
              label="Spam Complaints"
              value={analytics.spam}
              onClick={() => handleStatCardClick("spam")}
              active={statusFilter === "spam"}
            />
            <StatCard label="Delivery Rate" value={`${analytics.delivery_rate}%`} />
          </div>
          {analytics.sent > 0 && analytics.delivered === 0 && (
            <div className="card p-4 bg-blue-50 border-blue-200">
              <p className="text-sm text-blue-800">
                <span className="font-semibold">{analytics.sent}</span> email
                {analytics.sent === 1 ? " was" : "s were"} sent, but Delivered/Opened/Clicked are still showing 0.
                Those numbers come from Brevo's webhook, not from sending itself — if your backend isn't running
                on a publicly reachable HTTPS URL that Brevo can call (e.g. it's still on <code>localhost</code>),
                the webhook can't reach it and these will stay at 0 even though the emails actually sent fine. See
                the README's webhook setup section (a tool like <code>ngrok http 8000</code> works for local
                testing).
              </p>
            </div>
          )}
        </>
      )}

      <div className="card">
        <div className="px-5 py-4 border-b border-slate-200 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-900">
            Recipients ({recipients.length}{recipientsHasMore ? "+" : ""}
            {statusFilter ? " matching filter" : ` of ${campaign.recipient_count}`})
          </h2>
          {statusFilter && (
            <button className="text-xs text-brand-600 hover:underline" onClick={() => applyStatusFilter(null)}>
              Show all
            </button>
          )}
        </div>
        {["draft", "scheduled", "processing", "failed"].includes(campaign.status) && (
          <div className={`px-5 py-3 border-b border-slate-100 text-sm ${
            campaign.eligible_recipient_count > 0 ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"
          }`}>
            {campaign.eligible_recipient_count > 0 ? (
              <>
                <span className="font-semibold">{campaign.eligible_recipient_count}</span> eligible contact
                {campaign.eligible_recipient_count === 1 ? "" : "s"}{" "}
                {campaign.status === "draft" ? "will receive" : "are set to receive"} this campaign (active,
                non-suppressed contacts in the selected list{campaign.contact_lists?.length === 1 ? "" : "s"}).
              </>
            ) : (
              <>
                No eligible recipients — either no contact list is selected, or the selected list has no active,
                non-suppressed contacts.{" "}
                {campaign.status === "draft" ? (
                  <>
                    Check{" "}
                    <Link to={`/campaigns/${id}/edit`} className="underline font-medium">
                      the selected list(s)
                    </Link>{" "}
                    and confirm contacts in it are marked "Active". Sending or scheduling is blocked until this
                    shows at least 1.
                  </>
                ) : (
                  <>This is why the scheduled send didn't (or won't) go out — go back to draft and fix the list before rescheduling.</>
                )}
              </>
            )}
          </div>
        )}
        {recipients.length === 0 ? (
          <p className="px-5 py-8 text-sm text-slate-500 text-center">
            {campaign.status === "draft"
              ? "No recipients recorded yet — recipients are captured once you Send Now or Schedule this campaign."
              : "No recipients yet."}
          </p>
        ) : (
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase">Contact</th>
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
        {recipientsHasMore && (
          <div className="px-5 py-4 border-t border-slate-100 text-center">
            <button
              type="button"
              className="text-sm font-medium text-brand-600 hover:underline disabled:opacity-50"
              onClick={loadMoreRecipients}
              disabled={loadingMoreRecipients}
            >
              {loadingMoreRecipients
                ? "Loading…"
                : `Load more (showing ${recipients.length} of ${campaign.recipient_count})`}
            </button>
          </div>
        )}
      </div>

      {/* Send test email modal */}
      <Modal
        open={testModalOpen}
        onClose={() => setTestModalOpen(false)}
        title="Send Test Email"
        footer={
          <>
            <button className="btn-secondary" onClick={() => setTestModalOpen(false)}>
              Cancel
            </button>
            <button className="btn-primary" onClick={handleSendTest} disabled={!testEmail || sendingTest}>
              {sendingTest ? "Sending…" : "Send Test"}
            </button>
          </>
        }
      >
        <label className="label">Test email address</label>
        <input
          className="input"
          type="email"
          placeholder="you@example.com"
          value={testEmail}
          onChange={(e) => setTestEmail(e.target.value)}
        />
      </Modal>

      {/* Schedule modal */}
      <Modal
        open={scheduleModalOpen}
        onClose={() => setScheduleModalOpen(false)}
        title="Schedule Campaign"
        footer={
          <>
            <button className="btn-secondary" onClick={() => setScheduleModalOpen(false)}>
              Cancel
            </button>
            <button className="btn-primary" onClick={handleSchedule} disabled={scheduling}>
              {scheduling ? "Scheduling…" : "Schedule Campaign"}
            </button>
          </>
        }
      >
        <DateTimeTimezonePicker
          date={scheduleValue.date}
          time={scheduleValue.time}
          timezone={scheduleValue.timezone}
          onChange={setScheduleValue}
        />
      </Modal>

      <ConfirmDialog
        open={confirmSend}
        onClose={() => setConfirmSend(false)}
        onConfirm={handleSendNow}
        title="Send this campaign now?"
        message={`This will immediately send "${campaign.name}" to ${campaign.eligible_recipient_count || "all eligible"} recipients.`}
        confirmLabel="Send Now"
        danger={false}
        loading={sendingNow}
      />

      <ConfirmDialog
        open={confirmCancelSchedule}
        onClose={() => setConfirmCancelSchedule(false)}
        onConfirm={handleCancelSchedule}
        title="Cancel scheduled send?"
        message="The campaign will be moved back to draft."
        confirmLabel="Cancel Schedule"
      />
    </div>
  );
}