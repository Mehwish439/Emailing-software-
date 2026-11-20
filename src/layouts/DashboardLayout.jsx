import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import Avatar from "../components/Avatar";
import CommandPalette from "../components/CommandPalette";
import Dropdown, { MenuItem } from "../components/Dropdown";
import Icon from "../components/Icon";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { ROLE_LABELS, isCompanyAdmin, isPlatformAdmin } from "../utils/roles";
import { COMPANY_NAV, PLATFORM_NAV, breadcrumbsFor, flattenNav, userNav } from "./navigation";

const itemBase = "group relative flex items-center gap-3 rounded-lg text-sm font-medium transition-colors";
const itemState = (active) => (active ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900");

function ActiveBar() {
  return <span className="absolute -left-3 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-brand-600" aria-hidden="true" />;
}

function NavGroup({ item, collapsed, pathname }) {
  const groupActive = item.matchPaths.includes(pathname);
  const [open, setOpen] = useState(groupActive);
  useEffect(() => { if (groupActive) setOpen(true); }, [groupActive]);

  if (collapsed) {
    return (
      <NavLink to={item.to} title={item.label} aria-label={item.label} className={`${itemBase} h-10 justify-center ${itemState(groupActive)}`}>
        {groupActive && <ActiveBar />}
        <Icon name={item.icon} />
      </NavLink>
    );
  }
  return (
    <div>
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className={`${itemBase} w-full px-3 py-2 ${itemState(groupActive && !open)}`}>
        {groupActive && <ActiveBar />}
        <Icon name={item.icon} />
        <span className="flex-1 text-left">{item.label}</span>
        <Icon name="chevronDown" className={`h-4 w-4 text-slate-400 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="ml-[22px] mt-1 space-y-0.5 border-l border-slate-200 pl-3">
          {item.children.map((c) => (
            <NavLink key={c.to} to={c.to} end={c.end}
              className={({ isActive }) => `block rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors ${isActive ? "text-brand-700 bg-brand-50" : "text-slate-500 hover:text-slate-900 hover:bg-slate-100"}`}>
              {c.label}
            </NavLink>
          ))}
        </div>
      )}
    </div>
  );
}

function SidebarContent({ sections, switchLinks, collapsed, pathname, user, onLogout, onNavigate, areaLabel }) {
  return (
    <>
      <div className={`flex h-16 shrink-0 items-center border-b border-slate-100 ${collapsed ? "justify-center" : "gap-3 px-5"}`}>
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 text-sm font-bold text-white shadow-sm">Q</div>
        {!collapsed && (
          <div className="min-w-0 leading-tight">
            <p className="truncate font-semibold text-slate-900">QRM Campaigns</p>
            {areaLabel && <p className="text-[11px] text-slate-500">{areaLabel}</p>}
          </div>
        )}
      </div>

      <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-4 scroll-thin" aria-label="Main navigation" onClick={onNavigate}>
        {switchLinks.length > 0 && (
          <div className="space-y-1">
            {!collapsed && <p className="mb-1.5 px-3 text-xs font-medium text-slate-400">Switch area</p>}
            {switchLinks.map((l) => (
              <Link key={l.to} to={l.to} title={l.label} className={`${itemBase} ${collapsed ? "h-10 justify-center" : "px-3 py-2"} text-slate-600 hover:bg-slate-100 hover:text-slate-900`}>
                <Icon name={l.icon} />
                {!collapsed && l.label}
              </Link>
            ))}
          </div>
        )}
        {sections.map((section, idx) => (
          <div key={idx}>
            {section.title && !collapsed && <p className="mb-1.5 px-3 text-xs font-medium text-slate-400">{section.title}</p>}
            {section.title && collapsed && idx > 0 && <div className="mx-3 mb-2 border-t border-slate-100" />}
            <div className="space-y-0.5">
              {section.items.map((item) =>
                item.children ? (
                  <NavGroup key={item.label} item={item} collapsed={collapsed} pathname={pathname} />
                ) : (
                  <NavLink key={item.to} to={item.to} end={item.end} title={collapsed ? item.label : undefined} aria-label={item.label}
                    className={({ isActive }) => `${itemBase} ${collapsed ? "h-10 justify-center" : "px-3 py-2"} ${itemState(isActive)}`}>
                    {({ isActive }) => (<>
                      {isActive && <ActiveBar />}
                      <Icon name={item.icon} />
                      {!collapsed && <span className="truncate">{item.label}</span>}
                    </>)}
                  </NavLink>
                )
              )}
            </div>
          </div>
        ))}
      </nav>

      <div className="shrink-0 border-t border-slate-100 p-3">
        <div className={`flex items-center ${collapsed ? "flex-col gap-2" : "gap-3 rounded-xl p-2"}`}>
          <Avatar name={user?.first_name || user?.username} />
          {!collapsed && (
            <div className="min-w-0 flex-1 leading-tight">
              <p className="truncate text-sm font-medium text-slate-900">{user?.first_name || user?.username}</p>
              <p className="truncate text-xs text-slate-500">{ROLE_LABELS[user?.role] || "User"}</p>
            </div>
          )}
          <button onClick={onLogout} className="btn-icon" title="Log out" aria-label="Log out"><Icon name="logout" className="h-4 w-4" /></button>
        </div>
      </div>
    </>
  );
}

export default function DashboardLayout() {
  const { user, logout } = useAuth();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem("sidebar_collapsed") === "1"; } catch { return false; }
  });
  useEffect(() => { try { localStorage.setItem("sidebar_collapsed", collapsed ? "1" : "0"); } catch { /* storage unavailable */ } }, [collapsed]);
  useEffect(() => { setMobileOpen(false); }, [location.pathname]);

  // Ctrl/⌘ + K opens quick navigation.
  useEffect(() => {
    const onKey = (e) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPaletteOpen((o) => !o); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // The navigation shown follows the area being viewed; backend permissions remain authoritative.
  const area = location.pathname.startsWith("/platform") ? "platform" : location.pathname.startsWith("/company") ? "company" : "user";
  const sections = useMemo(() => (area === "platform" ? PLATFORM_NAV : area === "company" ? COMPANY_NAV : userNav(user)), [area, user]);
  const areaLabel = area === "platform" ? "Platform administration" : area === "company" ? "Company administration" : null;
  const switchLinks = [
    area !== "user" && { to: "/dashboard", label: "My workspace", icon: "send" },
    isCompanyAdmin(user) && area !== "company" && area !== "user" && { to: "/company", label: "Company administration", icon: "building" },
    isPlatformAdmin(user) && area !== "platform" && area !== "user" && { to: "/platform", label: "Platform administration", icon: "shield" },
  ].filter(Boolean);

  const paletteEntries = useMemo(() => {
    const quick = area === "user" ? [
      { label: "Create campaign", to: "/campaigns/create", icon: "plus", group: "Quick action" },
      { label: "Create template", to: "/templates/create", icon: "plus", group: "Quick action" },
      { label: "Create automation", to: "/automations/create", icon: "plus", group: "Quick action" },
    ] : [];
    return [...flattenNav(sections), ...quick];
  }, [sections, area]);

  const crumbs = breadcrumbsFor(location.pathname);

  const handleLogout = async () => {
    try {
      await logout();
      showToast("Logged out successfully.", "success");
    } catch {
      showToast("Failed to log out cleanly, but you have been signed out locally.", "info");
    }
    navigate("/login");
  };

  const sidebarProps = { sections, switchLinks, pathname: location.pathname, user, onLogout: handleLogout, areaLabel };

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-[70] focus:rounded-lg focus:bg-white focus:px-3 focus:py-2 focus:text-sm focus:shadow-pop">Skip to content</a>

      <aside className={`hidden shrink-0 flex-col border-r border-slate-200 bg-white transition-[width] duration-200 md:flex ${collapsed ? "w-[72px]" : "w-64"}`}>
        <SidebarContent {...sidebarProps} collapsed={collapsed} />
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="absolute inset-0 bg-slate-900/40 backdrop-blur-[2px]" onClick={() => setMobileOpen(false)} />
          <aside className="relative flex h-full w-72 max-w-[85vw] animate-toast-in flex-col bg-white shadow-pop">
            <SidebarContent {...sidebarProps} collapsed={false} onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 shrink-0 items-center justify-between gap-3 border-b border-slate-200 bg-white/90 px-4 backdrop-blur md:px-6">
          <div className="flex min-w-0 items-center gap-2">
            <button className="btn-icon md:hidden" aria-label="Open navigation" onClick={() => setMobileOpen(true)}><Icon name="menu" /></button>
            <button className="btn-icon hidden md:inline-flex" aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} aria-pressed={collapsed} onClick={() => setCollapsed((c) => !c)}>
              <Icon name="sidebar" className="h-[18px] w-[18px]" />
            </button>
            <nav aria-label="Breadcrumb" className="min-w-0">
              <ol className="flex min-w-0 items-center gap-1.5 text-sm">
                {crumbs.map((c, i) => {
                  const last = i === crumbs.length - 1;
                  return (
                    <li key={c.to} className={`flex min-w-0 items-center gap-1.5 ${last ? "" : "hidden sm:flex"}`}>
                      {i > 0 && <Icon name="chevronRight" className="h-3.5 w-3.5 text-slate-300" />}
                      {last ? <span aria-current="page" className="truncate font-semibold text-slate-900">{c.label}</span>
                        : c.id ? <span className="text-slate-500">{c.label}</span>
                        : <Link to={c.to} className="truncate text-slate-500 hover:text-slate-900">{c.label}</Link>}
                    </li>
                  );
                })}
              </ol>
            </nav>
          </div>

          <div className="flex items-center gap-2">
            <button onClick={() => setPaletteOpen(true)} aria-label="Search pages"
              className="hidden h-9 items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 text-sm text-slate-500 transition hover:border-slate-300 hover:bg-white sm:flex sm:w-56">
              <Icon name="search" className="h-4 w-4" />
              <span className="flex-1 text-left">Search pages…</span>
              <kbd className="rounded border border-slate-200 bg-white px-1.5 text-[10px] font-medium text-slate-400">Ctrl K</kbd>
            </button>
            <button onClick={() => setPaletteOpen(true)} className="btn-icon sm:hidden" aria-label="Search pages"><Icon name="search" /></button>

            <Dropdown width="w-64" trigger={({ toggle, open }) => (
              <button onClick={toggle} aria-haspopup="menu" aria-expanded={open} className="flex items-center gap-2 rounded-lg p-1 pr-2 transition hover:bg-slate-100">
                <Avatar name={user?.first_name || user?.username} size="h-8 w-8" text="text-xs" />
                <Icon name="chevronDown" className="hidden h-4 w-4 text-slate-400 sm:block" />
              </button>
            )}>
              <div className="px-2.5 py-2">
                <p className="truncate text-sm font-semibold text-slate-900">{user?.first_name || user?.username}</p>
                <p className="truncate text-xs text-slate-500">{user?.email}</p>
                <p className="mt-1 inline-flex rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-medium text-brand-700">{ROLE_LABELS[user?.role] || "User"}</p>
              </div>
              <div className="my-1 border-t border-slate-100" />
              <MenuItem as={Link} to="/settings"><Icon name="settings" className="h-4 w-4" /> Account settings</MenuItem>
              {isCompanyAdmin(user) && <MenuItem as={Link} to="/company"><Icon name="building" className="h-4 w-4" /> Company administration</MenuItem>}
              {isPlatformAdmin(user) && <MenuItem as={Link} to="/platform"><Icon name="shield" className="h-4 w-4" /> Platform administration</MenuItem>}
              <div className="my-1 border-t border-slate-100" />
              <MenuItem onClick={handleLogout} danger><Icon name="logout" className="h-4 w-4" /> Log out</MenuItem>
            </Dropdown>
          </div>
        </header>

        <main id="main" className="flex-1 overflow-y-auto scroll-thin">
          <div key={location.pathname} className="mx-auto w-full max-w-[1400px] animate-page-in p-4 md:p-6 lg:p-8">
            <Outlet />
          </div>
        </main>
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} entries={paletteEntries} />
    </div>
  );
}
