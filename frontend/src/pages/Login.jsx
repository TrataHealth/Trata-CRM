import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { ShieldCheck, ArrowRight, Loader2 } from "lucide-react";

export default function Login() {
  const { sendOtp, login, user } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState("phone");
  const [phone, setPhone] = useState("9873117605");
  const [otp, setOtp] = useState("123456");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  React.useEffect(() => {
    if (user) navigate("/");
  }, [user, navigate]);

  const onSend = async (e) => {
    e?.preventDefault();
    setErr("");
    if (phone.length < 10) return setErr("Enter a valid 10-digit phone");
    setLoading(true);
    try { await sendOtp(phone); setStep("otp"); } catch (e) { setErr(e?.response?.data?.detail || "Failed"); }
    setLoading(false);
  };

  const onVerify = async (e) => {
    e?.preventDefault();
    setErr("");
    if (otp.length !== 6) return setErr("Enter 6-digit OTP");
    setLoading(true);
    try { await login(phone, otp); navigate("/"); } catch (e) { setErr(e?.response?.data?.detail || "Login failed"); }
    setLoading(false);
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2 bg-white" data-testid="login-page">
      {/* Left visual */}
      <div className="hidden lg:flex relative overflow-hidden bg-[#091E42] text-white">
        <div className="absolute inset-0 bg-grid opacity-10" />
        <div className="absolute -top-32 -left-32 w-96 h-96 rounded-full bg-[#0052CC] blur-3xl opacity-40" />
        <div className="absolute -bottom-32 -right-32 w-96 h-96 rounded-full bg-[#00B8D9] blur-3xl opacity-30" />
        <div className="relative z-10 p-12 flex flex-col h-full">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-md bg-white text-[#0052CC] flex items-center justify-center font-heading font-black text-lg">T</div>
            <div>
              <div className="font-heading font-bold text-xl">TrataHealth CRM</div>
              <div className="text-xs opacity-70 tracking-widest uppercase">Master Operations Console</div>
            </div>
          </div>
          <div className="mt-auto space-y-6">
            <h1 className="font-heading text-5xl font-black tracking-tight leading-[1.05]">
              Run every<br />
              <span className="text-[#79E2F2]">patient, provider,</span><br />
              and case<br />
              from one console.
            </h1>
            <p className="text-base text-white/70 max-w-md leading-relaxed">
              Unified view of patients, doctors, hospitals, paramedics, ambulance fleets and pathology labs — with real-time activity, pipeline, tasks, analytics, and Claude-powered insights.
            </p>
            <div className="grid grid-cols-3 gap-4 pt-4">
              {[
                { k: "Live", v: "Activity feed" },
                { k: "AI", v: "Next-best-action" },
                { k: "Ops", v: "Pipeline & KYC" },
              ].map((s) => (
                <div key={s.k} className="border-l border-white/20 pl-3">
                  <div className="font-heading text-xl font-bold text-[#79E2F2]">{s.k}</div>
                  <div className="text-xs text-white/60 tracking-wider uppercase">{s.v}</div>
                </div>
              ))}
            </div>
          </div>
          <div className="mt-12 text-xs text-white/50 flex items-center gap-2">
            <ShieldCheck className="h-3.5 w-3.5" />
            Restricted to authorized administrators · All access logged
          </div>
        </div>
      </div>

      {/* Right form */}
      <div className="flex items-center justify-center p-8">
        <div className="w-full max-w-md">
          <div className="lg:hidden flex items-center gap-3 mb-8">
            <div className="h-10 w-10 rounded-md bg-[#0052CC] text-white flex items-center justify-center font-heading font-black text-lg">T</div>
            <div className="font-heading font-bold text-lg">TrataHealth CRM</div>
          </div>
          <div className="overline mb-2">Step {step === "phone" ? "1" : "2"} of 2</div>
          <h2 className="font-heading text-3xl font-bold tracking-tight text-[#091E42] mb-2">
            {step === "phone" ? "Admin Sign-in" : "Verify your number"}
          </h2>
          <p className="text-sm text-[#5E6C84] mb-8">
            {step === "phone"
              ? "Enter the master admin phone number to receive a one-time passcode."
              : `OTP sent to +91 ${phone}. Use ${"123456"} for testing.`}
          </p>

          {step === "phone" ? (
            <form onSubmit={onSend} className="space-y-4">
              <label className="block">
                <span className="overline">Phone Number</span>
                <div className="mt-2 flex">
                  <span className="px-3 inline-flex items-center bg-[#F1F2F4] border border-r-0 border-[#DFE1E6] rounded-l-md text-sm text-[#091E42] font-medium">+91</span>
                  <input
                    data-testid="login-phone-input"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value.replace(/[^0-9]/g, ""))}
                    maxLength={10}
                    placeholder="9873117605"
                    className="flex-1 px-3 py-2.5 text-sm bg-white border border-[#DFE1E6] rounded-r-md focus:border-[#4C9AFF] focus:ring-2 focus:ring-[#4C9AFF]/30 outline-none"
                  />
                </div>
              </label>
              {err && <div className="text-sm text-[#FF5630]" data-testid="login-error">{err}</div>}
              <button
                data-testid="login-send-otp-btn"
                type="submit"
                disabled={loading}
                className="w-full flex items-center justify-center gap-2 bg-[#0052CC] hover:bg-[#0747A6] text-white py-2.5 rounded-md font-semibold text-sm transition-colors disabled:opacity-60"
              >
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <>Send OTP <ArrowRight className="h-4 w-4" /></>}
              </button>
            </form>
          ) : (
            <form onSubmit={onVerify} className="space-y-4">
              <label className="block">
                <span className="overline">One-Time Passcode</span>
                <input
                  data-testid="login-otp-input"
                  value={otp}
                  onChange={(e) => setOtp(e.target.value.replace(/[^0-9]/g, ""))}
                  maxLength={6}
                  placeholder="123456"
                  className="mt-2 w-full px-3 py-2.5 text-lg tracking-[0.5em] text-center font-mono bg-white border border-[#DFE1E6] rounded-md focus:border-[#4C9AFF] focus:ring-2 focus:ring-[#4C9AFF]/30 outline-none"
                />
              </label>
              {err && <div className="text-sm text-[#FF5630]" data-testid="login-error">{err}</div>}
              <button
                data-testid="login-verify-btn"
                type="submit"
                disabled={loading}
                className="w-full flex items-center justify-center gap-2 bg-[#0052CC] hover:bg-[#0747A6] text-white py-2.5 rounded-md font-semibold text-sm disabled:opacity-60"
              >
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <>Verify & Enter Console <ArrowRight className="h-4 w-4" /></>}
              </button>
              <button
                type="button"
                onClick={() => setStep("phone")}
                className="w-full text-xs text-[#5E6C84] hover:text-[#091E42] py-1"
              >
                Use a different number
              </button>
            </form>
          )}

          <div className="mt-10 pt-6 border-t border-[#DFE1E6] text-xs text-[#5E6C84] flex items-start gap-2">
            <ShieldCheck className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            <span>This console is restricted to authorized TrataHealth administrators. All sign-in attempts are logged and monitored.</span>
          </div>
        </div>
      </div>
    </div>
  );
}
