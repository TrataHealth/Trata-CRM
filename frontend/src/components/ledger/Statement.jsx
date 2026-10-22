import React, { useCallback, useEffect, useRef, useState } from "react";
import { Download, Loader2, RotateCcw } from "lucide-react";
import api from "../../lib/api";
import { T, money, toastErr, downloadPdf } from "./ui";

const Stat = ({ label, value, tone = "", testid }) => (
  <div className="px-4 py-3" data-testid={testid}>
    <div className="text-[10px] uppercase tracking-wider text-[#5E6C84] font-semibold">{label}</div>
    <div className={`font-heading text-lg font-black mt-0.5 ${tone}`}>{value}</div>
  </div>
);

export function Statement({ uid, refreshKey }) {
  const [range, setRange] = useState({ from: "", to: "" });
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);
  const params = useCallback(() => ({ ...(uid ? { uid } : {}), ...(range.from ? { from: range.from } : {}), ...(range.to ? { to: range.to } : {}) }), [uid, range]);
  const load = useCallback(async () => {
    const n = ++seq.current;
    setBusy(true);
    try {
      const { data: d } = await api.get("/ledger/statement", { params: params() });
      if (n === seq.current) setData(d);
    } catch (e) { if (n === seq.current) toastErr(e, "Could not load statement"); }
    finally { if (n === seq.current) setBusy(false); }
  }, [params]);
  useEffect(() => { load(); }, [load, refreshKey]);

  return (
    <section className={T.card} data-testid="statement">
      <div className={`${T.head} flex-wrap`}>
        <span className="flex items-center gap-1.5">Account statement{busy && data && <Loader2 className="h-3 w-3 animate-spin" data-testid="statement-loading" />}</span>
        <div className="flex items-center gap-2 flex-wrap normal-case tracking-normal font-normal">
          <label className="flex items-center gap-1">From<input type="date" className={`${T.input} mt-0 w-36`} value={range.from} max={range.to || undefined} onChange={(e) => setRange({ ...range, from: e.target.value })} data-testid="statement-from" /></label>
          <label className="flex items-center gap-1">To<input type="date" className={`${T.input} mt-0 w-36`} value={range.to} min={range.from || undefined} onChange={(e) => setRange({ ...range, to: e.target.value })} data-testid="statement-to" /></label>
          {(range.from || range.to) && <button className={T.btnGhost} onClick={() => setRange({ from: "", to: "" })} data-testid="statement-reset"><RotateCcw className="h-3.5 w-3.5" /> All time</button>}
          <button className={T.btn} disabled={!data} onClick={() => downloadPdf("/ledger/statement/pdf", `Trata-statement-${data.generated_on}.pdf`, params())} data-testid="statement-pdf"><Download className="h-3.5 w-3.5" /> PDF</button>
        </div>
      </div>
      {!data ? <div className="p-6 flex items-center gap-2 text-sm text-[#5E6C84]"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div> : <>
        <div className={`transition-opacity ${busy ? "opacity-50" : ""}`}>
        <div className="grid grid-cols-2 md:grid-cols-4 divide-x divide-[#F4F5F7] border-b border-[#DFE1E6]">
          <Stat label="Opening balance" value={money(data.opening_balance)} testid="statement-opening" />
          <Stat label="Invoiced" value={money(data.total_debit)} testid="statement-debit" />
          <Stat label="Paid" value={money(data.total_credit)} tone="text-[#006644]" testid="statement-credit" />
          <Stat label="Amount due" value={money(data.closing_balance)} tone={data.closing_balance > 0 ? "text-[#BF2600]" : "text-[#006644]"} testid="statement-closing" />
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-xs" data-testid="statement-table">
            <thead className="bg-[#F8F9FA] text-[#5E6C84] uppercase text-[10px]"><tr>
              {["Date", "Type", "Reference", "Invoiced", "Paid", "Balance"].map((h, i) => <th key={h} className={`px-3 py-2 ${i > 2 ? "text-right" : "text-left"}`}>{h}</th>)}
            </tr></thead>
            <tbody>
              <tr className="border-t border-[#DFE1E6] italic text-[#5E6C84]"><td className="px-3 py-2" colSpan={5}>Opening balance</td><td className="px-3 py-2 text-right font-mono">{money(data.opening_balance)}</td></tr>
              {data.entries.length === 0 && <tr><td colSpan={6} className="px-3 py-6 text-center text-[#5E6C84]" data-testid="statement-empty">No invoices or payments in this period.</td></tr>}
              {data.entries.map((x, i) => (
                <tr key={`${x.invoice_id}-${x.type}`} className="border-t border-[#DFE1E6]" data-testid={`statement-row-${i}`}>
                  <td className="px-3 py-2 whitespace-nowrap">{x.date}</td>
                  <td className="px-3 py-2"><span className={`${T.chip} ${x.type === "payment" ? "bg-[#E3FCEF] text-[#006644]" : "bg-[#DEEBFF] text-[#0747A6]"}`}>{x.type === "payment" ? "Payment" : "Invoice"}</span></td>
                  <td className="px-3 py-2"><div className="font-mono font-semibold">{x.ref}</div><div className="text-[10px] text-[#5E6C84]">{x.description}</div></td>
                  <td className="px-3 py-2 text-right font-mono">{x.debit ? money(x.debit) : ""}</td>
                  <td className="px-3 py-2 text-right font-mono text-[#006644]">{x.credit ? money(x.credit) : ""}</td>
                  <td className="px-3 py-2 text-right font-mono font-bold">{money(x.balance)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        </div>
      </>}
    </section>
  );
}
