import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import ChartCard, { CHART_COLORS, chartTooltipStyle } from "../components/ChartCard";
import Icon from "../components/Icon";
import PageHeader from "../components/PageHeader";
import RecipientsPanel from "../components/RecipientsPanel";
import { PageSkeleton, Skeleton } from "../components/Skeleton";
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
  const [comparison, setComparison] = useState(null); // per-campaign rates for the most recent sent campaigns

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
      // Campaign comparison: reuse the existing per-campaign analytics endpoint for the latest few sent campaigns.
      const latest = (campaignsData.results || []).slice(0, 6);
      Promise.all(latest.map((c) => getCampaignAnalytics(c.id).then((a) => ({ name: c.name.length > 16 ? `${c.name.slice(0, 15)}…` : c.name, full: c.name, open: a.open_rate, click: a.click_rate, bounce: a.bounce_rate })).catch(() => null)))
        .then((rows) => setComparison(rows.filter(Boolean).reverse()))
        .catch(() => setComparison([]));
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

  if (loading) return <PageSkeleton />;

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

  // The top stat cards show the SELECTED campaign's own numbers once one is chosen, otherwise the account-wide totals.
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
    { label: "Emails Sent", value: topStats?.emails_sent ?? 0, icon: "mail", tone: "sky" },
    { label: "Delivered", value: topStats?.delivered ?? 0, icon: "checkCircle", tone: "green" },
    { label: "Opened", value: topStats?.opened ?? 0, icon: "mailOpen", tone: "brand" },
    { label: "Clicked", value: topStats?.clicked ?? 0, icon: "pointer", tone: "violet" },
    { label: "Bounced", value: topStats?.bounced ?? 0, icon: "ban", tone: "red" },
    { label: "Unsubscribed", value: topStats?.unsubscribed ?? 0, icon: "user", tone: "amber" },
    { label: "Spam Complaints", value: topStats?.spam_complaints ?? 0, icon: "alert", tone: "slate" },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Analytics"
        subtitle={selectedCampaignId ? "Showing numbers for the selected campaign." : "Overall performance across all campaigns."}
        actions={
          <>
            {campaigns.length > 0 && (
              <select className="input w-56" aria-label="Choose a campaign" value={selectedCampaignId} onChange={(e) => setSelectedCampaignId(e.target.value)}>
                <option value="">All campaigns</option>
                {campaigns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            )}
            <button className="btn-secondary" onClick={handleDownloadPdf} disabled={downloadingPdf}>
              <Icon name="download" className="h-4 w-4" /> {downloadingPdf ? "Generating…" : "Download PDF report"}
            </button>
          </>
        }
      />

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {STAT_CARDS.map((st) => {
          const filterValue = RECIPIENT_STATUS_FILTERS[st.label];
          return <StatCard key={st.label} label={st.label} value={st.value} icon={st.icon} tone={st.tone} onClick={() => handleStatCardClick(filterValue)} active={statusFilter === filterValue} />;
        })}
      </div>
      <p className="-mt-3 text-xs text-slate-500">Select a metric to see matching recipients{selectedCampaignId ? "" : " across all campaigns"}. Select it again to clear.</p>

      {statusFilter && (
        <RecipientsPanel recipients={recipients} statusFilter={statusFilter} onClear={() => applyStatusFilter(null)} hasMore={recipientsHasMore}
          loadingMore={loadingMoreRecipients} onLoadMore={loadMoreRecipients} loading={loadingRecipients} totalCount={recipientsTotal} showCampaignColumn={!selectedCampaignId} />
      )}

      {summary?.emails_sent > 0 && summary?.delivered === 0 && (
        <div className="flex items-start gap-3 rounded-xl border border-sky-200 bg-sky-50 p-4 text-sm text-sky-900">
          <Icon name="info" className="mt-0.5 h-4 w-4" />
          <p>
            <span className="font-semibold">{summary.emails_sent}</span> email{summary.emails_sent === 1 ? " has" : "s have"} been sent, but Delivered, Opened and Clicked are all still 0. Those numbers only arrive through Brevo’s webhook, not from sending itself. If your backend isn’t reachable at a public HTTPS URL (for example it runs on <code>localhost</code>), Brevo can’t call it back and these stay at 0 even though the emails went out. For local testing, expose the backend with a tool like <code>ngrok http 8000</code> and point the webhook at that URL — see the README’s Brevo webhook setup section.
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <div className="card">
          <div className="card-header">
            <div>
              <h2 className="card-title">Campaign performance</h2>
              <p className="mt-0.5 text-xs text-slate-500">{selectedCampaignId ? "Counts for the selected campaign" : "Select a campaign above for its detailed chart and rates"}</p>
            </div>
          </div>
          <div className="p-5">
            {campaigns.length === 0 ? (
              <p className="py-14 text-center text-sm text-slate-500">No sent campaigns yet.</p>
            ) : !selectedCampaignId ? (
              <p className="py-14 text-center text-sm text-slate-500">Choose a campaign from the menu at the top of the page.</p>
            ) : campaignAnalytics ? (
              <>
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chartData} margin={{ left: -12 }}>
                      <CartesianGrid vertical={false} stroke={CHART_COLORS.grid} strokeDasharray="3 3" />
                      <XAxis dataKey="name" tick={{ fontSize: 12, fill: "#64748b" }} axisLine={false} tickLine={false} />
                      <YAxis tick={{ fontSize: 12, fill: "#64748b" }} allowDecimals={false} axisLine={false} tickLine={false} />
                      <Tooltip contentStyle={chartTooltipStyle} cursor={{ fill: "#f1f5f9" }} />
                      <Bar dataKey="value" fill={CHART_COLORS.primary} radius={[6, 6, 0, 0]} maxBarSize={48} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
                  <RateStat label="Delivery rate" value={campaignAnalytics.delivery_rate} />
                  <RateStat label="Open rate" value={campaignAnalytics.open_rate} />
                  <RateStat label="Click rate" value={campaignAnalytics.click_rate} />
                  <RateStat label="Bounce rate" value={campaignAnalytics.bounce_rate} />
                  <RateStat label="Unsubscribe rate" value={campaignAnalytics.unsubscribe_rate} />
                  <RateStat label="Spam rate" value={campaignAnalytics.spam_rate} />
                </div>
              </>
            ) : (
              <div className="space-y-3 py-6"><Skeleton className="h-48 w-full" /><Skeleton className="h-4 w-1/2" /></div>
            )}
          </div>
        </div>

        <ChartCard title="Campaign comparison" subtitle="Open, click and bounce rate (%) for your latest sent campaigns"
          empty={campaigns.length === 0 ? "No sent campaigns yet." : comparison && comparison.length === 0 ? "Comparison data isn’t available right now." : null} height="h-[26rem]">
          {comparison === null ? (
            <div className="space-y-3"><Skeleton className="h-64 w-full" /><Skeleton className="h-4 w-1/3" /></div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={comparison} margin={{ left: -12 }}>
                <CartesianGrid vertical={false} stroke={CHART_COLORS.grid} strokeDasharray="3 3" />
                <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#64748b" }} axisLine={false} tickLine={false} interval={0} />
                <YAxis tick={{ fontSize: 12, fill: "#64748b" }} unit="%" axisLine={false} tickLine={false} />
                <Tooltip contentStyle={chartTooltipStyle} cursor={{ fill: "#f1f5f9" }} labelFormatter={(_, p) => p?.[0]?.payload?.full} formatter={(v) => `${v}%`} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="open" name="Open rate" fill={CHART_COLORS.primary} radius={[4, 4, 0, 0]} maxBarSize={22} />
                <Bar dataKey="click" name="Click rate" fill={CHART_COLORS.violet} radius={[4, 4, 0, 0]} maxBarSize={22} />
                <Bar dataKey="bounce" name="Bounce rate" fill={CHART_COLORS.red} radius={[4, 4, 0, 0]} maxBarSize={22} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>
      </div>
    </div>
  );
}

function RateStat({ label, value }) {
  return (
    <div className="rounded-lg border border-slate-100 bg-slate-50 px-4 py-3">
      <p className="text-lg font-semibold tabular-nums text-slate-900">{value}%</p>
      <p className="text-xs text-slate-500">{label}</p>
    </div>
  );
}
