export const CONTACT_TYPES = [
  { value: "patient", label: "Patients", icon: "User" },
  { value: "doctor", label: "Doctors", icon: "Stethoscope" },
  { value: "hospital", label: "Hospitals", icon: "Building2" },
  { value: "paramedic", label: "Paramedics", icon: "Cross" },
  { value: "ambulance_provider", label: "Ambulance", icon: "Ambulance" },
  { value: "pathologist", label: "Pathology Labs", icon: "FlaskConical" },
];

export const PIPELINE_STAGES = [
  { value: "lead", label: "Lead", color: "#5E6C84" },
  { value: "contacted", label: "Contacted", color: "#00B8D9" },
  { value: "kyc_submitted", label: "KYC Submitted", color: "#FFC400" },
  { value: "verified", label: "Verified", color: "#36B37E" },
  { value: "active", label: "Active", color: "#0052CC" },
  { value: "churned", label: "Churned", color: "#FF5630" },
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
