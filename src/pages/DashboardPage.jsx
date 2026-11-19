import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import ChartCard, { CHART_COLORS, chartTooltipStyle } from "../components/ChartCard";
import EmptyState from "../components/EmptyState";
import Icon from "../components/Icon";
import PageHeader from "../components/PageHeader";
import QuotaCard from "../components/QuotaCard";
import RecipientsPanel from "../components/RecipientsPanel";
import { PageSkeleton } from "../components/Skeleton";
import StatCard from "../components/StatCard";
import StatusBadge from "../components/StatusBadge";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import api from "../services/api";
import { getAllRecipients, getDashboardSummary } from "../services/analyticsService";
import { listCampaigns } from "../services/campaignService";
import { listScheduledCampaigns } from "../services/schedulingService";
import { RECIPIENT_STATUS_FILTERS } from "../utils/recipientStatusFilters";

const QUICK_ACTIONS = [
  { label: "Create campaign", to: "/campaigns/create", icon: "send", primary: true },
  { label: "Add or import contacts", to: "/contacts", icon: "users" },
  { label: "Create template", to: "/templates/create", icon: "template" },
  { label: "Build automation", to: "/automations/create", icon: "bolt" },
];

const rate = (num, den) => (den > 0 ? Math.round((1000 * num) / den) / 10 : null);
const fmtRate = (v) => (v === null ? "—" : `${v}%`);
const shortName = (s = "") => (s.length > 14 ? `${s.slice(0, 13)}…` : s);

export default function DashboardPage() {
  const { showToast } = useToast();
  const { user } = useAuth();
  const navigate = useNavigate();

  const [summary, setSummary] = useState(null);
  const [recentCampaigns, setRecentCampaigns] = useState([]);
  const [upcoming, setUpcoming] = useState([]);
  const [providers, setProviders] = useState(null);
  const [loading, setLoading] = useState(true);

  // Clicking a stat card filters the recipients panel to that status across ALL campaigns; clicking again clears it.
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
      try {
        const [summaryData, campaignsData, scheduledData] = await Promise.all([
          getDashboardSummary(),
          listCampaigns({ ordering: "-created_at", page_size: 8 }),
          listScheduledCampaigns(),
        ]);
        setSummary(summaryData);
        setRecentCampaigns(campaignsData.results || []);
        setUpcoming((scheduledData.results || scheduledData || []).filter((s) => s.status === "scheduled").slice(0, 5));
      } catch {
        showToast("Some dashboard data could not be loaded.", "error");
      } finally {
        setLoading(false);
      }
    })();
    api.get("/campaigns/providers/").then((r) => setProviders(r.data)).catch(() => setProviders(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
      const data = await getAllRecipients({ status: value, page: 1, page_size: 50 });
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

  const handleStatCardClick = (value) => applyStatusFilter(statusFilter === value ? null : value);

  const loadMoreRecipients = async () => {
    setLoadingMoreRecipients(true);
    try {
      const nextPage = recipientsPage + 1;
      const data = await getAllRecipients({ status: statusFilter, page: nextPage, page_size: 50 });
      setRecipients((prev) => [...prev, ...(data.results || [])]);
      setRecipientsPage(nextPage);
      setRecipientsHasMore(Boolean(data.next));
    } catch {
      showToast("Failed to load more recipients.", "error");
    } finally {
      setLoadingMoreRecipients(false);
    }
  };

  const s = useMemo(() => summary || {}, [summary]);
  const funnel = useMemo(() => [
    { name: "Sent", value: s.emails_sent ?? 0, fill: CHART_COLORS.slate },
    { name: "Delivered", value: s.delivered ?? 0, fill: CHART_COLORS.sky },
    { name: "Opened", value: s.opened ?? 0, fill: CHART_COLORS.primary },
    { name: "Clicked", value: s.clicked ?? 0, fill: CHART_COLORS.violet },
  ], [s]);
  const outcomes = useMemo(() => [
    { name: "Delivered", value: s.delivered ?? 0, fill: CHART_COLORS.green },
    { name: "Bounced", value: s.bounced ?? 0, fill: CHART_COLORS.red },
    { name: "Unsubscribed", value: s.unsubscribed ?? 0, fill: CHART_COLORS.amber },
    { name: "Spam", value: s.spam_complaints ?? 0, fill: CHART_COLORS.slate },
  ].filter((o) => o.value > 0), [s]);
  const sendingActivity = useMemo(
    () => [...recentCampaigns].reverse().map((c) => ({ name: shortName(c.name), full: c.name, recipients: Number(c.recipient_count ?? 0) })),
    [recentCampaigns]
  );

  const activity = useMemo(() => {
    const items = [
      ...recentCampaigns.filter((c) => c.created_at).map((c) => ({ key: `c${c.id}`, at: c.created_at, text: <>Campaign <Link className="row-link" to={`/campaigns/${c.id}`}>{c.name}</Link> created</>, status: c.status, icon: "send" })),
      ...upcoming.map((u) => ({ key: `s${u.id}`, at: u.scheduled_at, text: <><Link className="row-link" to={`/campaigns/${u.campaign}`}>{u.campaign_name}</Link> scheduled to send</>, status: u.status, icon: "clock", future: true })),
    ];
    return items.sort((a, b) => new Date(b.at) - new Date(a.at)).slice(0, 6);
  }, [recentCampaigns, upcoming]);

  if (loading) return <PageSkeleton />;

  const greeting = user?.first_name ? `Welcome back, ${user.first_name}` : "Welcome back";
  const openRate = rate(s.opened, s.delivered);
  const clickRate = rate(s.clicked, s.delivered);
  const bounceRate = rate(s.bounced, s.emails_sent);
  const click = (label) => { const v = RECIPIENT_STATUS_FILTERS[label]; return v ? { onClick: () => handleStatCardClick(v), active: statusFilter === v } : {}; };

  return (
    <div className="space-y-6">
      <PageHeader
        title={greeting}
        subtitle="Here’s how your email program is performing."
        actions={<button className="btn-primary" onClick={() => navigate("/campaigns/create")}><Icon name="plus" className="h-4 w-4" /> Create campaign</button>}
      />

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-4">
        <StatCard label="Total contacts" value={s.total_contacts ?? 0} icon="users" />
        <StatCard label="Total campaigns" value={s.total_campaigns ?? 0} icon="send" tone="violet" hint={`${s.scheduled_campaigns ?? 0} scheduled`} />
        <StatCard label="Emails sent" value={s.emails_sent ?? 0} icon="mail" tone="sky" {...click("Emails Sent")} />
        <StatCard label="Emails delivered" value={s.delivered ?? 0} icon="checkCircle" tone="green" hint={fmtRate(rate(s.delivered, s.emails_sent)) + " of sent"} {...click("Delivered")} />
        <StatCard label="Open rate" value={fmtRate(openRate)} icon="mailOpen" hint={`${(s.opened ?? 0).toLocaleString()} opened of delivered`} {...click("Opened")} />
        <StatCard label="Click rate" value={fmtRate(clickRate)} icon="pointer" tone="violet" hint={`${(s.clicked ?? 0).toLocaleString()} clicked of delivered`} {...click("Clicked")} />
        <StatCard label="Bounce rate" value={fmtRate(bounceRate)} icon="ban" tone="red" hint={`${(s.bounced ?? 0).toLocaleString()} bounced of sent`} {...click("Bounced")} />
        <StatCard label="Unsubscribed" value={s.unsubscribed ?? 0} icon="user" tone="amber" hint={`${(s.spam_complaints ?? 0).toLocaleString()} spam complaints`} {...click("Unsubscribed")} />
      </div>
      <p className="-mt-3 text-xs text-slate-500">Select a metric to list the matching recipients across all campaigns. Select it again to clear.</p>

      {statusFilter && (
        <RecipientsPanel recipients={recipients} statusFilter={statusFilter} onClear={() => applyStatusFilter(null)} hasMore={recipientsHasMore}
          loadingMore={loadingMoreRecipients} onLoadMore={loadMoreRecipients} loading={loadingRecipients} totalCount={recipientsTotal} showCampaignColumn />
      )}

      {/* Charts */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <ChartCard className="xl:col-span-2" title="Campaign performance overview" subtitle="How emails move from sent to clicked, across all campaigns" empty={(s.emails_sent ?? 0) === 0 && "Send your first campaign to see performance here."}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={funnel} layout="vertical" margin={{ left: 8, right: 24 }}>
              <CartesianGrid horizontal={false} stroke={CHART_COLORS.grid} strokeDasharray="3 3" />
              <XAxis type="number" tick={{ fontSize: 12, fill: "#64748b" }} allowDecimals={false} axisLine={false} tickLine={false} />
              <YAxis type="category" dataKey="name" tick={{ fontSize: 12, fill: "#475569" }} width={78} axisLine={false} tickLine={false} />
              <Tooltip contentStyle={chartTooltipStyle} cursor={{ fill: "#f1f5f9" }} />
              <Bar dataKey="value" radius={[0, 6, 6, 0]} barSize={26}>{funnel.map((d) => <Cell key={d.name} fill={d.fill} />)}</Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Delivery outcomes" subtitle="Share of tracked results" empty={outcomes.length === 0 && "No delivery data yet."}>
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={outcomes} dataKey="value" nameKey="name" innerRadius="58%" outerRadius="82%" paddingAngle={2} stroke="none">
                {outcomes.map((o) => <Cell key={o.name} fill={o.fill} />)}
              </Pie>
              <Tooltip contentStyle={chartTooltipStyle} />
            </PieChart>
          </ResponsiveContainer>
          <ul className="mt-1 flex flex-wrap justify-center gap-x-4 gap-y-1 text-xs text-slate-600">
            {outcomes.map((o) => <li key={o.name} className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ background: o.fill }} />{o.name}</li>)}
          </ul>
        </ChartCard>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <ChartCard className="xl:col-span-2" title="Email sending activity" subtitle="Recipients per recent campaign, oldest to newest" empty={sendingActivity.length === 0 && "No campaigns yet."}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={sendingActivity} margin={{ left: -12, right: 8 }}>
              <CartesianGrid vertical={false} stroke={CHART_COLORS.grid} strokeDasharray="3 3" />
              <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#64748b" }} axisLine={false} tickLine={false} interval={0} />
              <YAxis tick={{ fontSize: 12, fill: "#64748b" }} allowDecimals={false} axisLine={false} tickLine={false} />
              <Tooltip contentStyle={chartTooltipStyle} cursor={{ fill: "#f1f5f9" }} labelFormatter={(_, p) => p?.[0]?.payload?.full} />
              <Bar dataKey="recipients" name="Recipients" fill={CHART_COLORS.primary} radius={[6, 6, 0, 0]} maxBarSize={44} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <QuotaCard />
      </div>

      {/* Lists */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <div className="card overflow-hidden xl:col-span-2">
          <div className="card-header">
            <h2 className="card-title">Recent campaigns</h2>
            <Link to="/campaigns" className="link text-sm">View all</Link>
          </div>
          {recentCampaigns.length === 0 ? (
            <EmptyState icon="send" title="No campaigns yet" description="Your latest campaigns will appear here." action={<Link to="/campaigns/create" className="btn-primary"><Icon name="plus" className="h-4 w-4" /> Create campaign</Link>} />
          ) : (
            <div className="table-wrap scroll-thin">
              <table className="min-w-full divide-y divide-slate-100">
                <thead className="bg-slate-50/70"><tr><th className="th">Campaign</th><th className="th">Recipients</th><th className="th">Status</th></tr></thead>
                <tbody className="divide-y divide-slate-100">
                  {recentCampaigns.slice(0, 5).map((c) => (
                    <tr key={c.id} className="transition-colors hover:bg-slate-50/80">
                      <td className="px-4 py-3"><Link to={`/campaigns/${c.id}`} className="row-link text-sm">{c.name}</Link><p className="truncate text-xs text-slate-500">{c.subject}</p></td>
                      <td className="td tabular-nums">{Number(c.recipient_count ?? 0).toLocaleString()}</td>
                      <td className="px-4 py-3"><StatusBadge status={c.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="space-y-6">
          <div className="card">
            <div className="card-header"><h2 className="card-title">Provider status</h2><Icon name="server" className="h-4 w-4 text-slate-400" /></div>
            {!providers ? (
              <p className="p-5 text-sm text-slate-500">Provider information isn’t available right now.</p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {providers.options.map((o) => (
                  <li key={o.name} className="flex items-start justify-between gap-3 px-5 py-3">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-slate-900">{o.label}{o.name === providers.default && <span className="ml-2 rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-medium text-brand-700">Default</span>}</p>
                      {!o.usable && o.reason && <p className="mt-0.5 text-xs text-slate-500">{o.reason}</p>}
                    </div>
                    <span className={`badge ${o.usable ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"}`}><span className={`h-1.5 w-1.5 rounded-full ${o.usable ? "bg-emerald-500" : "bg-slate-400"}`} />{o.usable ? "Available" : "Unavailable"}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="card">
            <div className="card-header"><h2 className="card-title">Upcoming sends</h2><Link to="/scheduled" className="link text-sm">View all</Link></div>
            {upcoming.length === 0 ? <p className="p-5 text-sm text-slate-500">Nothing is scheduled.</p> : (
              <ul className="divide-y divide-slate-100">
                {upcoming.map((u) => (
                  <li key={u.id} className="px-5 py-3">
                    <Link to={`/campaigns/${u.campaign}`} className="row-link text-sm">{u.campaign_name}</Link>
                    <p className="mt-0.5 text-xs text-slate-500">{new Date(u.scheduled_at).toLocaleString()} · {u.timezone}</p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <div className="card xl:col-span-2">
          <div className="card-header"><h2 className="card-title">Recent activity</h2></div>
          {activity.length === 0 ? <p className="p-5 text-sm text-slate-500">Activity from your campaigns will show up here.</p> : (
            <ul className="divide-y divide-slate-100">
              {activity.map((a) => (
                <li key={a.key} className="flex items-center gap-3 px-5 py-3">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-500"><Icon name={a.icon} className="h-4 w-4" /></span>
                  <p className="min-w-0 flex-1 text-sm text-slate-700">{a.text}</p>
                  <time className="hidden shrink-0 text-xs text-slate-500 sm:block">{new Date(a.at).toLocaleString()}</time>
                  <StatusBadge status={a.status} />
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="card">
          <div className="card-header"><h2 className="card-title">Quick actions</h2></div>
          <div className="grid gap-2 p-4">
            {QUICK_ACTIONS.map((a) => (
              <Link key={a.label} to={a.to} className={`${a.primary ? "btn-primary" : "btn-secondary"} justify-start`}><Icon name={a.icon} className="h-4 w-4" /> {a.label}</Link>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
