import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { ShieldCheck, Mail, KeyRound, Loader2, CheckCircle2, RefreshCw } from "lucide-react";
import SecuritySetup from "./SecuritySetup";

export default function Settings() {
  const { user, refresh } = useAuth();
  const [status, setStatus] = useState(null);
  const [showSetup, setShowSetup] = useState(false);

  const load = async () => {
    const { data } = await api.get("/auth/security-status");
    setStatus(data);
  };
  useEffect(() => { load(); }, []);

  if (showSetup) {
    return (
      <SecuritySetup
        onComplete={async () => {
          setShowSetup(false);
          if (refresh) await refresh();
          await load();
        }}
      />
    );
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 max-w-3xl space-y-6" data-testid="settings-page">
      <div>
        <div className="overline">Account</div>
        <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">Settings</h1>
        <p className="text-sm text-[#5E6C84] mt-1">Signed in as <b className="text-[#091E42]">{user?.name}</b> · {user?.phone}</p>
      </div>

      <div className="bg-white border border-[#DFE1E6] rounded-md p-5" data-testid="settings-recovery-card">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <div className="overline flex items-center gap-1.5"><ShieldCheck className="h-3 w-3" /> Password recovery</div>
            <div className="font-heading text-lg font-bold text-[#091E42] mt-1">Recovery email + security questions</div>
            <p className="text-xs text-[#5E6C84] mt-1">Used if you ever forget your password. Answer 1 of 2 questions correctly to receive a 6-digit code by email.</p>
          </div>
          <button
            onClick={() => setShowSetup(true)}
            data-testid="settings-update-recovery-btn"
            className="flex items-center gap-2 px-3 py-2 text-sm font-semibold bg-[#0052CC] hover:bg-[#0747A6] text-white rounded-md"
          >
            <RefreshCw className="h-4 w-4" /> Update
          </button>
        </div>

        <div className="mt-4 grid sm:grid-cols-2 gap-3">
          <div className="border border-[#DFE1E6] rounded p-3">
            <div className="overline flex items-center gap-1.5"><Mail className="h-3 w-3" /> Recovery email</div>
            {!status && <div className="text-sm text-[#5E6C84] mt-2"><Loader2 className="h-4 w-4 inline animate-spin mr-1" /> Loading…</div>}
            {status && (
              status.has_recovery_email ? (
                <div className="mt-2 flex items-center gap-2 text-sm text-[#091E42]" data-testid="settings-email-set">
                  <CheckCircle2 className="h-4 w-4 text-[#36B37E]" />
                  <span className="font-mono">{status.recovery_email_masked}</span>
                </div>
              ) : (
                <div className="mt-2 text-sm text-[#974F0C]" data-testid="settings-email-missing">Not set yet</div>
              )
            )}
          </div>
          <div className="border border-[#DFE1E6] rounded p-3">
            <div className="overline flex items-center gap-1.5"><KeyRound className="h-3 w-3" /> Security questions</div>
            {!status && <div className="text-sm text-[#5E6C84] mt-2"><Loader2 className="h-4 w-4 inline animate-spin mr-1" /> Loading…</div>}
            {status && (
              status.has_security_questions ? (
                <ul className="mt-2 space-y-1 text-xs text-[#091E42]" data-testid="settings-questions-set">
                  {status.questions_set.map((q) => (
                    <li key={q.id} className="flex items-center gap-2">
                      <CheckCircle2 className="h-3.5 w-3.5 text-[#36B37E] shrink-0" /> {q.text}
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="mt-2 text-sm text-[#974F0C]" data-testid="settings-questions-missing">Not set yet</div>
              )
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
