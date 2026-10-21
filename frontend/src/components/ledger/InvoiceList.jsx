import React from "react";
import { Download, Send, CheckCircle2, Ban } from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";
import { T, money, STATUS_TONE, pretty, downloadInvoice, toastErr } from "./ui";

export function InvoiceList({ invoices, admin, onChanged }) {
  const act = async (inv, path, msg) => {
    try { await api.post(`/ledger/invoices/${inv.id}/${path}`); toast.success(msg); onChanged(); } catch (e) { toastErr(e); }
  };
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
              <td className="px-3 py-2 font-mono font-semibold">{i.number}</td>
              <td className="px-3 py-2">{i.month}</td>
              {admin && <td className="px-3 py-2">{i.provider_name}</td>}
              <td className="px-3 py-2 text-right font-mono">{money(i.taxable_value)}</td>
              <td className="px-3 py-2 text-right font-mono">{money(i.gst_total)}</td>
              <td className="px-3 py-2 text-right font-mono font-bold">{money(i.grand_total)}</td>
              <td className="px-3 py-2"><span className={`${T.chip} ${STATUS_TONE[i.status]}`} data-testid={`invoice-status-${i.id}`}>{pretty(i.status)}</span></td>
              <td className="px-3 py-2">
                <div className="flex justify-end gap-1.5 flex-wrap">
                  <button className={T.btnGhost} onClick={() => downloadInvoice(i)} data-testid={`invoice-download-${i.id}`}><Download className="h-3.5 w-3.5" /> PDF</button>
                  {admin && i.status === "issued" && <button className={T.btn} onClick={() => act(i, "share", "Shared with provider")} data-testid={`invoice-share-${i.id}`}><Send className="h-3.5 w-3.5" /> Share</button>}
                  {admin && ["issued", "shared"].includes(i.status) && <button className={T.btnGhost} onClick={() => act(i, "status?status=paid", "Marked paid")} data-testid={`invoice-paid-${i.id}`}><CheckCircle2 className="h-3.5 w-3.5" /> Paid</button>}
                  {admin && i.status !== "void" && <button className={T.btnDanger} onClick={() => window.confirm("Void this invoice? Its items become billable again.") && act(i, "status?status=void", "Invoice voided")} data-testid={`invoice-void-${i.id}`}><Ban className="h-3.5 w-3.5" /> Void</button>}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
