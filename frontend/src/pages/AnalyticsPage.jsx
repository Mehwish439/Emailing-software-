import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import Spinner from "../components/Spinner";
import StatCard from "../components/StatCard";
import { getCampaignAnalytics, getDashboardSummary } from "../services/analyticsService";
import { listCampaigns } from "../services/campaignService";

export default function AnalyticsPage() {
  const [summary, setSummary] = useState(null);
  const [campaigns, setCampaigns] = useState([]);
  const [selectedCampaignId, setSelectedCampaignId] = useState("");
  const [campaignAnalytics, setCampaignAnalytics] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setLoading(true);
      const [summaryData, campaignsData] = await Promise.all([
        getDashboardSummary(),
        listCampaigns({ status: "sent", page_size: 50, ordering: "-sent_at" }),
      ]);
      setSummary(summaryData);
      setCampaigns(campaignsData.results || []);
      if (campaignsData.results?.length) {
        setSelectedCampaignId(String(campaignsData.results[0].id));
      }
      setLoading(false);
    })();
  }, []);

  useEffect(() => {
    if (!selectedCampaignId) {
      setCampaignAnalytics(null);
      return;
    }
    getCampaignAnalytics(selectedCampaignId).then(setCampaignAnalytics);
  }, [selectedCampaignId]);

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

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Analytics</h1>
        <p className="text-sm text-slate-500">Overall performance across all campaigns.</p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
        <StatCard label="Emails Sent" value={summary?.emails_sent ?? 0} />
        <StatCard label="Delivered" value={summary?.delivered ?? 0} />
        <StatCard label="Opened" value={summary?.opened ?? 0} />
        <StatCard label="Clicked" value={summary?.clicked ?? 0} />
        <StatCard label="Bounced" value={summary?.bounced ?? 0} />
        <StatCard label="Unsubscribed" value={summary?.unsubscribed ?? 0} />
        <StatCard label="Spam Complaints" value={summary?.spam_complaints ?? 0} />
      </div>

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
