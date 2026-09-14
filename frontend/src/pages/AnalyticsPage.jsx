import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import RecipientsPanel from "../components/RecipientsPanel";
import Spinner from "../components/Spinner";
import StatCard from "../components/StatCard";
import { useToast } from "../context/ToastContext";
import { downloadAllCampaignsReportPdf, getAllRecipients, getCampaignAnalytics, getDashboardSummary } from "../services/analyticsService";
import { getCampaignRecipients, listCampaigns } from "../services/campaignService";
import { RECIPIENT_STATUS_FILTERS } from "../utils/recipientStatusFilters";

export default function AnalyticsPage() {
  const { showToast } = useToast();

  const [summary, setSummary] = useState(null);
  const [campaigns, setCampaigns] = useState([]);
  const [selectedCampaignId, setSelectedCampaignId] = useState("");
  const [campaignAnalytics, setCampaignAnalytics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [downloadingPdf, setDownloadingPdf] = useState(false);

  // Clicking a stat card below filters the recipients panel to just that
  // status. When a single campaign is selected (selectedCampaignId), this
  // filters that campaign's own recipients (via campaignService); when
  // "All campaigns" is selected, it filters recipients across every
  // campaign (via analyticsService.getAllRecipients). null means no card
  // is active / the panel is hidden.
  const [statusFilter, setStatusFilter] = useState(null);
  const [recipients, setRecipients] = useState([]);
  const [recipientsPage, setRecipientsPage] = useState(1);
  const [recipientsTotal, setRecipientsTotal] = useState(null);
  const [recipientsHasMore, setRecipientsHasMore] = useState(false);
  const [loadingRecipients, setLoadingRecipients] = useState(false);
  const [loadingMoreRecipients, setLoadingMoreRecipients] = useState(false);

  useEffect(() => {
    (async () => {
      setLoading(true);
      const [summaryData, campaignsData] = await Promise.all([
        getDashboardSummary(),
        listCampaigns({ status: "sent", page_size: 50, ordering: "-sent_at" }),
      ]);
      setSummary(summaryData);
      setCampaigns(campaignsData.results || []);
      // Starts on "All campaigns" (empty selection) rather than
      // auto-picking the first one, since the top stat cards below now
      // switch between the overall summary and a single campaign's numbers
      // based on this selection — defaulting to "All" avoids silently
      // showing just one campaign's numbers as if they were the total.
      setLoading(false);
    })();
  }, []);

  useEffect(() => {
    // Switching which campaign is selected changes what the stat cards
    // (and therefore the status filter values) mean, so any recipients
    // filter from before the switch no longer applies — clear it rather
    // than leave a stale/mismatched list on screen.
    setStatusFilter(null);
    setRecipients([]);
    setRecipientsHasMore(false);
    setRecipientsTotal(null);
    if (!selectedCampaignId) {
      setCampaignAnalytics(null);
      return;
    }
    getCampaignAnalytics(selectedCampaignId).then(setCampaignAnalytics);
  }, [selectedCampaignId]);

  const applyStatusFilter = async (value) => {
    setStatusFilter(value);
    if (!value) {
      setRecipients([]);
      setRecipientsHasMore(false);
      setRecipientsTotal(null);
      return;
    }
    setLoadingRecipients(true);
    try {
      const data = selectedCampaignId
        ? await getCampaignRecipients(selectedCampaignId, { recipient_status: value, page: 1, page_size: 50 })
        : await getAllRecipients({ status: value, page: 1, page_size: 50 });
      setRecipients(data.results || []);
      setRecipientsPage(1);
      setRecipientsHasMore(Boolean(data.next));
      setRecipientsTotal(data.count ?? null);
    } catch {
      showToast("Failed to load recipients.", "error");
    } finally {
      setLoadingRecipients(false);
    }
  };

  // Clicking the same stat again clears the filter (hides the panel).
  const handleStatCardClick = (value) => {
    applyStatusFilter(statusFilter === value ? null : value);
  };

  const loadMoreRecipients = async () => {
    setLoadingMoreRecipients(true);
    try {
      const nextPage = recipientsPage + 1;
      const data = selectedCampaignId
        ? await getCampaignRecipients(selectedCampaignId, { recipient_status: statusFilter, page: nextPage, page_size: 50 })
        : await getAllRecipients({ status: statusFilter, page: nextPage, page_size: 50 });
      setRecipients((prev) => [...prev, ...(data.results || [])]);
      setRecipientsPage(nextPage);
      setRecipientsHasMore(Boolean(data.next));
    } catch {
      showToast("Failed to load more recipients.", "error");
    } finally {
      setLoadingMoreRecipients(false);
    }
  };

  const handleDownloadPdf = async () => {
    setDownloadingPdf(true);
    try {
      await downloadAllCampaignsReportPdf();
    } finally {
      setDownloadingPdf(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center py-24">
        <Spinner size="lg" />
      </div>
    );
  }

  const chartData = campaignAnalytics
    ? [
        { name: "Sent", value: campaignAnalytics.sent },
        { name: "Delivered", value: campaignAnalytics.delivered },
        { name: "Opened", value: campaignAnalytics.opened },
        { name: "Clicked", value: campaignAnalytics.clicked },
        { name: "Bounced", value: campaignAnalytics.soft_bounced + campaignAnalytics.hard_bounced },
        { name: "Unsub'd", value: campaignAnalytics.unsubscribed },
      ]
    : [];

  // The top stat cards show the SELECTED campaign's own numbers once one is
  // chosen below, instead of always showing the account-wide totals — that
  // way picking a campaign actually changes what's displayed up top too.
  const topStats = campaignAnalytics
    ? {
        emails_sent: campaignAnalytics.sent,
        delivered: campaignAnalytics.delivered,
        opened: campaignAnalytics.opened,
        clicked: campaignAnalytics.clicked,
        bounced: campaignAnalytics.soft_bounced + campaignAnalytics.hard_bounced,
        unsubscribed: campaignAnalytics.unsubscribed,
        spam_complaints: campaignAnalytics.spam,
      }
    : summary;

  const STAT_CARDS = [
    { label: "Emails Sent", value: topStats?.emails_sent ?? 0 },
    { label: "Delivered", value: topStats?.delivered ?? 0 },
    { label: "Opened", value: topStats?.opened ?? 0 },
    { label: "Clicked", value: topStats?.clicked ?? 0 },
    { label: "Bounced", value: topStats?.bounced ?? 0 },
    { label: "Unsubscribed", value: topStats?.unsubscribed ?? 0 },
    { label: "Spam Complaints", value: topStats?.spam_complaints ?? 0 },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Analytics</h1>
          <p className="text-sm text-slate-500">
            {selectedCampaignId
              ? `Showing numbers for the selected campaign below.`
              : "Overall performance across all campaigns."}
          </p>
        </div>
        <button className="btn-secondary text-sm" onClick={handleDownloadPdf} disabled={downloadingPdf}>
          {downloadingPdf ? "Generating…" : "Download PDF Report (all campaigns)"}
        </button>
      </div>

      <p className="text-xs text-slate-400">
        Click a stat to see matching recipients{selectedCampaignId ? "" : " across all campaigns"} — click again to
        clear.
      </p>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
        {STAT_CARDS.map((s) => {
          const filterValue = RECIPIENT_STATUS_FILTERS[s.label];
          return (
            <StatCard
              key={s.label}
              label={s.label}
              value={s.value}
              onClick={() => handleStatCardClick(filterValue)}
              active={statusFilter === filterValue}
            />
          );
        })}
      </div>

      {statusFilter && (
        <RecipientsPanel
          recipients={recipients}
          statusFilter={statusFilter}
          onClear={() => applyStatusFilter(null)}
          hasMore={recipientsHasMore}
          loadingMore={loadingMoreRecipients}
          onLoadMore={loadMoreRecipients}
          loading={loadingRecipients}
          totalCount={recipientsTotal}
          showCampaignColumn={!selectedCampaignId}
        />
      )}

      {summary?.emails_sent > 0 && summary?.delivered === 0 && (
        <div className="card p-4 bg-blue-50 border-blue-200">
          <p className="text-sm text-blue-800">
            <span className="font-semibold">{summary.emails_sent}</span> email
            {summary.emails_sent === 1 ? " has" : "s have"} been sent, but Delivered/Opened/Clicked are all still
            0. Those numbers only come in via Brevo's webhook, not from sending itself — if your backend isn't
            reachable at a public HTTPS URL (e.g. it's running on <code>localhost</code>), Brevo has no way to
            call it back and these will stay at 0 even though the emails actually went out fine. For local
            testing, expose your backend with a tool like <code>ngrok http 8000</code> and point the webhook at
            that URL — see the README's Brevo webhook setup section.
          </p>
        </div>
      )}

      <div className="card p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-slate-900">Campaign performance</h2>
          {campaigns.length > 0 && (
            <select
              className="input max-w-xs"
              value={selectedCampaignId}
              onChange={(e) => setSelectedCampaignId(e.target.value)}
            >
              <option value="">All campaigns (totals above)</option>
              {campaigns.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          )}
        </div>

        {campaigns.length === 0 ? (
          <p className="text-sm text-slate-500 text-center py-12">No sent campaigns yet.</p>
        ) : !selectedCampaignId ? (
          <p className="text-sm text-slate-500 text-center py-12">
            Select a campaign above to see its detailed chart and rates.
          </p>
        ) : campaignAnalytics ? (
          <>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} allowDecimals={false} />
                  <Tooltip />
                  <Bar dataKey="value" fill="#3d63f7" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mt-4 text-sm">
              <RateStat label="Delivery Rate" value={campaignAnalytics.delivery_rate} />
              <RateStat label="Open Rate" value={campaignAnalytics.open_rate} />
              <RateStat label="Click Rate" value={campaignAnalytics.click_rate} />
              <RateStat label="Bounce Rate" value={campaignAnalytics.bounce_rate} />
              <RateStat label="Unsubscribe Rate" value={campaignAnalytics.unsubscribe_rate} />
              <RateStat label="Spam Rate" value={campaignAnalytics.spam_rate} />
            </div>
          </>
        ) : (
          <div className="flex justify-center py-12">
            <Spinner />
          </div>
        )}
      </div>
    </div>
  );
}

function RateStat({ label, value }) {
  return (
    <div className="rounded-lg bg-slate-50 px-4 py-3">
      <p className="text-lg font-semibold text-slate-900">{value}%</p>
      <p className="text-slate-500">{label}</p>
    </div>
  );
}