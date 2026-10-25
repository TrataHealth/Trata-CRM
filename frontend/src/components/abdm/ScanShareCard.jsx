import React, { useEffect, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { Link } from "react-router-dom";
import { Printer, QrCode, RefreshCw } from "lucide-react";
import api from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { T } from "../ledger/ui";

function printQr(svg, qr) {
  const w = window.open("", "_blank", "width=700,height=900");
  if (!w) return;
  w.document.write(`<html><head><title>Scan & Share — ${qr.hospital_name || ""}</title></head>
    <body style="font-family:sans-serif;text-align:center;padding:40px;color:#091E42">
    <h1 style="margin:0 0 6px">${qr.hospital_name || "Our hospital"}</h1><h2 style="margin:0 0 24px;font-weight:600">Skip the queue — scan with your ABHA app</h2>
    ${svg}<p style="font-size:18px;margin-top:24px">Open the ABHA app or any ABDM health app, tap <b>Scan &amp; Share</b>, then show the token number at the desk.</p>
    <p style="color:#5E6C84">Counter ${qr.code} · Facility ${qr.hip_id}</p><script>window.onload=()=>window.print()</script></body></html>`);
  w.document.close();
}

function QrPanel() {
  const [qr, setQr] = useState(null); const [err, setErr] = useState(""); const box = useRef();
  useEffect(() => { api.get("/abdm/share/qr").then((r) => setQr(r.data)).catch((e) => setErr(e?.response?.data?.detail || "Could not load the QR")); }, []);
  if (err) return <div className="text-sm text-[#BF2600]" data-testid="share-qr-error">{err}</div>;
  if (!qr) return <div className="text-sm text-[#5E6C84]">Loading QR…</div>;
  return (
    <div className="flex flex-col items-center gap-3 shrink-0" data-testid="share-qr-panel">
      <div ref={box} className="p-3 bg-white border border-[#DFE1E6] rounded-md"><QRCodeSVG value={qr.qr_url} size={168} data-testid="share-qr" /></div>
      <div className="text-[11px] text-[#5E6C84]">Counter <b data-testid="share-qr-code">{qr.code}</b></div>
      <button className={T.btn} onClick={() => printQr(box.current.innerHTML.replace('width="168" height="168"', 'width="320" height="320"'), qr)} data-testid="share-qr-print"><Printer className="h-3.5 w-3.5" /> Print poster</button>
    </div>
  );
}

function SharesTable({ rows, showHospital, linkBase }) {
  if (!rows.length) return <div className="text-sm text-[#5E6C84] py-6" data-testid="share-empty">No patients have shared their profile on this day yet.</div>;
  return (
    <div className="overflow-x-auto"><table className="w-full text-sm" data-testid="share-table">
      <thead><tr className="text-left text-[10px] uppercase tracking-wider text-[#5E6C84]">{["Token", "Patient", "ABHA", "Mobile", ...(showHospital ? ["Hospital"] : []), "Shared at", ""].map((h) => <th key={h} className="py-2 pr-3 font-semibold">{h}</th>)}</tr></thead>
      <tbody>{rows.map((r) => (
        <tr key={r.id} className="border-t border-[#F4F5F7]" data-testid={`share-row-${r.id}`}>
          <td className="py-2 pr-3"><span className="inline-grid place-items-center h-8 min-w-8 px-2 rounded-md bg-[#DEEBFF] text-[#0747A6] font-black" data-testid={`share-token-${r.id}`}>{r.token}</span></td>
          <td className="py-2 pr-3"><div className="font-semibold text-[#091E42]">{r.name}</div><div className="text-xs text-[#5E6C84]">{[r.gender, r.year_of_birth && `b. ${r.year_of_birth}`].filter(Boolean).join(" · ")}</div></td>
          <td className="py-2 pr-3 text-xs"><div>{r.abha_address}</div><div className="text-[#5E6C84]">{r.abha_number || "—"}</div></td>
          <td className="py-2 pr-3 text-xs">{r.phone_masked || "—"}</td>
          {showHospital && <td className="py-2 pr-3 text-xs">{r.hospital_name}</td>}
          <td className="py-2 pr-3 text-xs whitespace-nowrap">{new Date(r.last_shared_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}{r.share_count > 1 && <span className="text-[#5E6C84]"> · {r.share_count}×</span>}</td>
          <td className="py-2 text-xs">{linkBase && r.patient_user_id ? <Link to={`${linkBase}/${r.patient_user_id}`} className="text-[#0052CC] font-semibold" data-testid={`share-open-${r.id}`}>Open patient</Link> : r.save_error ? <span className="text-[#BF2600]" title={r.save_error}>Not saved</span> : <span className="text-[#36B37E]">Saved</span>}</td>
        </tr>))}</tbody>
    </table></div>
  );
}

export function ScanShareCard() {
  const { user, isProvider } = useAuth();
  const isHospital = isProvider && user?.provider_type === "hospital";
  const today = new Date(Date.now() + 5.5 * 3600e3).toISOString().slice(0, 10);
  const [date, setDate] = useState(today); const [data, setData] = useState(null);
  const load = () => api.get("/abdm/share/profiles", { params: { date } }).then((r) => setData(r.data)).catch(() => setData({ profiles: [] }));
  useEffect(() => { load(); const t = date === today ? setInterval(load, 15000) : null; return () => t && clearInterval(t); /* eslint-disable-next-line */ }, [date]);
  return (
    <section className={`${T.card} p-5`} data-testid="scan-share-card">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div><div className="font-heading font-bold text-[#091E42] flex items-center gap-2"><QrCode className="h-4 w-4 text-[#0052CC]" /> Scan & Share — OPD walk-ins</div>
          <p className="text-xs text-[#5E6C84] mt-0.5 max-w-xl">{isHospital ? "Patients scan this QR with their ABHA app. Their verified details are saved to your patient list and they get a token number for the day." : "Profiles shared by patients at every hospital's Scan & Share QR."}</p></div>
        <div className="flex items-center gap-2">
          <input type="date" value={date} max={today} onChange={(e) => setDate(e.target.value || today)} className={`${T.input} mt-0 w-auto`} data-testid="share-date" />
          <button className={T.btnGhost} onClick={load} data-testid="share-refresh"><RefreshCw className="h-3.5 w-3.5" /></button>
        </div>
      </div>
      <div className="flex flex-col lg:flex-row gap-6">
        {isHospital && <QrPanel />}
        <div className="flex-1 min-w-0">
          <div className="text-[11px] font-bold uppercase tracking-wider text-[#5E6C84] mb-1">Shared profiles <span data-testid="share-count">({data?.profiles.length ?? 0})</span></div>
          {data ? <SharesTable rows={data.profiles} showHospital={!isProvider} linkBase={isHospital ? "/provider/patients" : user?.is_master_admin ? "/admin/patients" : null} /> : <div className="text-sm text-[#5E6C84]">Loading…</div>}
        </div>
      </div>
    </section>
  );
}
