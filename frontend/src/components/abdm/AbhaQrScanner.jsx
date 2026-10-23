import React, { useEffect, useRef, useState } from "react";
import { Html5Qrcode } from "html5-qrcode";
import { Camera, Loader2, QrCode } from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../ui/dialog";
import { T, toastErr } from "../ledger/ui";

function Viewfinder({ onText }) {
  const ref = useRef(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    const q = new Html5Qrcode("abha-qr-reader", { verbose: false });
    let done = false;
    q.start({ facingMode: "environment" }, { fps: 10, qrbox: { width: 240, height: 240 } },
      (text) => { if (!done) { done = true; onText(text); } }, () => {})
      .catch(() => setErr("Camera not available — allow camera access in the browser and try again."));
    ref.current = q;
    return () => { q.isScanning ? q.stop().then(() => q.clear()).catch(() => {}) : q.clear(); };
  }, [onText]);
  return (
    <div>
      <div id="abha-qr-reader" className="w-full overflow-hidden rounded-md bg-black min-h-[240px]" data-testid="abha-qr-viewfinder" />
      {err && <p className="text-xs text-[#BF2600] mt-2" data-testid="abha-qr-camera-error">{err}</p>}
    </div>
  );
}

/** Scans the QR on a patient's ABHA card, saves it, and returns {record, profile}. */
export function AbhaQrScanner({ patientUserId, patientPhone, onResult, label = "Scan ABHA QR", className, testid = "abha-qr-open" }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const handle = React.useCallback(async (text) => {
    setBusy(true);
    try {
      const { data } = await api.post("/abdm/records/from-qr", { qr: text, patient_user_id: patientUserId || null, patient_phone: (patientPhone || "").replace(/\D/g, "").slice(-10) || null });
      toast.success(`ABHA ${data.record.abha_number} captured for ${data.record.name || "patient"}`);
      setOpen(false);
      onResult?.(data);
    } catch (e) { toastErr(e, "Could not read this QR"); setOpen(false); } finally { setBusy(false); }
  }, [patientUserId, patientPhone, onResult]);

  return (
    <>
      <button type="button" className={className || T.btnGhost} onClick={() => setOpen(true)} data-testid={testid}><QrCode className="h-3.5 w-3.5" /> {label}</button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-sm" data-testid="abha-qr-dialog">
          <DialogHeader><DialogTitle className="font-heading flex items-center gap-2"><Camera className="h-4 w-4" /> Scan the ABHA card QR</DialogTitle></DialogHeader>
          {open && !busy && <Viewfinder onText={handle} />}
          {busy && <div className="h-[240px] grid place-items-center text-sm text-[#5E6C84]"><Loader2 className="h-5 w-5 animate-spin" /></div>}
          <p className="text-[11px] text-[#5E6C84]">Hold the patient's ABHA card or ABHA app QR steady inside the box. Details are filled from the card; verify with OTP on the ABHA page for KYC-verified status.</p>
        </DialogContent>
      </Dialog>
    </>
  );
}
