import React, { useEffect, useState } from "react";
import { Loader2, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../ui/dialog";
import { T, money, PAY_MODES, toastErr } from "./ui";

const today = () => new Date(Date.now() + 330 * 60000).toISOString().slice(0, 10);

export function PaidDialog({ invoice, onClose, onDone }) {
  const [f, setF] = useState({ paid_on: today(), mode: "bank_transfer", reference: "", note: "" });
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (invoice) setF({ paid_on: today(), mode: "bank_transfer", reference: "", note: "" }); }, [invoice]);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  const submit = async () => {
    setBusy(true);
    try {
      const { data } = await api.post(`/ledger/invoices/${invoice.id}/status`, f, { params: { status: "paid" } });
      const d = data.delivery || {};
      if (d.email_status === "sent") toast.success(`Marked paid · receipt ${data.receipt_no} emailed to ${d.email}`);
      else if (d.email_status === "no_email_on_file") toast.warning(`Marked paid · receipt in CRM · no billing email on file`);
      else toast.warning(`Marked paid · receipt in CRM · email not sent (${d.email_status})`);
      onDone();
      onClose();
    } catch (e) { toastErr(e, "Could not mark paid"); } finally { setBusy(false); }
  };

  return (
    <Dialog open={!!invoice} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-md" data-testid="paid-dialog">
        <DialogHeader><DialogTitle className="font-heading">Record payment</DialogTitle></DialogHeader>
        {invoice && <div className="space-y-3">
          <div className="text-xs text-[#42526E]"><b className="font-mono">{invoice.number}</b> · {invoice.provider_name} · <b>{money(invoice.grand_total)}</b></div>
          <div className="grid grid-cols-2 gap-3">
            <label className={T.label}>Received on<input type="date" min={invoice.issue_date} max={today()} className={T.input} value={f.paid_on} onChange={set("paid_on")} data-testid="paid-date" /></label>
            <label className={T.label}>Mode<select className={T.input} value={f.mode} onChange={set("mode")} data-testid="paid-mode">
              {Object.entries(PAY_MODES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          </div>
          <label className={T.label}>Reference (UTR / cheque no.)<input className={T.input} value={f.reference} onChange={set("reference")} maxLength={120} data-testid="paid-reference" /></label>
          <label className={T.label}>Note (shown on receipt)<input className={T.input} value={f.note} onChange={set("note")} maxLength={300} data-testid="paid-note" /></label>
          <p className="text-[11px] text-[#5E6C84]">A branded receipt is emailed to the provider and posted in their console automatically.</p>
          <div className="flex justify-end gap-2">
            <button className={T.btnGhost} onClick={onClose} data-testid="paid-cancel">Cancel</button>
            <button className={T.btn} onClick={submit} disabled={busy || !f.paid_on} data-testid="paid-submit">
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />} Mark paid & send receipt
            </button>
          </div>
        </div>}
      </DialogContent>
    </Dialog>
  );
}
