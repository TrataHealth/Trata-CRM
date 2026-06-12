export const CONTACT_TYPES = [
  { value: "patient", label: "Patients", icon: "User" },
  { value: "doctor", label: "Doctors", icon: "Stethoscope" },
  { value: "hospital", label: "Hospitals", icon: "Building2" },
  { value: "paramedic", label: "Paramedics", icon: "Cross" },
  { value: "ambulance_provider", label: "Ambulance", icon: "Ambulance" },
  { value: "pathologist", label: "Pathology Labs", icon: "FlaskConical" },
];

export const TEAM_ROLES = [
  { value: "admin",            label: "Admin",            tier: 0, color: "#0747A6", short: "ADM" },
  { value: "national_manager", label: "National Manager", tier: 1, color: "#6554C0", short: "NM"  },
  { value: "regional_manager", label: "Regional Manager", tier: 2, color: "#0052CC", short: "RM"  },
  { value: "zonal_manager",    label: "Zonal Manager",    tier: 3, color: "#00875A", short: "ZM"  },
  { value: "area_manager",     label: "Area Manager",     tier: 4, color: "#36B37E", short: "AM"  },
  { value: "sales_rep",        label: "Sales Rep",        tier: 5, color: "#FFAB00", short: "SR"  },
  { value: "ops_rep",          label: "Ops Rep",          tier: 5, color: "#FF8B00", short: "OPS" },
];

export const ROLE_META = Object.fromEntries(TEAM_ROLES.map((r) => [r.value, r]));
export const roleLabel = (r) => ROLE_META[r]?.label || (r || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
export const roleColor = (r) => ROLE_META[r]?.color || "#42526E";

/** SLA helper — returns {label, color, urgency:'fresh'|'warn'|'overdue', hours, days}.
 * Used to render "Pending 14h" / "OVERDUE 2d 6h" chips with red urgency past 24h.
 * @param {string} since ISO datetime
 * @param {number} thresholdHours hours after which it's flagged "overdue" (default 24)
 */
export function slaInfo(since, thresholdHours = 24) {
  if (!since) return { label: "—", color: "#5E6C84", urgency: "fresh", hours: 0, days: 0 };
  const ms = Date.now() - new Date(since).getTime();
  const totalMins = Math.max(0, Math.floor(ms / 60000));
  const days = Math.floor(totalMins / 1440);
  const hours = Math.floor((totalMins % 1440) / 60);
  const mins  = totalMins % 60;
  let label;
  if (days >= 1) label = `${days}d ${hours}h`;
  else if (hours >= 1) label = `${hours}h ${mins}m`;
  else label = `${mins}m`;
  const totalHours = totalMins / 60;
  let urgency, color;
  if (totalHours >= thresholdHours) { urgency = "overdue"; color = "#FF5630"; }
  else if (totalHours >= thresholdHours * 0.5) { urgency = "warn"; color = "#FFAB00"; }
  else { urgency = "fresh"; color = "#36B37E"; }
  return { label, color, urgency, hours: totalHours, days };
}


export const PIPELINE_STAGES = [
  { value: "lead", label: "Lead", color: "#5E6C84" },
  { value: "contacted", label: "Contacted", color: "#00B8D9" },
  { value: "kyc_submitted", label: "KYC Collected", color: "#FFC400" },
  { value: "verified", label: "App Onboarded", color: "#36B37E" },
  { value: "active", label: "Live on App", color: "#0052CC" },
  { value: "churned", label: "Dropped", color: "#FF5630" },
];

export const SALES_ACTIVITY_TYPES = [
  { value: "cold_call",       label: "Cold Call",        color: "#0052CC", icon: "Phone" },
  { value: "follow_up",       label: "Follow-up",        color: "#00B8D9", icon: "PhoneCall" },
  { value: "pitch_meeting",   label: "Pitch Meeting",    color: "#6554C0", icon: "Presentation" },
  { value: "site_visit",      label: "Site Visit",       color: "#FFAB00", icon: "MapPin" },
  { value: "demo",            label: "App Demo",         color: "#FF8B00", icon: "MonitorPlay" },
  { value: "kyc_collection",  label: "KYC Collection",   color: "#FFC400", icon: "FileText" },
  { value: "app_training",    label: "App Training",     color: "#36B37E", icon: "GraduationCap" },
  { value: "whatsapp",        label: "WhatsApp",         color: "#25D366", icon: "MessageCircle" },
  { value: "email",           label: "Email",            color: "#5E6C84", icon: "Mail" },
  { value: "note",            label: "Note",             color: "#42526E", icon: "StickyNote" },
];

export const SALES_OUTCOMES = [
  { value: "connected",          label: "Connected",            stage: null },
  { value: "no_answer",          label: "No answer",            stage: null },
  { value: "not_interested",     label: "Not interested",       stage: "churned" },
  { value: "interested",         label: "Interested",           stage: "contacted" },
  { value: "meeting_scheduled",  label: "Meeting scheduled",    stage: "contacted" },
  { value: "pitched",            label: "Pitched",              stage: "contacted" },
  { value: "kyc_pending",        label: "KYC pending",          stage: "contacted" },
  { value: "kyc_collected",      label: "KYC collected",        stage: "kyc_submitted" },
  { value: "signed_on_app",      label: "Signed on app",        stage: "verified" },
  { value: "first_use",          label: "Live on app",          stage: "active" },
];

export const ACTIVITY_CATEGORIES = [
  { value: "emergency_case", label: "Emergency Cases", color: "#FF5630" },
  { value: "appointment", label: "Appointments", color: "#0052CC" },
  { value: "ambulance_booking", label: "Ambulance Bookings", color: "#FFC400" },
  { value: "lab_booking", label: "Lab Bookings", color: "#00B8D9" },
  { value: "pathology_booking", label: "Pathology Bookings", color: "#6554C0" },
  { value: "kyc", label: "KYC", color: "#36B37E" },
];

export const STATUS_COLORS = {
  // emergency
  CREATED: "#FFC400",
  PARAMEDIC_ASSIGNED: "#00B8D9",
  AMBULANCE_DISPATCHED: "#0052CC",
  ON_THE_WAY: "#0052CC",
  REACHED: "#36B37E",
  COMPLETED: "#36B37E",
  CANCELLED: "#5E6C84",
  CLOSED: "#5E6C84",
  // appt
  scheduled: "#0052CC",
  completed: "#36B37E",
  cancelled: "#FF5630",
  no_show: "#FFC400",
  // ambulance
  pending: "#FFC400",
  accepted: "#00B8D9",
  in_progress: "#0052CC",
  // labs
  booked: "#FFC400",
  sample_collected: "#0052CC",
  report_ready: "#36B37E",
  // kyc
  approved: "#36B37E",
  submitted: "#00B8D9",
  rejected: "#FF5630",
  // tasks
  open: "#FFC400",
  done: "#36B37E",
};

export function statusColor(s) {
  return STATUS_COLORS[s] || "#5E6C84";
}

export function typeLabel(t) {
  return (CONTACT_TYPES.find((x) => x.value === t)?.label || t).replace(/s$/, "");
}

export function stageLabel(s) {
  return PIPELINE_STAGES.find((x) => x.value === s)?.label || s;
}

export function fmtCurrency(n) {
  return "₹" + (n || 0).toLocaleString("en-IN");
}

export function relativeTime(iso) {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  const diff = Date.now() - t;
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(iso).toLocaleDateString();
}
