import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

const NAV_SECTIONS = [
  {
    items: [{ label: "Dashboard", to: "/dashboard", icon: "grid" }],
  },
  {
    title: "Contacts",
    items: [
      { label: "All Contacts", to: "/contacts", icon: "users" },
      { label: "Lists", to: "/contacts/lists", icon: "list" },
    ],
  },
  {
    title: "Campaigns",
    items: [
      { label: "All Campaigns", to: "/campaigns", icon: "send" },
      { label: "Scheduled", to: "/scheduled", icon: "clock" },
    ],
  },
  {
    items: [
      { label: "Templates", to: "/templates", icon: "template" },
      { label: "Analytics", to: "/analytics", icon: "chart" },
      { label: "Settings", to: "/settings", icon: "settings" },
    ],
  },
];

const ICONS = {
  grid: (
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
  ),
  users: (
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M17 20h5v-2a4 4 0 00-3-3.87M9 20H4v-2a4 4 0 013-3.87m6-4a4 4 0 11-8 0 4 4 0 018 0zm6 0a4 4 0 11-8 0 4 4 0 018 0z" />
  ),
  list: (
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M4 6h16M4 12h16M4 18h7" />
  ),
  send: (
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
  ),
  clock: (
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
  ),
  template: (
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M9 17.25V21m6-3.75V21M5 3h14a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2z" />
  ),
  chart: (
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M9 19v-6M15 19v-10M4 5v14a2 2 0 002 2h12a2 2 0 002-2V5" />
  ),
  settings: (
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
  ),
};

function Icon({ name }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      {ICONS[name]}
    </svg>
  );
}

export default function DashboardLayout() {
  const { user, logout } = useAuth();
  const { showToast } = useToast();
  const navigate = useNavigate();

  const handleLogout = async () => {
    try {
      await logout();
      showToast("Logged out successfully.", "success");
      navigate("/login");
    } catch {
      showToast("Failed to log out cleanly, but you have been signed out locally.", "info");
      navigate("/login");
    }
  };

  return (
    <div className="min-h-screen flex bg-slate-50">
      <aside className="hidden md:flex w-64 flex-col bg-white border-r border-slate-200">
        <div className="flex items-center gap-2 px-6 h-16 border-b border-slate-200">
          <div className="h-8 w-8 rounded-lg bg-brand-600 flex items-center justify-center text-white font-bold">Q</div>
          <span className="font-semibold text-slate-900">QRM</span>
        </div>
        <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-6">
          {NAV_SECTIONS.map((section, idx) => (
            <div key={idx}>
              {section.title && (
                <p className="px-3 mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
                  {section.title}
                </p>
              )}
              <div className="space-y-1">
                {section.items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={({ isActive }) =>
                      `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                        isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100"
                      }`
                    }
                  >
                    <Icon name={item.icon} />
                    {item.label}
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-16 flex items-center justify-between px-4 md:px-6 border-b border-slate-200 bg-white">
          <div className="flex-1 max-w-md">
            <input type="search" placeholder="Search…" className="input" />
          </div>
          <div className="flex items-center gap-4">
            <div className="text-right hidden sm:block">
              <p className="text-sm font-medium text-slate-900">{user?.first_name || user?.username}</p>
              <p className="text-xs text-slate-500">{user?.email}</p>
            </div>
            <div className="h-9 w-9 rounded-full bg-brand-100 text-brand-700 flex items-center justify-center font-semibold">
              {(user?.first_name?.[0] || user?.username?.[0] || "?").toUpperCase()}
            </div>
            <button onClick={handleLogout} className="btn-secondary">
              Logout
            </button>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
