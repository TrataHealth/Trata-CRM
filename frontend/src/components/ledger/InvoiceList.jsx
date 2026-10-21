import React from "react";
import { Download, Send, CheckCircle2, Ban, Mail, MailWarning } from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";
import { T, money, STATUS_TONE, pretty, downloadInvoice, toastErr } from "./ui";

export function InvoiceList({ invoices, admin, onChanged }) {
  const act = async (inv, path, msg) => {
    try { await api.post(`/ledger/invoices/${inv.id}/${path}`); toast.success(msg); onChanged(); } catch (e) { toastErr(e); }
  };
  const share = async (inv) => {
    try {
      const { data } = await api.post(`/ledger/invoices/${inv.id}/share`);
      const d = data.delivery || {};
      if (d.email_status === "sent") toast.success(`${data.number} shared · emailed to ${d.email}`);
      else if (d.email_status === "no_email_on_file") toast.warning(`${data.number} shared in CRM · no billing email on file (set it in Billing terms)`);
      else toast.warning(`${data.number} shared in CRM · email not sent (${d.email_status})`);
      onChanged();
    } catch (e) { toastErr(e); }
  };
  const lastMail = (i) => [...(i.deliveries || [])].reverse().find((d) => d.email_status !== "skipped");
  if (!invoices.length) return <div className="p-6 text-center text-sm text-[#5E6C84]" data-testid="invoices-empty">No invoices yet.</div>;
  return (
    <div className="overflow-x-auto" data-testid="invoices-table">
      <table className="min-w-full text-xs">
        <thead className="bg-[#F8F9FA] text-[#5E6C84] uppercase text-[10px]">
          <tr>
            <th className="px-3 py-2 text-left">Invoice #</th><th className="px-3 py-2 text-left">Month</th>
            {admin && <th className="px-3 py-2 text-left">Provider</th>}
            <th className="px-3 py-2 text-right">Taxable</th><th className="px-3 py-2 text-right">GST</th>
            <th className="px-3 py-2 text-right">Total</th><th className="px-3 py-2 text-left">Status</th><th className="px-3 py-2 text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {invoices.map((i) => (
            <tr key={i.id} className="border-t border-[#DFE1E6]" data-testid={`invoice-row-${i.id}`}>
              <td className="px-3 py-2 font-mono font-semibold">{i.number || <span className="text-[#7A5D00]">Draft</span>}
                {admin && lastMail(i) && (
                  <div className="text-[10px] font-sans font-normal text-[#5E6C84] flex items-center gap-1" data-testid={`invoice-email-${i.id}`} title={lastMail(i).email || ""}>
                    {lastMail(i).email_status === "sent" ? <Mail className="h-3 w-3 text-[#00875A]" /> : <MailWarning className="h-3 w-3 text-[#FF991F]" />}
                    {lastMail(i).kind === "reminder" ? `Reminder ${i.reminder_count || 1}×` : "Emailed"} · {lastMail(i).email_status.replace(/_/g, " ")}
                  </div>
                )}
              </td>
              <td className="px-3 py-2">{i.month}</td>
              {admin && <td className="px-3 py-2">{i.provider_name}</td>}
              <td className="px-3 py-2 text-right font-mono">{money(i.taxable_value)}</td>
              <td className="px-3 py-2 text-right font-mono">{money(i.gst_total)}</td>
              <td className="px-3 py-2 text-right font-mono font-bold">{money(i.grand_total)}</td>
              <td className="px-3 py-2"><span className={`${T.chip} ${STATUS_TONE[i.status]}`} data-testid={`invoice-status-${i.id}`}>{pretty(i.status)}</span></td>
              <td className="px-3 py-2">
                <div className="flex justify-end gap-1.5 flex-wrap">
                  <button className={T.btnGhost} onClick={() => downloadInvoice(i)} data-testid={`invoice-download-${i.id}`}><Download className="h-3.5 w-3.5" /> PDF</button>
                  {admin && ["issued", "draft"].includes(i.status) && <button className={T.btn} onClick={() => share(i)} data-testid={`invoice-share-${i.id}`}><Send className="h-3.5 w-3.5" /> {i.status === "draft" ? "Issue & share" : "Share"}</button>}
                  {admin && ["issued", "shared"].includes(i.status) && <button className={T.btnGhost} onClick={() => act(i, "status?status=paid", "Marked paid")} data-testid={`invoice-paid-${i.id}`}><CheckCircle2 className="h-3.5 w-3.5" /> Paid</button>}
                  {admin && !["void", "paid"].includes(i.status) && i.status !== "draft" && <button className={T.btnDanger} onClick={() => window.confirm("Void this invoice? Its items become billable again.") && act(i, "status?status=void", "Invoice voided")} data-testid={`invoice-void-${i.id}`}><Ban className="h-3.5 w-3.5" /> Void</button>}
                  {admin && i.status === "draft" && <button className={T.btnDanger} onClick={() => window.confirm("Discard this draft?") && act(i, "status?status=void", "Draft discarded")} data-testid={`invoice-discard-${i.id}`}><Ban className="h-3.5 w-3.5" /> Discard</button>}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
