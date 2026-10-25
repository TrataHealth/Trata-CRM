import { toast } from "sonner";

export const inr = (n) => (n == null ? "—" : `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`);
export const when = (s) => (s ? new Date(s).toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—");
export const errMsg = (e, d = "Something went wrong") => toast.error(e?.response?.data?.detail || d);

export const ORDER_STATUS = {
  PENDING_PHARMACY: ["New", "bg-[#FFF0B3] text-[#974F0C]"], PREORDER_PENDING: ["Pre-order", "bg-[#EAE6FF] text-[#403294]"],
  ACCEPTED: ["Accepted", "bg-[#DEEBFF] text-[#0747A6]"], FULFILLED: ["Fulfilled", "bg-[#E3FCEF] text-[#006644]"],
  REJECTED: ["Rejected", "bg-[#FFEBE6] text-[#BF2600]"], CANCELLED: ["Cancelled", "bg-[#F4F5F7] text-[#42526E]"],
};
export const RX_STATUS = {
  submitted: ["New", "bg-[#FFF0B3] text-[#974F0C]"], issued: ["Issued", "bg-[#FFF0B3] text-[#974F0C]"], pending: ["New", "bg-[#FFF0B3] text-[#974F0C]"],
  accepted: ["Accepted", "bg-[#DEEBFF] text-[#0747A6]"], ready_for_pickup: ["Ready", "bg-[#EAE6FF] text-[#403294]"],
  fulfilled: ["Fulfilled", "bg-[#E3FCEF] text-[#006644]"], rejected: ["Rejected", "bg-[#FFEBE6] text-[#BF2600]"],
};
export const Chip = ({ map, s, testid }) => { const [l, c] = map[s] || [s, "bg-[#F4F5F7] text-[#42526E]"]; return <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded ${c}`} data-testid={testid}>{l}</span>; };
export const itemLine = (it) => (typeof it === "string" ? it : [it.name || it.line, it.dosage, it.quantity].filter(Boolean).join(" · "));
export const inp = "w-full px-3 py-2 text-sm border border-[#DFE1E6] rounded-md focus:border-[#4C9AFF] outline-none bg-white";
export const btn = "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md disabled:opacity-50";
export const primary = `${btn} bg-[#0052CC] text-white hover:bg-[#0747A6]`;
export const ghost = `${btn} border border-[#DFE1E6] text-[#091E42] hover:bg-[#F8F9FA]`;
export const danger = `${btn} border border-[#FFBDAD] text-[#BF2600] hover:bg-[#FFEBE6]`;
