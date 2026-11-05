import React, { useEffect, useState } from "react";
import { Ban, Trash2, RotateCcw, ShieldCheck, Loader2, X } from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../ui/dialog";

const COPY = {
  suspend: { title: "Suspend users", verb: "Suspend", need: true, tone: "bg-[#DE350B] hover:bg-[#BF2600]",
    help: "They see a suspension notice in the Admin Console, Provider app and TrataX and can't use anything until you restore access. They're emailed with this reason." },
  unsuspend: { title: "Restore access", verb: "Restore access", need: false, tone: "bg-[#00875A] hover:bg-[#006644]",
    help: "The suspension is lifted everywhere and they're emailed that their account is active again." },
  archive: { title: "Delete users", verb: "Delete", need: true, tone: "bg-[#DE350B] hover:bg-[#BF2600]",
    help: "They disappear from every Trata app (all profiles on the account, as in the Provider App) and can't sign in. You can restore them from 'Deleted users' for 30 days — after that they're erased permanently." },
  restore: { title: "Restore deleted users", verb: "Restore", need: false, tone: "bg-[#0052CC] hover:bg-[#0747A6]",
    help: "They come back to every Trata app with their data." },
};

export function BulkActionDialog({ action, ids, onClose, onDone, field = "contact_ids" }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => setReason(""), [action]);
  if (!action) return null;
  const c = COPY[action];
  const submit = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/admin/users/bulk", { [field]: ids, action, reason: reason.trim() || null });
      const sent = Object.values(data.emails || {}).filter((v) => v === "sent").length;
      toast.success(`${c.verb}: ${data.updated} user${data.updated === 1 ? "" : "s"}${sent ? ` · ${sent} emailed` : ""}${data.skipped.length ? ` · skipped: ${data.skipped.map((x) => `${x.name || "user"} (${x.why})`).join(", ")}` : ""}`);
      onDone();
    } catch (e) { toast.error(e?.response?.data?.detail || "Action failed"); } finally { setBusy(false); }
  };
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-md" data-testid={`bulk-dialog-${action}`}>
        <DialogHeader><DialogTitle className="font-heading">{c.title} ({ids.length})</DialogTitle></DialogHeader>
        <p className="text-sm text-[#42526E]">{c.help}</p>
        {c.need && <label className="text-xs font-semibold text-[#42526E] block">Reason {action === "suspend" && "(shown to the user)"}
          <textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} data-testid="bulk-reason"
            className="mt-1 w-full px-3 py-2 text-sm border border-[#DFE1E6] rounded-md focus:border-[#4C9AFF] outline-none font-normal" /></label>}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-2 text-sm border border-[#DFE1E6] rounded-md" data-testid="bulk-cancel">Cancel</button>
          <button onClick={submit} disabled={busy || (c.need && reason.trim().length < 5)} data-testid="bulk-confirm"
            className={`inline-flex items-center gap-2 px-3 py-2 text-sm font-semibold text-white rounded-md disabled:opacity-50 ${c.tone}`}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}{c.verb} {ids.length}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export const SuspendedTag = ({ reason, testId }) => (
  <span title={reason || "Suspended"} data-testid={testId}
        className="inline-flex items-center gap-1 ml-2 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider rounded bg-[#FFEBE6] text-[#BF2600] align-middle">
    <Ban className="h-3 w-3" />Suspended</span>
);

/** Row-selection state for user tables keyed by users.id. */
export function useSelection(rows, keyOf = (r) => r.id) {
  const [sel, setSel] = useState(() => new Set());
  const ids = rows.map(keyOf);
  const all = ids.length > 0 && ids.every((i) => sel.has(i));
  const toggle = (id) => setSel((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const toggleAll = () => setSel(all ? new Set() : new Set(ids));
  const selected = ids.filter((i) => sel.has(i));
  return { sel, selected, all, toggle, toggleAll, clear: () => setSel(new Set()) };
}

export const RowCheck = ({ checked, onChange, testId }) => (
  <input type="checkbox" checked={checked} onChange={onChange} onClick={(e) => e.stopPropagation()} data-testid={testId}
         className="h-4 w-4 accent-[#0052CC] cursor-pointer" />
);

export function BulkBar({ count, archivedView, onAction, onClear }) {
  if (!count) return null;
  const B = ({ a, icon: I, label, cls }) => (
    <button onClick={() => onAction(a)} data-testid={`bulk-${a}`} className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md transition-colors ${cls}`}><I className="h-3.5 w-3.5" />{label}</button>
  );
  return (
    <div className="sticky top-2 z-20 flex flex-wrap items-center gap-2 bg-[#091E42] text-white rounded-md px-3 py-2 shadow-lg" data-testid="bulk-bar">
      <span className="text-sm font-semibold mr-1" data-testid="bulk-count">{count} selected</span>
      {archivedView ? <B a="restore" icon={RotateCcw} label="Restore" cls="bg-white/10 hover:bg-white/20" /> : <>
        <B a="suspend" icon={Ban} label="Suspend" cls="bg-[#FF8B00] hover:bg-[#FF991F] text-[#091E42]" />
        <B a="unsuspend" icon={ShieldCheck} label="Restore access" cls="bg-white/10 hover:bg-white/20" />
        <B a="archive" icon={Trash2} label="Delete" cls="bg-[#DE350B] hover:bg-[#FF5630]" />
      </>}
      <button onClick={onClear} className="ml-auto p-1 rounded hover:bg-white/10" data-testid="bulk-clear" title="Clear selection"><X className="h-4 w-4" /></button>
    </div>
  );
}
