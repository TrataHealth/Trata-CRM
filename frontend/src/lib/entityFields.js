// Mirrors ALLOWED_CHILDREN in the Provider app (backend/routes/organisations.py).
export const KIND_LABEL = { hospital: "Hospital", hospital_branch: "Hospital branch", pharmacy: "Pharmacy", path_lab: "Path lab",
  diagnostic_centre: "Diagnostic centre", poly_clinic: "Poly clinic", health_centre: "Health centre", ambulance: "Ambulance unit" };
export const ALLOWED = { hospital: Object.keys(KIND_LABEL), pharmacy: ["pharmacy"], path_lab: ["path_lab", "diagnostic_centre"],
  diagnostic_centre: ["path_lab", "diagnostic_centre"], ambulance: ["ambulance"] };
// [key, label, required, wide]
export const FIELDS = [["name", "Entity name", true, true], ["contact_person", "Admin / owner name", true], ["dedicated_phone", "Dedicated login phone", true],
  ["email", "Email"], ["address", "Address", true, true], ["city", "City", true], ["state", "State"], ["pincode", "Pincode"],
  ["license_number", "Licence number"], ["gst_number", "GST number"]];
export const COLUMNS = ["entity_kind", ...FIELDS.map(([k]) => k), "dispatch_radius_km"];

const ALIAS = { type: "entity_kind", entity_type: "entity_kind", kind: "entity_kind", phone: "dedicated_phone", mobile: "dedicated_phone",
  dedicated_login_phone: "dedicated_phone", login_phone: "dedicated_phone", entity_name: "name", admin_owner_name: "contact_person",
  owner: "contact_person", owner_name: "contact_person", admin_name: "contact_person", licence_number: "license_number",
  gst: "gst_number", dispatch_radius: "dispatch_radius_km", pin: "pincode", pin_code: "pincode" };
const key = (h) => { const k = String(h).trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, ""); return ALIAS[k] || k; };
const kindOf = (v) => { const k = key(v); return Object.keys(KIND_LABEL).find((x) => x === k || key(KIND_LABEL[x]) === k) || String(v || "").trim(); };

export function normalizeRow(raw) {
  const out = {};
  Object.entries(raw).forEach(([h, v]) => { const k = key(h); if (COLUMNS.includes(k) && v !== "" && v != null) out[k] = String(v).trim(); });
  if (out.entity_kind) out.entity_kind = kindOf(out.entity_kind);
  if (out.dedicated_phone) out.dedicated_phone = out.dedicated_phone.replace(/\D/g, "").slice(-10);
  return out;
}

export function rowErrors(r, allowed) {
  const e = {};
  FIELDS.forEach(([k, label, req]) => { if (req && !String(r[k] || "").trim()) e[k] = `${label} is required`; });
  if (!r.entity_kind) e.entity_kind = "Type is required";
  else if (!allowed.includes(r.entity_kind)) e.entity_kind = `"${r.entity_kind}" is not allowed`;
  if (r.dedicated_phone && !/^[6-9]\d{9}$/.test(r.dedicated_phone)) e.dedicated_phone = "Must be a 10-digit Indian mobile";
  if (r.pincode && !/^\d{6}$/.test(r.pincode)) e.pincode = "Must be 6 digits";
  if (r.email && !/^\S+@\S+\.\S+$/.test(r.email)) e.email = "Invalid email";
  if (r.dispatch_radius_km && !(Number(r.dispatch_radius_km) >= 0 && Number(r.dispatch_radius_km) <= 200)) e.dispatch_radius_km = "0 to 200 km";
  return e;
}

export const toPayload = (r) => {
  const b = Object.fromEntries(Object.entries(r).filter(([, v]) => v !== "" && v != null));
  if (b.dispatch_radius_km) b.dispatch_radius_km = Number(b.dispatch_radius_km);
  return b;
};
