import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import Spinner from "../components/Spinner";
import StatCard from "../components/StatCard";
import StatusBadge from "../components/StatusBadge";
import { getDashboardSummary } from "../services/analyticsService";
import { listCampaigns } from "../services/campaignService";
import { listScheduledCampaigns } from "../services/schedulingService";

const QUICK_ACTIONS = [
  { label: "Add Contact", to: "/contacts", icon: "M12 4v16m8-8H4" },
  { label: "Import Contacts", to: "/contacts", icon: "M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5 5-5M12 15V3" },
  { label: "Create Campaign", to: "/campaigns/create", icon: "M12 4v16m8-8H4" },
  { label: "Create Template", to: "/templates/create", icon: "M12 4v16m8-8H4" },
  { label: "Schedule Campaign", to: "/campaigns", icon: "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" },
];

export default function DashboardPage() {
  const [summary, setSummary] = useState(null);
  const [recentCampaigns, setRecentCampaigns] = useState([]);
  const [upcoming, setUpcoming] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const [summaryData, campaignsData, scheduledData] = await Promise.all([
          getDashboardSummary(),
          listCampaigns({ ordering: "-created_at", page_size: 5 }),
          listScheduledCampaigns(),
        ]);
        setSummary(summaryData);
        setRecentCampaigns(campaignsData.results || []);
        setUpcoming((scheduledData.results || scheduledData || []).filter((s) => s.status === "scheduled").slice(0, 5));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) {
    return (
      <div className="flex justify-center py-24">
        <Spinner size="lg" />
      </div>
    );
  }

  const stats = [
    { label: "Total Contacts", value: summary?.total_contacts ?? 0 },
    { label: "Total Campaigns", value: summary?.total_campaigns ?? 0 },
    { label: "Scheduled Campaigns", value: summary?.scheduled_campaigns ?? 0 },
    { label: "Emails Sent", value: summary?.emails_sent ?? 0 },
    { label: "Delivered", value: summary?.delivered ?? 0 },
    { label: "Opened", value: summary?.opened ?? 0 },
    { label: "Clicked", value: summary?.clicked ?? 0 },
    { label: "Bounced", value: summary?.bounced ?? 0 },
    { label: "Unsubscribed", value: summary?.unsubscribed ?? 0 },
    { label: "Spam Complaints", value: summary?.spam_complaints ?? 0 },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Dashboard</h1>
        <p className="text-sm text-slate-500">Here's how your campaigns are performing.</p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        {stats.map((s) => (
          <StatCard key={s.label} label={s.label} value={s.value} />
        ))}
      </div>

      <div className="card p-5">
        <h2 className="text-sm font-semibold text-slate-900 mb-3">Quick actions</h2>
        <div className="flex flex-wrap gap-2">
          {QUICK_ACTIONS.map((action) => (
            <Link key={action.label} to={action.to} className="btn-secondary">
              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={action.icon} />
              </svg>
              {action.label}
            </Link>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="card">
          <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
            <h2 className="text-sm font-semibold text-slate-900">Recent campaigns</h2>
            <Link to="/campaigns" className="text-sm text-brand-600 hover:underline">
              View all
            </Link>
          </div>
          {recentCampaigns.length === 0 ? (
            <p className="px-5 py-8 text-sm text-slate-500 text-center">No campaigns yet.</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {recentCampaigns.map((c) => (
                <li key={c.id} className="flex items-center justify-between px-5 py-3">
                  <div>
                    <Link to={`/campaigns/${c.id}`} className="text-sm font-medium text-slate-900 hover:text-brand-600">
                      {c.name}
                    </Link>
                    <p className="text-xs text-slate-500">{c.subject}</p>
                  </div>
                  <StatusBadge status={c.status} />
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card">
          <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
            <h2 className="text-sm font-semibold text-slate-900">Upcoming scheduled campaigns</h2>
            <Link to="/scheduled" className="text-sm text-brand-600 hover:underline">
              View all
            </Link>
          </div>
          {upcoming.length === 0 ? (
            <p className="px-5 py-8 text-sm text-slate-500 text-center">Nothing scheduled.</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {upcoming.map((s) => (
                <li key={s.id} className="flex items-center justify-between px-5 py-3">
                  <div>
                    <p className="text-sm font-medium text-slate-900">{s.campaign_name}</p>
                    <p className="text-xs text-slate-500">
                      {new Date(s.scheduled_at).toLocaleString()} ({s.timezone})
                    </p>
                  </div>
                  <StatusBadge status={s.status} />
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
