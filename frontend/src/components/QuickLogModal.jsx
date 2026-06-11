import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { X, Loader2, Search, CalendarClock, Tag, MapPin, CheckCircle2 } from "lucide-react";
import { SALES_ACTIVITY_TYPES, SALES_OUTCOMES, PIPELINE_STAGES } from "../lib/constants";

export default function QuickLogModal({ initialLead = null, onClose, onSaved }) {
  const [lead, setLead] = useState(initialLead);
  const [search, setSearch] = useState("");
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [activityType, setActivityType] = useState("cold_call");
  const [outcome, setOutcome] = useState("");
  const [notes, setNotes] = useState("");
  const [nextDate, setNextDate] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [gps, setGps] = useState(null);
  const [gpsBusy, setGpsBusy] = useState(false);
  const [gpsErr, setGpsErr] = useState("");

  const captureGps = () => {
    setGpsErr("");
    if (!navigator.geolocation) {
      setGpsErr("Geolocation not supported on this device");
      return;
    }
    setGpsBusy(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setGps({ lat: +pos.coords.latitude.toFixed(6), lng: +pos.coords.longitude.toFixed(6), accuracy: Math.round(pos.coords.accuracy || 0) });
        setGpsBusy(false);
      },
      (e) => {
        setGpsErr(e?.message || "Could not fetch location. Please allow location access.");
        setGpsBusy(false);
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
    );
  };

  // Lead autocomplete
  useEffect(() => {
    if (lead) return;
    if (!search.trim()) { setResults([]); return; }
    const t = setTimeout(async () => {
      setSearching(true);
      try {
        const { data } = await api.get("/contacts", { params: { q: search, limit: 8 } });
        setResults(data.items);
      } finally { setSearching(false); }
    }, 250);
    return () => clearTimeout(t);
  }, [search, lead]);

  const submit = async () => {
    setErr("");
    if (!lead) return setErr("Pick a lead first.");
    setSaving(true);
    try {
      await api.post("/agent/quick-log", {
        contact_id: lead.id,
        activity_type: activityType,
        outcome: outcome || null,
        notes,
        next_action_at: nextDate ? new Date(nextDate).toISOString() : null,
        gps: gps ? { lat: gps.lat, lng: gps.lng } : null,
      });
      onSaved?.();
    } catch (e) {
      setErr(e?.response?.data?.detail || "Could not save");
    }
    setSaving(false);
  };

  const stageHint = SALES_OUTCOMES.find((o) => o.value === outcome)?.stage;
  const stageHintLabel = stageHint ? PIPELINE_STAGES.find((s) => s.value === stageHint)?.label : null;

  return (
    <div className="fixed inset-0 z-[100] flex items-end sm:items-center justify-center bg-black/50 p-0 sm:p-4" onClick={onClose} data-testid="quick-log-modal">
      <div className="bg-white w-full sm:max-w-lg rounded-t-2xl sm:rounded-lg shadow-2xl flex flex-col max-h-[92vh]" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b border-[#DFE1E6]">
          <div>
            <div className="overline">Quick Log</div>
            <div className="font-heading font-bold text-lg text-[#091E42]">Log Activity</div>
          </div>
          <button onClick={onClose} className="p-1.5 text-[#5E6C84] hover:bg-[#F1F2F4] rounded" data-testid="quick-log-close">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-4 overflow-y-auto flex-1 space-y-4">
          {/* Lead picker */}
          {lead ? (
            <div className="flex items-center justify-between bg-[#F8F9FA] border border-[#DFE1E6] rounded-md p-3" data-testid="ql-selected-lead">
              <div className="min-w-0">
                <div className="text-sm font-semibold text-[#091E42] truncate">{lead.name}</div>
                <div className="text-[11px] text-[#5E6C84] truncate">{lead.type} · {lead.city || "—"} · {lead.phone || ""}</div>
              </div>
              <button onClick={() => { setLead(null); setSearch(""); }} className="text-xs text-[#0052CC] font-semibold">Change</button>
            </div>
          ) : (
            <div>
              <div className="overline mb-2">1. Pick a lead</div>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#5E6C84]" />
                <input
                  autoFocus
                  data-testid="ql-lead-search"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search your leads…"
                  className="pl-9 w-full px-3 py-2.5 text-sm border border-[#DFE1E6] rounded-md focus:border-[#4C9AFF] outline-none"
                />
              </div>
              {searching && <div className="text-xs text-[#5E6C84] mt-1">Searching…</div>}
              {results.length > 0 && (
                <div className="mt-2 border border-[#DFE1E6] rounded-md max-h-48 overflow-y-auto">
                  {results.map((r) => (
                    <button
                      key={r.id}
                      onClick={() => { setLead(r); setResults([]); setSearch(""); }}
                      data-testid={`ql-pick-${r.id}`}
                      className="w-full text-left px-3 py-2 hover:bg-[#F8F9FA] flex items-center justify-between border-b border-[#F1F2F4] last:border-0">
                      <div className="min-w-0">
                        <div className="text-sm font-semibold text-[#091E42] truncate">{r.name}</div>
                        <div className="text-[11px] text-[#5E6C84]">{r.type} · {r.city}</div>
                      </div>
                      <span className="text-[10px] uppercase tracking-wider font-bold text-[#5E6C84]">{(r.pipeline_stage || "").replace(/_/g, " ")}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Activity type */}
          <div>
            <div className="overline mb-2 flex items-center gap-1.5"><Tag className="h-3 w-3" /> 2. Type</div>
            <div className="grid grid-cols-3 gap-2">
              {SALES_ACTIVITY_TYPES.map((t) => (
                <button
                  key={t.value}
                  onClick={() => setActivityType(t.value)}
                  data-testid={`ql-type-${t.value}`}
                  className={`px-2 py-2 text-xs font-semibold rounded border transition-colors ${
                    activityType === t.value
                      ? "text-white"
                      : "bg-white text-[#42526E] border-[#DFE1E6] hover:border-[#0052CC]"
                  }`}
                  style={activityType === t.value ? { background: t.color, borderColor: t.color } : {}}>
                  {t.label}
                </button>
              ))}
            </div>
          </div>

          {/* GPS Check-in (site visits only) */}
          {activityType === "site_visit" && (
            <div data-testid="ql-gps-block">
              <div className="overline mb-2 flex items-center gap-1.5"><MapPin className="h-3 w-3" /> GPS Check-in</div>
              {gps ? (
                <div className="flex items-center justify-between bg-[#E3FCEF] border border-[#36B37E]/30 rounded-md p-2.5">
                  <div className="flex items-center gap-2 min-w-0">
                    <CheckCircle2 className="h-4 w-4 text-[#36B37E] shrink-0" />
                    <div className="text-xs">
                      <div className="font-semibold text-[#006644]">Checked in at site</div>
                      <div className="font-mono text-[10px] text-[#42526E]">{gps.lat}, {gps.lng} · ±{gps.accuracy}m</div>
                    </div>
                  </div>
                  <button onClick={() => { setGps(null); setGpsErr(""); }} className="text-xs text-[#0052CC] font-semibold" data-testid="ql-gps-clear">Clear</button>
                </div>
              ) : (
                <button
                  onClick={captureGps}
                  disabled={gpsBusy}
                  data-testid="ql-gps-capture"
                  className="w-full flex items-center justify-center gap-2 px-3 py-2.5 text-sm font-semibold border border-dashed border-[#0052CC]/40 text-[#0052CC] hover:bg-[#DEEBFF] rounded-md disabled:opacity-60"
                >
                  {gpsBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <MapPin className="h-4 w-4" />}
                  {gpsBusy ? "Getting your location…" : "Check in with GPS"}
                </button>
              )}
              {gpsErr && <div className="text-[11px] text-[#FF5630] mt-1" data-testid="ql-gps-error">{gpsErr}</div>}
              <div className="text-[11px] text-[#5E6C84] mt-1">Captures your live coordinates as proof of site visit.</div>
            </div>
          )}

          {/* Outcome */}
          <div>
            <div className="overline mb-2">3. Outcome</div>
            <div className="flex flex-wrap gap-1.5">
              {SALES_OUTCOMES.map((o) => (
                <button
                  key={o.value}
                  onClick={() => setOutcome(o.value === outcome ? "" : o.value)}
                  data-testid={`ql-outcome-${o.value}`}
                  className={`px-2.5 py-1 text-xs font-semibold rounded transition-colors ${
                    outcome === o.value
                      ? "bg-[#091E42] text-white"
                      : "bg-[#F1F2F4] text-[#42526E] hover:bg-[#DFE1E6]"
                  }`}>
                  {o.label}
                </button>
              ))}
            </div>
            {stageHintLabel && (
              <div className="mt-2 text-[11px] text-[#974F0C] bg-[#FFFAE6] border border-[#FFC400]/40 rounded px-2 py-1">
                This will move the lead to <b>{stageHintLabel}</b>.
              </div>
            )}
          </div>

          {/* Notes */}
          <div>
            <div className="overline mb-2">Notes (optional)</div>
            <textarea
              data-testid="ql-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              placeholder="What happened? What did they say?"
              className="w-full px-3 py-2 text-sm border border-[#DFE1E6] rounded-md focus:border-[#4C9AFF] outline-none resize-none"
            />
          </div>

          {/* Next action date */}
          <div>
            <div className="overline mb-2 flex items-center gap-1.5"><CalendarClock className="h-3 w-3" /> Next follow-up (optional)</div>
            <input
              type="date"
              data-testid="ql-next-date"
              value={nextDate}
              onChange={(e) => setNextDate(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-[#DFE1E6] rounded-md focus:border-[#4C9AFF] outline-none"
            />
            <div className="text-[11px] text-[#5E6C84] mt-1">Auto-creates a follow-up task for you on this date.</div>
          </div>

          {err && <div className="text-sm text-[#FF5630]" data-testid="ql-error">{err}</div>}
        </div>

        <div className="p-4 border-t border-[#DFE1E6] flex gap-2">
          <button onClick={onClose} className="flex-1 px-4 py-2.5 text-sm font-semibold border border-[#DFE1E6] rounded-md hover:bg-[#F8F9FA]" data-testid="ql-cancel">
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={saving || !lead}
            data-testid="ql-save"
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-semibold bg-[#0052CC] hover:bg-[#0747A6] text-white rounded-md disabled:opacity-60">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save Log"}
          </button>
        </div>
      </div>
    </div>
  );
}
