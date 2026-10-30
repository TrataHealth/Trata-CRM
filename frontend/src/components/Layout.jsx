import React from "react";
import { NavLink, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, Users, GitBranch, ListChecks, Activity, BedDouble, UserCog,
  BarChart3, LogOut, Search, Bell, Sparkles, RefreshCw, Database, Menu, X,
  Building2, ClipboardList, IdCard, Wallet, Compass, Trophy, Settings as SettingsIcon, ShieldCheck,
  UserPlus, HeartPulse, Receipt, Fingerprint, Pill, ShoppingBag, FileText, Radio, CalendarDays,
} from "lucide-react";
import { useAuth } from "../lib/auth";
import api from "../lib/api";
import { relativeTime } from "../lib/constants";
import { LiveBell } from "./LiveUpdates";
import { NewOrderAlerts } from "./pharmacy/NewOrderAlerts";
import { AlertListener } from "./alerts/AlertListener";

const ADMIN_NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, exact: true },
  { to: "/contacts", label: "All Users", icon: Users, exact: true },
  { to: "/admin/notifications", label: "Notification Centre", icon: Bell, masterOnly: true },
  { to: "/admin/audit", label: "Live Audit", icon: ShieldCheck, exact: true, masterOnly: true },
  { section: "Patient app" },
  { to: "/users/patients", label: "Trata Patient Users", icon: Users, masterOnly: true },
  { to: "/admin/audit/patient", label: "Patient Activity", icon: Radio, masterOnly: true },
  { to: "/abha", label: "ABHA (ABDM)", icon: Fingerprint },
  { section: "Provider app" },
  { to: "/users/providers", label: "Trata Providers", icon: Building2, masterOnly: true },
  { to: "/admin/audit/provider", label: "Provider Activity", icon: Radio, masterOnly: true },
  { to: "/admin/onboarding", label: "Onboarding", icon: UserPlus },
  { to: "/admin/kyc-queue", label: "KYC Final Approval", icon: ShieldCheck, badgeKey: "kyc_admin_queue" },
  { to: "/admin/ledger", label: "Provider Ledger", icon: Receipt },
  { section: "Sales & team" },
  { to: "/pipeline", label: "Pipeline", icon: GitBranch },
  { to: "/activities", label: "Activities", icon: Activity },
  { to: "/tasks", label: "Tasks", icon: ListChecks },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/agent/leaderboard", label: "Leaderboard", icon: Trophy },
  { to: "/team", label: "Team & Roles", icon: UserCog },
];

const SALES_NAV = [
  { to: "/agent", label: "My Day", icon: Compass, exact: true },
  { to: "/agent/leads", label: "My Leads", icon: Users },
  { to: "/pipeline", label: "My Pipeline", icon: GitBranch },
  { to: "/activities", label: "My Activity Log", icon: Activity },
  { to: "/tasks", label: "My Tasks", icon: ListChecks },
];

const PROVIDER_NAV = [
  { to: "/provider", label: "My Dashboard", icon: LayoutDashboard, exact: true },
  { to: "/pharmacy/orders", label: "Medicine Orders", icon: ShoppingBag, pharmacyOnly: true },
  { to: "/pharmacy/prescriptions", label: "Prescriptions", icon: FileText, pharmacyOnly: true },
  { to: "/pharmacy/stock", label: "Stock", icon: Pill, pharmacyOnly: true },
  { to: "/pharmacy/sales", label: "Sales", icon: BarChart3, pharmacyOnly: true },
  { to: "/provider/command-center", label: "Command Center", icon: Activity, hospitalOnly: true },
  { to: "/provider/beds", label: "Beds", icon: BedDouble, hospitalOnly: true },
  { to: "/provider/staff", label: "Staff", icon: UserCog, hospitalOnly: true },
  { to: "/provider/patients", label: "Patients", icon: HeartPulse, hospitalOnly: true },
  { to: "/provider/entities", label: "My Entities", icon: Building2, entitiesOnly: true },
  { to: "/provider/appointments", label: "Appointments", icon: CalendarDays, doctorOnly: true },
  { to: "/provider/activities", label: "My Activities", icon: Activity },
  { to: "/provider/earnings", label: "Earnings & Payouts", icon: Wallet },
  { to: "/provider/ledger", label: "Trata Patients & Billing", icon: Receipt },
  { to: "/abha", label: "ABHA (ABDM)", icon: Fingerprint },
  { to: "/provider/profile", label: "Profile", icon: IdCard },
  { to: "/provider/kyc", label: "KYC", icon: ShieldCheck },
  { to: "/tasks", label: "Tasks", icon: ListChecks },
];

export default function Layout({ children }) {
  const { user, logout, isProvider, isSalesRep, isAdmin } = useAuth();
  const isHospital = user?.provider_type === "hospital";
  const hasEntities = ["hospital", "pharmacy", "pathology", "pathologist", "path_lab", "diagnostic_centre", "ambulance"].includes(user?.provider_type) && !user?.parent_org_name;
  const NAV = (isProvider ? PROVIDER_NAV : isSalesRep ? SALES_NAV : ADMIN_NAV).filter(
    (n) => (!n.hospitalOnly || isHospital) && (!n.entitiesOnly || hasEntities) && (!n.pharmacyOnly || user?.provider_type === "pharmacy") && (!n.doctorOnly || user?.provider_type === "doctor") && (!n.masterOnly || user?.is_master_admin)
  );
  const navigate = useNavigate();
  const [query, setQuery] = React.useState("");
  const [results, setResults] = React.useState(null);
  const [open, setOpen] = React.useState(false);
  const [sync, setSync] = React.useState(null);
  const [syncing, setSyncing] = React.useState(false);
  const [navOpen, setNavOpen] = React.useState(false);
  const [mobileSearchOpen, setMobileSearchOpen] = React.useState(false);

  React.useEffect(() => { setNavOpen(false); }, [navigate]);

  const loadSync = React.useCallback(async () => {
    if (isProvider) return;
    try {
      const [up, db] = await Promise.all([
        api.get("/admin/sync/status").then((r) => r.data).catch(() => ({})),
        api.get("/supabase/status").then((r) => r.data).catch(() => ({ connected: false })),
      ]);
      setSync({ ...up, shared_db: db });
    } catch {}
  }, [isProvider]);

  React.useEffect(() => { loadSync(); }, [loadSync]);

  // Sidebar live badges (KYC admin queue, etc.) — admins only, poll every 30s
  const [navBadges, setNavBadges] = React.useState({ kyc_admin_queue: 0 });
  React.useEffect(() => {
    if (!isAdmin) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const { data } = await api.get("/admin/kyc-queue-count");
        if (!cancelled) setNavBadges((b) => ({ ...b, kyc_admin_queue: data.count || 0 }));
      } catch {}
    };
    tick();
    const t = setInterval(tick, 30000);
    return () => { cancelled = true; clearInterval(t); };
  }, [isAdmin]);

  const runSync = async () => {
    setSyncing(true);
    try {
      await api.post("/admin/sync/run");
      await loadSync();
    } catch (e) {
      alert(e?.response?.data?.detail || "Sync failed");
    }
    setSyncing(false);
  };

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
      {/* Sidebar — desktop fixed, mobile drawer */}
      {navOpen && (
        <button
          aria-label="Close menu"
          onClick={() => setNavOpen(false)}
          className="lg:hidden fixed inset-0 bg-black/40 z-40"
          data-testid="nav-overlay"
        />
      )}
      <aside
        className={`fixed lg:sticky lg:top-0 inset-y-0 left-0 z-50 w-64 lg:w-60 shrink-0 h-screen bg-[#F8F9FA] border-r border-[#DFE1E6] flex flex-col transform transition-transform lg:transform-none ${
          navOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        }`}
        data-testid="sidebar"
      >
        <div className="h-14 flex items-center gap-2 px-4 border-b border-[#DFE1E6] justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <img src="/brand/shield.png" alt="" className="h-9 w-9 object-contain shrink-0" />
            <div className="min-w-0">
              <div className="font-heading font-bold text-[#091E42] leading-none truncate">Trata Health</div>
              <div className="text-[10px] text-[#5E6C84] tracking-wider uppercase mt-0.5 truncate">Admin Console</div>
            </div>
          </div>
          <button
            className="lg:hidden p-1.5 text-[#5E6C84] hover:bg-white rounded"
            onClick={() => setNavOpen(false)}
            data-testid="nav-close-btn"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <nav className="flex-1 min-h-0 overflow-y-auto p-3 space-y-1">
          {NAV.map((n) => n.section ? (
            <div key={n.section} className="pt-4 pb-1 px-3 text-[10px] font-bold uppercase tracking-wider text-[#5E6C84]" data-testid={`nav-section-${n.section.toLowerCase().replace(/\s+/g, "-")}`}>{n.section}</div>
          ) : (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.exact}
              onClick={() => setNavOpen(false)}
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
              <span className="font-medium flex-1">{n.label}</span>
              {n.badgeKey === "kyc_admin_queue" && navBadges.kyc_admin_queue > 0 && (
                <span data-testid="kyc-queue-badge" className="inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 text-[10px] font-bold bg-[#FF5630] text-white rounded-full">
                  {navBadges.kyc_admin_queue}
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-[#DFE1E6] p-3 shrink-0 bg-[#F8F9FA]">
          <div className="flex items-center gap-3 mb-3">
            <div className="h-9 w-9 rounded-full bg-[#091E42] text-white flex items-center justify-center font-heading font-bold text-sm">
              {(user?.name || "MA").split(" ").map((p) => p[0]).slice(0, 2).join("")}
            </div>
            <div className="min-w-0">
              <div className="text-sm font-semibold text-[#091E42] truncate">{user?.name}</div>
              <div className="text-[11px] text-[#5E6C84] truncate">
                {user?.is_master_admin ? "Trata Health Admin"
                  : user?.role === "provider_owner"
                    ? `${(user?.provider_type || "").replace(/^\w/, c => c.toUpperCase())} Owner`
                    : user?.role}
              </div>
            </div>
          </div>
          <button
            data-testid="logout-btn"
            onClick={() => { logout(); navigate("/login"); }}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm text-[#42526E] hover:text-[#FF5630] hover:bg-white rounded-md transition-colors"
          >
            <LogOut className="h-4 w-4" /> Logout
          </button>
          <NavLink
            to="/settings"
            onClick={() => setNavOpen(false)}
            data-testid="nav-settings"
            className={({ isActive }) =>
              `mt-1 w-full flex items-center justify-center gap-2 px-3 py-2 text-xs rounded-md transition-colors ${
                isActive ? "bg-[#0052CC] text-white" : "text-[#5E6C84] hover:text-[#091E42] hover:bg-white"
              }`
            }
          >
            <SettingsIcon className="h-3.5 w-3.5" /> Account settings
          </NavLink>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 min-w-0 flex flex-col">
        <header className="h-14 flex items-center gap-2 lg:gap-4 px-3 lg:px-6 border-b border-[#DFE1E6] bg-white sticky top-0 z-30" data-testid="topbar">
          {/* Mobile menu trigger */}
          <button
            className="lg:hidden p-2 -ml-1 text-[#091E42] hover:bg-[#F1F2F4] rounded"
            onClick={() => setNavOpen(true)}
            aria-label="Open menu"
            data-testid="nav-open-btn"
          >
            <Menu className="h-5 w-5" />
          </button>
          {/* Mobile logo */}
          <div className="lg:hidden flex items-center gap-1.5 mr-auto">
            <img src="/brand/shield.png" alt="" className="h-7 w-7 object-contain" />
            <span className="font-heading font-bold text-sm text-[#091E42]">Trata Health</span>
          </div>
          {/* Search - desktop inline */}
          <div className="hidden md:block relative flex-1 max-w-xl">
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
          {/* Mobile search icon trigger */}
          <button
            className="md:hidden p-2 text-[#42526E] hover:bg-[#F1F2F4] rounded"
            onClick={() => setMobileSearchOpen((v) => !v)}
            aria-label="Search"
            data-testid="mobile-search-toggle"
          >
            <Search className="h-5 w-5" />
          </button>
          <LiveBell isMaster={!!user?.is_master_admin} />
          <DataSourceBadge sync={sync} syncing={syncing} onSync={runSync} hidden={isProvider} />
          <div className="hidden lg:flex items-center gap-2 px-3 py-1.5 bg-gradient-to-r from-[#0052CC] to-[#00B8D9] text-white rounded-md text-xs font-semibold">
            <Sparkles className="h-3.5 w-3.5" /> AI Insights Active
          </div>
        </header>
        {/* Mobile search overlay row */}
        {mobileSearchOpen && (
          <div className="md:hidden p-3 border-b border-[#DFE1E6] bg-white sticky top-14 z-20">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#5E6C84]" />
              <input
                autoFocus
                data-testid="mobile-search-input"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search contacts, activities, tasks…"
                className="w-full pl-9 pr-3 py-2 text-sm bg-[#F1F2F4] border border-transparent rounded-md focus:bg-white focus:border-[#4C9AFF] outline-none"
              />
              {results && (
                <div className="mt-2 bg-white border border-[#DFE1E6] rounded-md shadow max-h-80 overflow-auto">
                  <SearchSection title="Contacts" items={results.contacts} onClick={(i) => { navigate(`/contacts/${i.id}`); setMobileSearchOpen(false); }} />
                  <SearchSection title="Activities" items={results.activities} renderSub={(i) => `${i.category} · ${i.status}`} />
                  <SearchSection title="Tasks" items={results.tasks} renderSub={(i) => `${i.status} · ${i.priority}`} />
                </div>
              )}
            </div>
          </div>
        )}
        <div className="flex-1 min-w-0 overflow-x-hidden">{children}</div>
        {isProvider && user?.provider_type === "pharmacy" && <NewOrderAlerts />}
        {user?.is_master_admin && <AlertListener />}
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


function DataSourceBadge({ sync, syncing, onSync, hidden }) {
  if (hidden) return null;
  if (!sync) return null;
  const upstream = sync.enabled;
  const live = upstream || sync.shared_db?.connected;
  const last = sync.last?.last_synced_at;
  const tip = upstream
    ? `Live · ${sync.base_url}\nLast sync: ${last ? relativeTime(last) : "never"}`
    : live ? "Live · reading the shared Trata database directly (all 4 apps)" : "Shared Trata database unreachable — showing cached data";
  return (
    <div
      data-testid="data-source-badge"
      title={tip}
      className={`flex items-center gap-2 px-2.5 py-1 rounded-md text-[11px] font-semibold border ${
        live ? "border-[#36B37E]/30 bg-[#E3FCEF] text-[#006644]" : "border-[#FFC400]/40 bg-[#FFFAE6] text-[#974F0C]"
      }`}
    >
      <Database className="h-3 w-3" />
      {live ? (
        <>
          <span>LIVE</span>
          {upstream ? <>
          <span className="font-normal text-[#42526E] hidden md:inline">· {last ? relativeTime(last) : "syncing…"}</span>
          <button
            onClick={onSync}
            disabled={syncing}
            data-testid="sync-now-btn"
            className="ml-1 inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-white hover:bg-[#F4F5F7] border border-[#DFE1E6] text-[#42526E] disabled:opacity-50"
          >
            <RefreshCw className={`h-3 w-3 ${syncing ? "animate-spin" : ""}`} />
            {syncing ? "Syncing" : "Sync"}
          </button>
          </> : <span className="font-normal text-[#42526E] hidden md:inline">· shared DB</span>}
        </>
      ) : (
        <span>OFFLINE</span>
      )}
    </div>
  );
}
