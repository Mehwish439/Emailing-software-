import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import Avatar from "../components/Avatar";
import Icon from "../components/Icon";
import PageHeader from "../components/PageHeader";
import QuotaCard from "../components/QuotaCard";
import Tabs from "../components/Tabs";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import api from "../services/api";
import { updateProfile } from "../services/authService";
import { formatApiError } from "../utils/formatError";
import { ROLE_LABELS, isCompanyAdmin, isPlatformAdmin } from "../utils/roles";

const TABS = [
  { key: "profile", label: "General" },
  { key: "account", label: "Account" },
  { key: "sending", label: "Sending quota" },
  { key: "providers", label: "Email providers" },
];

function Section({ title, description, children, footer }) {
  return (
    <section className="card overflow-hidden">
      <div className="grid gap-6 p-5 sm:p-6 lg:grid-cols-[260px_1fr]">
        <div><h2 className="card-title">{title}</h2>{description && <p className="mt-1 text-sm text-slate-500">{description}</p>}</div>
        <div>{children}</div>
      </div>
      {footer && <div className="flex justify-end border-t border-slate-100 bg-slate-50/60 px-5 py-3 sm:px-6">{footer}</div>}
    </section>
  );
}

function ProvidersPanel() {
  const [info, setInfo] = useState(undefined);
  useEffect(() => { api.get("/campaigns/providers/").then((r) => setInfo(r.data)).catch(() => setInfo(null)); }, []);
  const { user } = useAuth();
  return (
    <Section title="Email providers" description="Which sending providers your account can use. Credentials are managed by platform administrators and are never shown here.">
      {info === undefined ? <p className="text-sm text-slate-500">Loading providers…</p>
        : info === null ? <p className="text-sm text-slate-500">Provider information isn’t available right now.</p>
        : (
          <ul className="space-y-3">
            {info.options.map((o) => (
              <li key={o.name} className={`flex items-start gap-4 rounded-xl border p-4 ${o.name === info.default ? "border-brand-300 bg-brand-50/40" : "border-slate-200"}`}>
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-white text-slate-600 ring-1 ring-slate-200"><Icon name={o.name === "brevo" ? "send" : "server"} className="h-5 w-5" /></span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-semibold text-slate-900">{o.label}</p>
                    {o.name === info.default && <span className="rounded-full bg-brand-100 px-2 py-0.5 text-[11px] font-medium text-brand-700">Active default</span>}
                  </div>
                  <p className="mt-0.5 text-sm text-slate-500">{o.usable ? "Connected and available for your campaigns." : o.reason || "Not available for this account."}</p>
                </div>
                <span className={`badge ${o.usable ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"}`}><span className={`h-1.5 w-1.5 rounded-full ${o.usable ? "bg-emerald-500" : "bg-slate-400"}`} />{o.usable ? "Available" : "Unavailable"}</span>
              </li>
            ))}
          </ul>
        )}
      {isPlatformAdmin(user) && <Link to="/platform/providers" className="btn-secondary mt-4"><Icon name="settings" className="h-4 w-4" /> Manage providers &amp; limits</Link>}
    </Section>
  );
}

export default function SettingsPage() {
  const { user, setUser } = useAuth();
  const { showToast } = useToast();
  const [tab, setTab] = useState("profile");
  const [form, setForm] = useState({
    first_name: user?.first_name || "",
    last_name: user?.last_name || "",
    company_name: user?.company_name || "",
  });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const updated = await updateProfile(form);
      setUser(updated);
      showToast("Profile updated.", "success");
    } catch (err) {
      showToast(formatApiError(err, "Failed to update profile."), "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader title="Settings" subtitle="Manage your profile, sending limits and email providers." />
      <Tabs tabs={TABS} value={tab} onChange={setTab} />

      {tab === "profile" && (
        <form onSubmit={handleSubmit}>
          <Section
            title="Profile"
            description="Your name appears in the app and on campaigns you create."
            footer={<button type="submit" className="btn-primary" disabled={saving}>{saving ? "Saving…" : "Save changes"}</button>}
          >
            <div className="mb-5 flex items-center gap-4">
              <Avatar name={form.first_name || user?.username} size="h-14 w-14" text="text-lg" />
              <div><p className="text-sm font-medium text-slate-900">{[form.first_name, form.last_name].filter(Boolean).join(" ") || user?.username}</p><p className="text-sm text-slate-500">{user?.email}</p></div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div><label className="label" htmlFor="st-fn">First name</label><input id="st-fn" className="input" autoComplete="given-name" value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} /></div>
              <div><label className="label" htmlFor="st-ln">Last name</label><input id="st-ln" className="input" autoComplete="family-name" value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} /></div>
              <div className="sm:col-span-2"><label className="label" htmlFor="st-co">Company name</label><input id="st-co" className="input" value={form.company_name} onChange={(e) => setForm({ ...form, company_name: e.target.value })} /></div>
            </div>
          </Section>
        </form>
      )}

      {tab === "account" && (
        <Section title="Account" description="Sign-in details and access. Role, company and quotas are managed by your administrators.">
          <dl className="grid gap-4 sm:grid-cols-2">
            {[["Username", user?.username], ["Email", user?.email], ["Role", ROLE_LABELS[user?.role] || "User"], ["Company", user?.company?.name || "—"]].map(([k, v]) => (
              <div key={k}><dt className="label">{k}</dt><dd className="input !bg-slate-50 text-slate-700">{v || "—"}</dd></div>
            ))}
          </dl>
          {(isCompanyAdmin(user) || isPlatformAdmin(user)) && (
            <div className="mt-5 flex flex-wrap gap-2">
              {isCompanyAdmin(user) && <Link to="/company/settings" className="btn-secondary"><Icon name="building" className="h-4 w-4" /> Company &amp; plan</Link>}
              {isPlatformAdmin(user) && <Link to="/platform" className="btn-secondary"><Icon name="shield" className="h-4 w-4" /> Platform administration</Link>}
            </div>
          )}
        </Section>
      )}

      {tab === "sending" && <div className="max-w-3xl"><QuotaCard /></div>}
      {tab === "providers" && <ProvidersPanel />}
    </div>
  );
}
