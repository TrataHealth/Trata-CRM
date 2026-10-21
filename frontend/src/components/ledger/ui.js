import api from "../../lib/api";
import { toast } from "sonner";

export const T = {
  card: "bg-white border border-[#DFE1E6] rounded-md",
  head: "px-4 py-2 text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold border-b border-[#DFE1E6] bg-[#F8F9FA] flex items-center justify-between gap-2",
  btn: "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md bg-[#0052CC] text-white hover:bg-[#0747A6] transition-colors disabled:opacity-40",
  btnGhost: "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md text-[#42526E] border border-[#DFE1E6] bg-white hover:bg-[#F4F5F7] transition-colors disabled:opacity-40",
  btnDanger: "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md text-[#BF2600] border border-[#FFBDAD] bg-white hover:bg-[#FFEBE6] disabled:opacity-40",
  input: "w-full mt-1 text-xs px-2 py-1.5 bg-white border border-[#DFE1E6] rounded focus:border-[#4C9AFF] focus:ring-2 focus:ring-[#4C9AFF]/30 outline-none",
  label: "block text-[11px] text-[#42526E] font-medium",
  chip: "inline-flex items-center px-2 py-0.5 text-[10px] font-bold rounded-full whitespace-nowrap",
};

export const INDIAN_STATES = ["Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chandigarh",
  "Chhattisgarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Goa", "Gujarat", "Haryana", "Himachal Pradesh",
  "Jammu and Kashmir", "Jharkhand", "Karnataka", "Kerala", "Ladakh", "Lakshadweep", "Madhya Pradesh", "Maharashtra",
  "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Puducherry", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
  "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal"];

export const money = (v) => `₹${Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
export const thisMonth = () => new Date().toISOString().slice(0, 7);
export const pretty = (s) => String(s || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const KIND_LABEL = {
  consultation: "OPD consult", teleconsultation: "Teleconsult", sos: "Emergency SOS", admission: "Admission",
  ambulance_ride: "Ambulance ride", lab_test: "Lab test", manual: "Extended service",
};

export const STATUS_TONE = {
  approved: "bg-[#E3FCEF] text-[#006644]", pending_review: "bg-[#FFFAE6] text-[#974F0C]",
  rejected: "bg-[#FFEBE6] text-[#BF2600]", issued: "bg-[#DEEBFF] text-[#0747A6]",
  shared: "bg-[#EAE6FF] text-[#403294]", paid: "bg-[#E3FCEF] text-[#006644]", void: "bg-[#F4F5F7] text-[#5E6C84]",
};

const errMsg = (e, fb) => {
  const d = e?.response?.data?.detail;
  return typeof d === "string" ? d : fb;
};
export const toastErr = (e, fb = "Something went wrong") => toast.error(errMsg(e, fb));

export async function openFile(fid) {
  try {
    const { data } = await api.get(`/ledger/files/${fid}`, { responseType: "blob" });
    window.open(URL.createObjectURL(data), "_blank", "noopener");
  } catch (e) { toastErr(e, "Could not open document"); }
}

export async function downloadInvoice(inv) {
  try {
    const { data } = await api.get(`/ledger/invoices/${inv.id}/pdf`, { responseType: "blob" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(data);
    a.download = `${inv.number.replace(/\//g, "-")}.pdf`;
    a.click();
  } catch (e) { toastErr(e, "Download failed"); }
}
