import { isCompanyAdmin, isPlatformAdmin } from "../utils/roles";

// Navigation is built per signed-in user so only authorised areas appear. This is a UX filter only:
// the backend remains the authority on every request, and RoleRoute still guards the routes themselves.

const CONTACT_PATHS = ["/contacts", "/contacts/lists", "/contacts/tags", "/contacts/segments"];

export function userNav(user) {
  const admin = [{ label: "Settings", to: "/settings", icon: "settings" }];
  if (isCompanyAdmin(user)) admin.push({ label: "Company Administration", to: "/company", icon: "building" });
  if (isPlatformAdmin(user)) admin.push({ label: "Platform Administration", to: "/platform", icon: "shield" });

  return [
    {
      title: "Main",
      items: [
        { label: "Dashboard", to: "/dashboard", icon: "grid" },
        {
          label: "Contacts & Lists", icon: "users", to: "/contacts", matchPaths: CONTACT_PATHS,
          children: [
            { label: "All contacts", to: "/contacts", end: true },
            { label: "Lists", to: "/contacts/lists" },
            { label: "Tags", to: "/contacts/tags" },
            { label: "Segments", to: "/contacts/segments" },
          ],
        },
        { label: "Campaigns", to: "/campaigns", icon: "send" },
        { label: "Scheduled Campaigns", to: "/scheduled", icon: "clock" },
        { label: "Templates", to: "/templates", icon: "template" },
        { label: "Analytics", to: "/analytics", icon: "chart" },
      ],
    },
    {
      title: "Automation",
      items: [
        { label: "Automations", to: "/automations", icon: "bolt" },
        { label: "Signup Forms", to: "/contacts/signup-forms", icon: "form" },
      ],
    },
    { title: "Administration", items: admin },
  ];
}

export const COMPANY_NAV = [
  { items: [{ label: "Overview", to: "/company", icon: "grid", end: true }] },
  {
    title: "Manage",
    items: [
      { label: "Members & invitations", to: "/company/members", icon: "users" },
      { label: "Quotas & usage", to: "/company/quotas", icon: "activity" },
      { label: "Campaign activity", to: "/company/campaigns", icon: "send" },
      { label: "Analytics", to: "/company/analytics", icon: "chart" },
      { label: "Suppressions", to: "/company/suppressions", icon: "ban" },
      { label: "Activity log", to: "/company/audit", icon: "list" },
      { label: "Company & plan", to: "/company/settings", icon: "settings" },
    ],
  },
];

export const PLATFORM_NAV = [
  { items: [{ label: "Overview", to: "/platform", icon: "grid", end: true }] },
  {
    title: "Tenants",
    items: [
      { label: "Companies", to: "/platform/companies", icon: "building" },
      { label: "Users", to: "/platform/users", icon: "users" },
      { label: "Plans & quotas", to: "/platform/plans", icon: "layers" },
    ],
  },
  {
    title: "Sending",
    items: [
      { label: "Providers & limits", to: "/platform/providers", icon: "server" },
      { label: "Queue & failures", to: "/platform/queue", icon: "clock" },
      { label: "Campaign monitor", to: "/platform/campaigns", icon: "send" },
      { label: "Analytics", to: "/platform/analytics", icon: "chart" },
    ],
  },
  {
    title: "Operations",
    items: [
      { label: "System health", to: "/platform/health", icon: "heart" },
      { label: "Audit log", to: "/platform/audit", icon: "shield" },
    ],
  },
];

const LABELS = {
  dashboard: "Dashboard", contacts: "Contacts", lists: "Lists", tags: "Tags", segments: "Segments", "signup-forms": "Signup Forms",
  automations: "Automations", templates: "Templates", campaigns: "Campaigns", scheduled: "Scheduled Campaigns", analytics: "Analytics",
  settings: "Settings", company: "Company Administration", platform: "Platform Administration", members: "Members & invitations",
  quotas: "Quotas & usage", suppressions: "Suppressions", audit: "Activity log", providers: "Providers & limits", queue: "Queue & failures",
  companies: "Companies", users: "Users", plans: "Plans & quotas", health: "System health", create: "Create", edit: "Edit",
};

/** Breadcrumb trail for a pathname. Numeric / id-like segments become "Details". */
export function breadcrumbsFor(pathname) {
  const parts = pathname.split("/").filter(Boolean);
  const crumbs = [];
  let acc = "";
  parts.forEach((seg) => {
    acc += `/${seg}`;
    const idLike = /^\d+$/.test(seg) || /^[0-9a-f-]{16,}$/i.test(seg);
    const label = LABELS[seg] || (idLike ? "Details" : seg.replace(/[-_]/g, " ").replace(/^./, (c) => c.toUpperCase()));
    crumbs.push({ label, to: acc, id: idLike });
  });
  // "/contacts/signup-forms" reads better as Signup Forms alone.
  if (parts[0] === "contacts" && parts[1] === "signup-forms") return [{ label: "Signup Forms", to: "/contacts/signup-forms" }];
  // Ids have no page of their own to link to when followed by an action (edit); keep the link on the detail crumb only.
  return crumbs;
}

export function flattenNav(sections) {
  const out = [];
  sections.forEach((s) => s.items.forEach((i) => {
    if (i.children) i.children.forEach((c) => out.push({ label: c.label === "All contacts" ? "Contacts" : c.label, to: c.to, icon: i.icon, group: s.title }));
    else out.push({ label: i.label, to: i.to, icon: i.icon, group: s.title });
  }));
  return out;
}
