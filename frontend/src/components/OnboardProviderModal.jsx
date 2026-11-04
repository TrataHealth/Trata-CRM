import React, { useState } from "react";
import api from "../lib/api";
import { X, Loader2, UserPlus, CheckCircle2, AlertCircle, ExternalLink } from "lucide-react";

// Role options shown in the dropdown — mirrors Trata Admin App's onboarding taxonomy.
const ROLE_OPTIONS = [
  { value: "ambulance_provider", label: "Ambulance provider", icon: "🚑" },
  { value: "hospital",           label: "Hospital",           icon: "🏥" },
  { value: "doctor",             label: "Doctor (clinic)",    icon: "🩺" },
  { value: "paramedic",          label: "Paramedic",          icon: "➕" },
  { value: "path_lab",           label: "Path lab",           icon: "🧪" },
  { value: "pharmacy",           label: "Pharmacy",           icon: "💊" },
  { value: "diagnostic_centre",  label: "Diagnostic centre",  icon: "🔬" },
  { value: "nurse",              label: "Nurse",              icon: "🩹" },
];

// Per-role extra fields. Keys must match the backend onboard-provider whitelist.
const ROLE_EXTRA_FIELDS = {
  ambulance_provider: [
    { key: "ambulance_count", label: "Number of ambulances", type: "number", placeholder: "e.g. 4" },
    { key: "vehicle_reg",     label: "Lead vehicle reg.",    type: "text",   placeholder: "e.g. MH12 AB 1234" },
    { key: "license_number",  label: "Operator licence #",   type: "text",   placeholder: "Optional" },
  ],
  hospital: [
    { key: "hospital_name",   label: "Hospital legal name",  type: "text",   placeholder: "If different from above" },
    { key: "specialization",  label: "Specialities",         type: "text",   placeholder: "e.g. Emergency, Ortho, Gynec" },
    { key: "license_number",  label: "Hospital licence #",   type: "text",   placeholder: "Optional" },
  ],
  doctor: [
    { key: "specialization",  label: "Specialisation",       type: "text",   placeholder: "e.g. Cardiologist" },
    { key: "license_number",  label: "MCI registration #",   type: "text",   placeholder: "Optional" },
  ],
  paramedic: [
    { key: "specialization",  label: "Skill area",           type: "text",   placeholder: "e.g. ALS / BLS" },
    { key: "license_number",  label: "Certification #",      type: "text",   placeholder: "Optional" },
  ],
  path_lab: [
    { key: "lab_specialty",   label: "Lab specialty",        type: "text",   placeholder: "e.g. Pathology, Radiology" },
    { key: "license_number",  label: "Lab licence #",        type: "text",   placeholder: "Optional" },
  ],
  diagnostic_centre: [
    { key: "lab_specialty",   label: "Tests offered",        type: "text",   placeholder: "e.g. Imaging, Pathology" },
    { key: "license_number",  label: "Centre licence #",     type: "text",   placeholder: "Optional" },
  ],
  nurse: [
    { key: "specialization",  label: "Nursing area",         type: "text",   placeholder: "e.g. ICU, Home care" },
    { key: "license_number",  label: "Nursing council reg. #", type: "text", placeholder: "Optional" },
  ],
  pharmacy: [
    { key: "pharmacy_type",   label: "Pharmacy type",        type: "text",   placeholder: "e.g. Retail / 24×7" },
    { key: "license_number",  label: "Drug licence #",       type: "text",   placeholder: "Optional" },
  ],
};

const initial = (role = "") => ({
  role,
  name: "",
  phone: "",
  email: "",
  city: "",
  state: "",
  address: "",
  pan_number: "",
  gst_number: "",
});

export default function OnboardProviderModal({ onClose, onCreated }) {
  const [form, setForm] = useState(initial());
  const [extras, setExtras] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(null);

  const set = (k, v) => setForm((s) => ({ ...s, [k]: v }));
  const setExtra = (k, v) => setExtras((s) => ({ ...s, [k]: v }));

  const submit = async () => {
    setError("");
    if (!form.role) return setError("Pick a role");
    if (!form.name.trim()) return setError("Provider name is required");
    const phone = (form.phone || "").replace(/[^\d]/g, "").slice(-10);
    if (phone.length !== 10) return setError("Phone must be a 10-digit Indian mobile number");
    setSubmitting(true);
    try {
      const payload = {
        ...form,
        phone,
        ...Object.fromEntries(Object.entries(extras).filter(([_, v]) => v !== "" && v !== null && v !== undefined)),
      };
      const { data } = await api.post("/admin/onboard-provider", payload);
      setSuccess(data);
    } catch (e) {
      setError(e?.response?.data?.detail || "Could not onboard provider");
    }
    setSubmitting(false);
  };

  const extraFields = form.role ? (ROLE_EXTRA_FIELDS[form.role] || []) : [];

  return (
    <div className="fixed inset-0 z-50 bg-[#091E42]/40 backdrop-blur-sm flex items-center justify-center p-4" data-testid="onboard-modal" onClick={onClose}>
      <div className="bg-white border border-[#DFE1E6] rounded-md w-full max-w-2xl max-h-[90vh] overflow-y-auto shadow-2xl" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="px-5 py-4 border-b border-[#DFE1E6] flex items-center justify-between sticky top-0 bg-white z-10">
          <div className="flex items-center gap-2 font-heading text-base font-bold text-[#091E42]">
            <UserPlus className="h-4 w-4 text-[#0052CC]" /> Onboard new provider
          </div>
          <button onClick={onClose} className="text-[#5E6C84] hover:text-[#091E42]" data-testid="onboard-close-btn" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Success state */}
        {success ? (
          <div className="p-5 space-y-3" data-testid="onboard-success">
            <div className="flex items-start gap-3 p-3 rounded-md bg-[#E3FCEF] border border-[#36B37E]/40">
              <CheckCircle2 className="h-5 w-5 text-[#006644] mt-0.5 shrink-0" />
              <div>
                <div className="font-heading font-bold text-[#006644]">{success.contact.name} added to CRM</div>
                <div className="text-xs text-[#42526E] mt-1">
                  Assigned to <b>{success.contact.assigned_agent_name || "no agent (no territory match)"}</b> · pipeline: <b>contacted</b> · KYC: <b>pending</b>
                </div>
              </div>
            </div>
            <div className="text-xs text-[#42526E] bg-[#F4F5F7] border border-[#DFE1E6] rounded-md p-3 space-y-2" data-testid="onboard-sync-status">
              <div className="font-semibold text-[#091E42]">Sync status</div>
              <div className="flex items-start gap-2">
                <CheckCircle2 className="h-3.5 w-3.5 text-[#36B37E] mt-0.5 shrink-0" />
                <span>Added to TrataHealth CRM (this app)</span>
              </div>
              <div className="flex items-start gap-2">
                <CheckCircle2 className="h-3.5 w-3.5 text-[#36B37E] mt-0.5 shrink-0" />
                <span>Outbound <code className="font-mono text-[10px]">crm.lead.created</code> event delivered to the Trata Admin App webhook (HTTP 200).</span>
              </div>
              <div className="flex items-start gap-2">
                <AlertCircle className="h-3.5 w-3.5 text-[#FFAB00] mt-0.5 shrink-0" />
                <span>The Trata Admin App currently <i>logs</i> incoming lead events but does not auto-create users from them. Once the Admin App's webhook handler is upgraded to create user records on <code className="font-mono text-[10px]">lead.created</code>, this provider will be able to OTP-login to the Provider App with phone <b>{success.contact.phone}</b> (dev OTP: 123456).</span>
              </div>
            </div>
            <div className="flex gap-2 pt-2">
              <button onClick={() => onCreated?.(success)} className="flex-1 px-3 py-2 text-sm font-semibold rounded-md text-white bg-[#0052CC] hover:bg-[#0747A6]" data-testid="onboard-open-contact-btn">
                Open contact <ExternalLink className="inline h-3 w-3 ml-0.5" />
              </button>
              <button onClick={() => { setSuccess(null); setForm(initial()); setExtras({}); }} className="px-3 py-2 text-sm border border-[#DFE1E6] rounded-md hover:bg-[#F8F9FA]" data-testid="onboard-add-another-btn">
                Add another
              </button>
            </div>
          </div>
        ) : (
          <div className="p-5 space-y-4">
            {/* Role selector */}
            <Field label="Provider role" required>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2" data-testid="onboard-role-grid">
                {ROLE_OPTIONS.map((r) => (
                  <button
                    key={r.value}
                    type="button"
                    onClick={() => set("role", r.value)}
                    data-testid={`onboard-role-${r.value}`}
                    className={`text-left px-3 py-2 border rounded-md text-xs font-semibold transition ${form.role === r.value ? "border-[#0052CC] bg-[#DEEBFF] text-[#0747A6]" : "border-[#DFE1E6] text-[#42526E] hover:border-[#42526E]"}`}
                  >
                    <span className="mr-1">{r.icon}</span> {r.label}
                  </button>
                ))}
              </div>
            </Field>

            {/* Common fields */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Field label="Provider name" required>
                <input value={form.name} onChange={(e) => set("name", e.target.value)} className={inputCls} placeholder="Display name" data-testid="onboard-name" autoFocus />
              </Field>
              <Field label="Mobile (10-digit)" required>
                <input value={form.phone} onChange={(e) => set("phone", e.target.value)} className={inputCls} placeholder="9XXXXXXXXX" maxLength={10} inputMode="numeric" data-testid="onboard-phone" />
              </Field>
              <Field label="Email">
                <input value={form.email} onChange={(e) => set("email", e.target.value)} className={inputCls} placeholder="optional" type="email" data-testid="onboard-email" />
              </Field>
              <Field label="City">
                <input value={form.city} onChange={(e) => set("city", e.target.value)} className={inputCls} placeholder="e.g. Delhi" data-testid="onboard-city" />
              </Field>
              <Field label="State">
                <input value={form.state} onChange={(e) => set("state", e.target.value)} className={inputCls} placeholder="e.g. Maharashtra" data-testid="onboard-state" />
              </Field>
              <Field label="Address">
                <input value={form.address} onChange={(e) => set("address", e.target.value)} className={inputCls} placeholder="Optional" data-testid="onboard-address" />
              </Field>
              <Field label="PAN number">
                <input value={form.pan_number} onChange={(e) => set("pan_number", e.target.value.toUpperCase())} className={inputCls} placeholder="Optional · ABCDE1234F" maxLength={10} data-testid="onboard-pan" />
              </Field>
              <Field label="GST number">
                <input value={form.gst_number} onChange={(e) => set("gst_number", e.target.value.toUpperCase())} className={inputCls} placeholder="Optional" data-testid="onboard-gst" />
              </Field>
            </div>

            {/* Per-role extras */}
            {extraFields.length > 0 && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2 border-t border-[#DFE1E6]">
                {extraFields.map((f) => (
                  <Field key={f.key} label={f.label}>
                    <input
                      type={f.type}
                      value={extras[f.key] || ""}
                      onChange={(e) => setExtra(f.key, e.target.value)}
                      className={inputCls}
                      placeholder={f.placeholder}
                      data-testid={`onboard-extra-${f.key}`}
                    />
                  </Field>
                ))}
              </div>
            )}

            {error && (
              <div className="flex items-start gap-2 p-2.5 text-xs rounded-md bg-[#FFEBE6] text-[#BF2600] border border-[#FF5630]/30" data-testid="onboard-error">
                <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" /><span>{error}</span>
              </div>
            )}

            {/* Footer */}
            <div className="flex items-center justify-end gap-2 pt-3 border-t border-[#DFE1E6]">
              <button onClick={onClose} className="px-3 py-2 text-sm border border-[#DFE1E6] rounded-md hover:bg-[#F8F9FA]" data-testid="onboard-cancel-btn">
                Cancel
              </button>
              <button
                onClick={submit}
                disabled={submitting}
                data-testid="onboard-submit-btn"
                className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-semibold rounded-md text-white bg-[#0052CC] hover:bg-[#0747A6] disabled:opacity-60"
              >
                {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
                {submitting ? "Onboarding…" : "Onboard provider"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const inputCls =
  "w-full px-3 py-2 text-sm border border-[#DFE1E6] rounded-md text-[#091E42] placeholder:text-[#A5ADBA] focus:outline-none focus:ring-2 focus:ring-[#4C9AFF] focus:border-[#0052CC]";

function Field({ label, required, children }) {
  return (
    <label className="block">
      <span className="text-[11px] uppercase tracking-wider text-[#5E6C84] font-semibold flex items-center gap-1">
        {label}{required && <span className="text-[#FF5630]">*</span>}
      </span>
      <div className="mt-1">{children}</div>
    </label>
  );
}
