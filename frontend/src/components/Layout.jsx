import React from "react";
import { NavLink, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, Users, GitBranch, ListChecks, Activity,
  BarChart3, UserCog, LogOut, Search, Bell, Sparkles,
} from "lucide-react";
import { useAuth } from "../lib/auth";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, exact: true },
  { to: "/contacts", label: "Contacts", icon: Users },
  { to: "/pipeline", label: "Pipeline", icon: GitBranch },
  { to: "/activities", label: "Activities", icon: Activity },
  { to: "/tasks", label: "Tasks", icon: ListChecks },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/team", label: "Team & Roles", icon: UserCog },
];

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [query, setQuery] = React.useState("");
  const [results, setResults] = React.useState(null);
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    if (!query.trim()) { setResults(null); return; }
    const t = setTimeout(async () => {
      try {
        const api = (await import("../lib/api")).default;
        const { data } = await api.get(`/search`, { params: { q: query } });
        setResults(data);
        setOpen(true);
      } catch {}
    }, 250);
    return () => clearTimeout(t);
  }, [query]);

  return (
    <div className="min-h-screen flex bg-white" data-testid="app-layout">
      {/* Sidebar */}
      <aside className="w-60 shrink-0 bg-[#F8F9FA] border-r border-[#DFE1E6] flex flex-col" data-testid="sidebar">
        <div className="h-14 flex items-center gap-2 px-5 border-b border-[#DFE1E6]">
          <div className="h-7 w-7 rounded-md bg-[#0052CC] flex items-center justify-center text-white font-bold font-heading">T</div>
          <div>
            <div className="font-heading font-bold text-[#091E42] leading-none">TrataCRM</div>
            <div className="text-[10px] text-[#5E6C84] tracking-wider uppercase mt-0.5">Master Console</div>
          </div>
        </div>

        <nav className="flex-1 p-3 space-y-1">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.exact}
              data-testid={`nav-${n.label.toLowerCase().replace(/\s+/g, "-")}`}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 text-sm rounded-md transition-colors ${
                  isActive
                    ? "bg-[#0052CC] text-white"
                    : "text-[#42526E] hover:bg-white hover:text-[#091E42]"
                }`
              }
            >
              <n.icon className="h-4 w-4" strokeWidth={1.75} />
              <span className="font-medium">{n.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-[#DFE1E6] p-3">
          <div className="flex items-center gap-3 mb-3">
            <div className="h-9 w-9 rounded-full bg-[#091E42] text-white flex items-center justify-center font-heading font-bold text-sm">
              {(user?.name || "MA").split(" ").map((p) => p[0]).slice(0, 2).join("")}
            </div>
            <div className="min-w-0">
              <div className="text-sm font-semibold text-[#091E42] truncate">{user?.name}</div>
              <div className="text-[11px] text-[#5E6C84] truncate">{user?.is_master_admin ? "Master Admin" : user?.role}</div>
            </div>
          </div>
          <button
            data-testid="logout-btn"
            onClick={() => { logout(); navigate("/login"); }}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm text-[#42526E] hover:text-[#FF5630] hover:bg-white rounded-md transition-colors"
          >
            <LogOut className="h-4 w-4" /> Logout
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 min-w-0 flex flex-col">
        <header className="h-14 flex items-center gap-4 px-6 border-b border-[#DFE1E6] bg-white sticky top-0 z-30" data-testid="topbar">
          <div className="relative flex-1 max-w-xl">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#5E6C84]" />
            <input
              data-testid="global-search-input"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onFocus={() => results && setOpen(true)}
              onBlur={() => setTimeout(() => setOpen(false), 200)}
              placeholder="Search contacts, activities, tasks…"
              className="w-full pl-9 pr-3 py-2 text-sm bg-[#F1F2F4] border border-transparent rounded-md focus:bg-white focus:border-[#4C9AFF] focus:ring-2 focus:ring-[#4C9AFF]/30 outline-none"
            />
            {open && results && (
              <div className="absolute top-full mt-1 left-0 right-0 bg-white border border-[#DFE1E6] rounded-md shadow-lg max-h-96 overflow-auto z-50" data-testid="search-results">
                <SearchSection title="Contacts" items={results.contacts} onClick={(i) => { navigate(`/contacts/${i.id}`); setOpen(false); }} />
                <SearchSection title="Activities" items={results.activities} renderSub={(i) => `${i.category} · ${i.status}`} />
                <SearchSection title="Tasks" items={results.tasks} renderSub={(i) => `${i.status} · ${i.priority}`} />
                {(!results.contacts.length && !results.activities.length && !results.tasks.length) && (
                  <div className="p-4 text-sm text-[#5E6C84]">No results</div>
                )}
              </div>
            )}
          </div>
          <button
            onClick={() => navigate("/activities")}
            className="flex items-center gap-2 px-3 py-2 text-sm text-[#42526E] hover:bg-[#F1F2F4] rounded-md"
            data-testid="topbar-notifications-btn"
          >
            <Bell className="h-4 w-4" /> Notifications
          </button>
          <div className="flex items-center gap-2 px-3 py-1.5 bg-gradient-to-r from-[#0052CC] to-[#00B8D9] text-white rounded-md text-xs font-semibold">
            <Sparkles className="h-3.5 w-3.5" /> AI Insights Active
          </div>
        </header>
        <div className="flex-1 min-w-0 overflow-x-hidden">{children}</div>
      </main>
    </div>
  );
}

function SearchSection({ title, items, onClick, renderSub }) {
  if (!items || !items.length) return null;
  return (
    <div className="py-2">
      <div className="overline px-4 pb-1">{title}</div>
      {items.map((i) => (
        <button
          key={i.id}
          onClick={() => onClick?.(i)}
          className="w-full text-left px-4 py-2 hover:bg-[#F8F9FA] flex items-center justify-between gap-3"
        >
          <span className="text-sm text-[#091E42] truncate">{i.name || i.title}</span>
          <span className="text-[11px] text-[#5E6C84] truncate">{renderSub ? renderSub(i) : (i.type || i.phone || "")}</span>
        </button>
      ))}
    </div>
  );
}
