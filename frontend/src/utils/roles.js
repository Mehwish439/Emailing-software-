// Role names come from the backend (accounts.User.Role): "user", "company_admin", "super_admin".
// The backend remains authoritative; this only decides which screens to show.
export const ROLES = { USER: "user", COMPANY_ADMIN: "company_admin", SUPER_ADMIN: "super_admin" };

export const isPlatformAdmin = (user) => user?.role === ROLES.SUPER_ADMIN;
export const isCompanyAdmin = (user) => user?.role === ROLES.COMPANY_ADMIN && !!user?.company;

export function homePathFor(user) {
  if (isPlatformAdmin(user)) return "/platform";
  if (isCompanyAdmin(user)) return "/company";
  return "/dashboard";
}

export const ROLE_LABELS = { user: "User", company_admin: "Company admin", super_admin: "Platform admin" };

/** Can this user open this path? (UX only — backend permissions are authoritative.) */
export function canAccessPath(user, path = "") {
  if (path.startsWith("/platform")) return isPlatformAdmin(user);
  if (path.startsWith("/company")) return isCompanyAdmin(user);
  return true;
}

/** Login tabs. Choosing a tab grants NOTHING: the backend authenticates and returns the real role. */
export const ACCOUNT_TYPES = [
  { key: "company_admin", label: "Company Admin", hint: "You manage your company's team, limits and campaigns." },
  { key: "user", label: "Company User", hint: "You are an employee or member of a company." },
  { key: "super_admin", label: "SaaS Super Admin", hint: "Platform owner or authorised platform administrator." },
];
export const DASHBOARD_NAMES = { user: "User dashboard", company_admin: "Company Admin dashboard", super_admin: "SaaS Super Admin dashboard" };
