import React, { useEffect, useState } from "react";
import { Fingerprint, Wifi, WifiOff } from "lucide-react";
import api from "../lib/api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { EnrolWizard } from "../components/abdm/EnrolWizard";
import { VerifyWizard } from "../components/abdm/VerifyWizard";
import { AbhaRecords } from "../components/abdm/AbhaRecords";
import { T } from "../components/ledger/ui";

export default function Abha() {
  const [status, setStatus] = useState(null);
  const [tick, setTick] = useState(0);
  useEffect(() => { api.get("/abdm/status").then((r) => setStatus(r.data)).catch(() => setStatus({ connected: false })); }, []);
  const saved = () => setTick((t) => t + 1);

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="abha-page">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="text-[11px] font-bold uppercase tracking-wider text-[#5E6C84] flex items-center gap-1.5"><Fingerprint className="h-3.5 w-3.5" /> ABDM · Milestone 1</div>
            <h1 className="font-heading text-3xl font-black text-[#091E42] mt-1">ABHA for patients</h1>
            <p className="text-sm text-[#42526E] mt-1">Create a patient's Ayushman Bharat Health Account with Aadhaar OTP, or verify an existing ABHA.</p>
          </div>
          {status && <span className={`${T.chip} gap-1 py-1 px-2.5 ${status.connected ? "bg-[#E3FCEF] text-[#006644]" : "bg-[#FFEBE6] text-[#BF2600]"}`} data-testid="abdm-status" title={status.error || ""}>
            {status.connected ? <Wifi className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}
            {status.connected ? `ABDM ${status.environment} connected` : "ABDM unreachable"}
          </span>}
        </div>
        <section className={`${T.card} p-5`}>
          <Tabs defaultValue="create">
            <TabsList>
              <TabsTrigger value="create" data-testid="abha-tab-create">Create ABHA</TabsTrigger>
              <TabsTrigger value="verify" data-testid="abha-tab-verify">Verify existing ABHA</TabsTrigger>
            </TabsList>
            <TabsContent value="create" className="mt-5"><EnrolWizard consentText={status?.consent_text} onSaved={saved} /></TabsContent>
            <TabsContent value="verify" className="mt-5"><VerifyWizard onSaved={saved} /></TabsContent>
          </Tabs>
        </section>
        <AbhaRecords refreshKey={tick} />
      </div>
  );
}
