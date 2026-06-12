import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { CONTACT_TYPES, PIPELINE_STAGES, typeLabel, fmtCurrency, relativeTime } from "../lib/constants";
import { Filter, Download, CheckCircle2, XCircle, Search, UserPlus } from "lucide-react";
import OnboardProviderModal from "../components/OnboardProviderModal";

export default function Contacts() {
  const [params, setParams] = useSearchParams();
  const [list, setList] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [onboardOpen, setOnboardOpen] = useState(false);
  const type = params.get("type") || "";
  const stage = params.get("stage") || "";
  const verified = params.get("verified") || "";
  const q = params.get("q") || "";
  const navigate = useNavigate();
  const { user } = useAuth();
  const canOnboard = !!(user?.is_master_admin || ["admin", "manager", "national_manager", "regional_manager", "zonal_manager", "area_manager"].includes(user?.role));

  const fetch = async () => {
    setLoading(true);
    const { data } = await api.get("/contacts", {
      params: {
        type: type || undefined,
        pipeline_stage: stage || undefined,
        is_verified: verified === "" ? undefined : verified === "true",
        q: q || undefined,
        limit: 100,
      },
    });
    setList(data.items); setTotal(data.total); setLoading(false);
  };

  useEffect(() => { fetch(); /* eslint-disable-next-line */ }, [type, stage, verified, q]);

  const setParam = (k, v) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v); else p.delete(k);
    setParams(p);
  };

  const exportCsv = async () => {
    const token = localStorage.getItem("trata_token");
    const url = `${api.defaults.baseURL}/export/contacts.csv${type ? `?type=${type}` : ""}`;
    const r = await fetch_with_token(url, token);
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `contacts${type ? "-" + type : ""}.csv`;
    a.click();
  };

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-5 lg:space-y-6" data-testid="contacts-page">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="overline">User Directory</div>
          <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">
            Trata Users <span className="text-[#5E6C84] font-medium">/ {total.toLocaleString()}</span>
          </h1>
          <p className="text-sm text-[#5E6C84] mt-1">All users on the Trata network — providers, prospects, and partners.</p>
        </div>
        <div className="flex items-center gap-2">
          {canOnboard && (
            <button
              data-testid="contacts-onboard-btn"
              onClick={() => setOnboardOpen(true)}
              className="flex items-center gap-2 px-3.5 py-2 text-sm font-semibold rounded-md text-white bg-[#0052CC] hover:bg-[#0747A6] shadow-sm"
            >
              <UserPlus className="h-4 w-4" /> Onboard provider
            </button>
          )}
          <button
            data-testid="contacts-export-btn"
            onClick={exportCsv}
            className="flex items-center gap-2 px-3 py-2 text-sm border border-[#DFE1E6] rounded-md hover:bg-[#F8F9FA]"
          >
            <Download className="h-4 w-4" /> Export CSV
          </button>
        </div>
      </div>

      {onboardOpen && (
        <OnboardProviderModal
          onClose={() => setOnboardOpen(false)}
          onCreated={(created) => {
            setOnboardOpen(false);
            fetch();
            if (created?.contact?.id) navigate(`/contacts/${created.contact.id}`);
          }}
        />
      )}

      {/* Type tabs */}
      <div className="flex flex-nowrap overflow-x-auto scrollbar-thin gap-1.5 border-b border-[#DFE1E6] pb-3 -mx-4 px-4 sm:mx-0 sm:px-0" data-testid="contacts-type-tabs">
        <TypeTab label="All" value="" active={!type} onClick={() => setParam("type", "")} />
        {CONTACT_TYPES.map((c) => (
          <TypeTab key={c.value} label={c.label} value={c.value} active={type === c.value} onClick={() => setParam("type", c.value)} />
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3" data-testid="contacts-filters">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#5E6C84]" />
          <input
            placeholder="Search name, phone, email…"
            defaultValue={q}
            onChange={(e) => setParam("q", e.target.value)}
            data-testid="contacts-search-input"
            className="pl-9 pr-3 py-2 text-sm bg-white border border-[#DFE1E6] rounded-md min-w-[260px] focus:border-[#4C9AFF] focus:ring-2 focus:ring-[#4C9AFF]/30 outline-none"
          />
        </div>
        <FilterSelect
          label="Stage"
          value={stage}
          onChange={(v) => setParam("stage", v)}
          options={[{ value: "", label: "All stages" }, ...PIPELINE_STAGES.map((s) => ({ value: s.value, label: s.label }))]}
          testid="contacts-stage-filter"
        />
        <FilterSelect
          label="Status"
          value={verified}
          onChange={(v) => setParam("verified", v)}
          options={[{ value: "", label: "Any" }, { value: "true", label: "Verified" }, { value: "false", label: "Pending" }]}
          testid="contacts-status-filter"
        />
      </div>

      {/* Table */}
      <div className="bg-white border border-[#DFE1E6] rounded-md overflow-hidden">
        <div className="overflow-x-auto scrollbar-thin">
          <table className="w-full text-sm" data-testid="contacts-table">
            <thead className="bg-[#F8F9FA] border-b border-[#DFE1E6]">
              <tr className="text-left">
                <Th>Name</Th><Th>Type</Th><Th>Phone</Th><Th>City</Th>
                <Th>Stage</Th><Th>Status</Th><Th align="right">Deal Value</Th>
                <Th>Joined</Th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={8} className="py-10 text-center text-sm text-[#5E6C84]">Loading…</td></tr>
              )}
              {!loading && list.length === 0 && (
                <tr><td colSpan={8} className="py-10 text-center text-sm text-[#5E6C84]">No contacts match these filters.</td></tr>
              )}
              {list.map((c) => (
                <tr
                  key={c.id}
                  onClick={() => navigate(`/contacts/${c.id}`)}
                  className="border-b border-[#F1F2F4] last:border-0 hover:bg-[#F8F9FA] cursor-pointer"
                  data-testid={`contact-row-${c.id}`}
                >
                  <Td>
                    <div className="flex items-center gap-3 min-w-0">
                      <Avatar name={c.name} src={c.avatar} />
                      <div className="min-w-0">
                        <div className="font-semibold text-[#091E42] truncate">{c.name}</div>
                        <div className="text-xs text-[#5E6C84] truncate">{c.specialization || c.email || "—"}</div>
                      </div>
                    </div>
                  </Td>
                  <Td><Pill>{typeLabel(c.type)}</Pill></Td>
                  <Td className="font-mono text-xs">{c.phone}</Td>
                  <Td>{c.city || "—"}</Td>
                  <Td><StagePill stage={c.pipeline_stage} /></Td>
                  <Td>
                    {c.is_verified ? (
                      <span className="inline-flex items-center gap-1 text-[#36B37E] text-xs font-semibold"><CheckCircle2 className="h-3.5 w-3.5" /> Verified</span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[#FFAB00] text-xs font-semibold"><XCircle className="h-3.5 w-3.5" /> Pending</span>
                    )}
                  </Td>
                  <Td align="right" className="font-mono">{c.deal_value ? fmtCurrency(c.deal_value) : "—"}</Td>
                  <Td className="text-xs text-[#5E6C84]">{relativeTime(c.created_at)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

async function fetch_with_token(url, token) {
  return await window.fetch(url, { headers: { Authorization: `Bearer ${token}` } });
}

function Th({ children, align = "left" }) {
  return <th className={`px-3 py-2.5 text-[11px] uppercase tracking-wider font-semibold text-[#5E6C84] text-${align}`}>{children}</th>;
}
function Td({ children, align = "left", className = "" }) {
  return <td className={`px-3 py-2.5 text-${align} ${className}`}>{children}</td>;
}

function TypeTab({ label, value, active, onClick }) {
  return (
    <button
      onClick={onClick}
      data-testid={`typetab-${value || "all"}`}
      className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors whitespace-nowrap shrink-0 ${
        active ? "bg-[#091E42] text-white" : "text-[#42526E] hover:bg-[#F1F2F4]"
      }`}
    >
      {label}
    </button>
  );
}

function FilterSelect({ label, value, onChange, options, testid }) {
  return (
    <div className="flex items-center gap-2">
      <span className="overline">{label}</span>
      <select
        data-testid={testid}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="px-2 py-1.5 text-sm bg-white border border-[#DFE1E6] rounded-md focus:border-[#4C9AFF] outline-none"
      >
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}

function Pill({ children }) {
  return <span className="inline-flex px-2 py-0.5 text-[11px] uppercase tracking-wider font-semibold bg-[#F1F2F4] text-[#42526E] rounded">{children}</span>;
}

function StagePill({ stage }) {
  const s = PIPELINE_STAGES.find((p) => p.value === stage);
  if (!s) return "—";
  return (
    <span
      className="inline-flex px-2 py-0.5 text-[11px] uppercase tracking-wider font-semibold rounded"
      style={{ background: `${s.color}15`, color: s.color }}
    >
      {s.label}
    </span>
  );
}

export function Avatar({ name, src, size = 36 }) {
  const initials = (name || "").split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase();
  if (src) {
    return <img src={src} alt={name} className="rounded-full object-cover border border-[#DFE1E6]" style={{ width: size, height: size }} />;
  }
  const colors = ["#0052CC", "#36B37E", "#FF5630", "#FFAB00", "#6554C0", "#00B8D9"];
  const hash = (name || "").split("").reduce((a, c) => a + c.charCodeAt(0), 0);
  const bg = colors[hash % colors.length];
  return (
    <div
      className="rounded-full flex items-center justify-center text-white font-heading font-bold text-xs shrink-0"
      style={{ width: size, height: size, background: bg }}
    >
      {initials || "?"}
    </div>
  );
}
