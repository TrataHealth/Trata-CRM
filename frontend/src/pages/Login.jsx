import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { ShieldCheck, ArrowRight, Loader2, Lock, KeyRound } from "lucide-react";

export default function Login() {
  const { sendOtp, verifyOtp, setPassword, loginPassword, user } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState("phone");
  const [phone, setPhoneN] = useState("9873117605");
  const [otp, setOtp] = useState("123456");
  const [password, setPasswordN] = useState("");
  const [tempToken, setTempToken] = useState(null);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [previewUser, setPreviewUser] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  React.useEffect(() => {
    if (user) navigate(user.role === "provider_owner" ? "/provider" : "/");
  }, [user, navigate]);

  const onSendOtp = async (e) => {
    e?.preventDefault();
    setErr("");
    if (phone.length < 10) return setErr("Enter a valid 10-digit phone");
    setLoading(true);
    try { await sendOtp(phone); setStep("otp"); }
    catch (e) { setErr(e?.response?.data?.detail || "Failed"); }
    setLoading(false);
  };

  const onVerifyOtp = async (e) => {
    e?.preventDefault();
    setErr("");
    if (otp.length !== 6) return setErr("Enter 6-digit OTP");
    setLoading(true);
    try {
      const r = await verifyOtp(phone, otp);
      setTempToken(r.temp_token);
      setNeedsSetup(r.needs_password_setup);
      setPreviewUser(r.user);
      setStep("password");
    } catch (e) { setErr(e?.response?.data?.detail || "Login failed"); }
    setLoading(false);
  };

  const onPassword = async (e) => {
    e?.preventDefault();
    setErr("");
    if (password.length < 6) return setErr("Password must be at least 6 characters");
    setLoading(true);
    try {
      const u = needsSetup
        ? await setPassword(tempToken, password)
        : await loginPassword(tempToken, password);
      navigate(u.role === "provider_owner" ? "/provider" : "/");
    } catch (e) { setErr(e?.response?.data?.detail || "Password failed"); }
    setLoading(false);
  };

  const titles = {
    phone: { kicker: "Step 1 of 3", title: "Sign in", sub: "Enter your registered phone number." },
    otp:   { kicker: "Step 2 of 3", title: "Verify your number", sub: `OTP sent to +91 ${phone}. Use 123456 for testing.` },
    password: {
      kicker: "Step 3 of 3",
      title: needsSetup ? "Set your password" : "Enter your password",
      sub: needsSetup
        ? "First time signing in — choose a password (min 6 chars) for your TrataCRM account."
        : `Welcome back${previewUser?.name ? `, ${previewUser.name}` : ""}. Enter your password to continue.`,
    },
  };

  const t = titles[step];

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
              <div className="text-xs opacity-70 tracking-widest uppercase">Master Operations · Provider Portal</div>
            </div>
          </div>
          <div className="mt-auto space-y-6">
            <h1 className="font-heading text-5xl font-black tracking-tight leading-[1.05]">
              One console.<br />
              <span className="text-[#79E2F2]">Every provider.</span><br />
              Every activity.
            </h1>
            <p className="text-base text-white/70 max-w-md leading-relaxed">
              HQ team sees the whole network. Hospital, clinic, ambulance and lab owners see exactly their own world — real-time activity, KYC, earnings and AI insights tailored to their role.
            </p>
            <div className="grid grid-cols-3 gap-4 pt-4">
              {[
                { k: "Phone", v: "OTP delivered" },
                { k: "Pass", v: "Secure 2nd factor" },
                { k: "Role", v: "Scoped data" },
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
            Phone + OTP + Password. All access logged.
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
          <div className="overline mb-2">{t.kicker}</div>
          <h2 className="font-heading text-3xl font-bold tracking-tight text-[#091E42] mb-2">{t.title}</h2>
          <p className="text-sm text-[#5E6C84] mb-8">{t.sub}</p>

          {step === "phone" && (
            <form onSubmit={onSendOtp} className="space-y-4">
              <label className="block">
                <span className="overline">Phone Number</span>
                <div className="mt-2 flex">
                  <span className="px-3 inline-flex items-center bg-[#F1F2F4] border border-r-0 border-[#DFE1E6] rounded-l-md text-sm text-[#091E42] font-medium">+91</span>
                  <input
                    data-testid="login-phone-input"
                    value={phone}
                    onChange={(e) => setPhoneN(e.target.value.replace(/[^0-9]/g, ""))}
                    maxLength={10}
                    placeholder="9873117605"
                    className="flex-1 px-3 py-2.5 text-sm bg-white border border-[#DFE1E6] rounded-r-md focus:border-[#4C9AFF] focus:ring-2 focus:ring-[#4C9AFF]/30 outline-none"
                  />
                </div>
              </label>
              {err && <div className="text-sm text-[#FF5630]" data-testid="login-error">{err}</div>}
              <SubmitBtn loading={loading} testid="login-send-otp-btn">
                Send OTP <ArrowRight className="h-4 w-4" />
              </SubmitBtn>
              <DemoCreds />
            </form>
          )}

          {step === "otp" && (
            <form onSubmit={onVerifyOtp} className="space-y-4">
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
              <SubmitBtn loading={loading} testid="login-verify-btn">
                Verify OTP <ArrowRight className="h-4 w-4" />
              </SubmitBtn>
              <button type="button" onClick={() => setStep("phone")} className="w-full text-xs text-[#5E6C84] hover:text-[#091E42] py-1">
                Use a different number
              </button>
            </form>
          )}

          {step === "password" && (
            <form onSubmit={onPassword} className="space-y-4">
              {previewUser?.role && (
                <div className="text-xs text-[#5E6C84] mb-1">
                  Signing in as <span className="font-semibold text-[#091E42]">{previewUser.name}</span>
                  {previewUser.role === "provider_owner" && previewUser.provider_type && (
                    <span> · <span className="inline-flex px-1.5 py-0.5 bg-[#E6FCFF] text-[#006A75] rounded text-[10px] font-bold uppercase tracking-wider">{previewUser.provider_type}</span></span>
                  )}
                  {previewUser.role === "admin" && (
                    <span> · <span className="inline-flex px-1.5 py-0.5 bg-[#FFEBE6] text-[#974F0C] rounded text-[10px] font-bold uppercase tracking-wider">Master Admin</span></span>
                  )}
                </div>
              )}
              <label className="block">
                <span className="overline">{needsSetup ? "Choose Password" : "Password"}</span>
                <div className="mt-2 relative">
                  {needsSetup
                    ? <KeyRound className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#5E6C84]" />
                    : <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#5E6C84]" />
                  }
                  <input
                    data-testid="login-password-input"
                    value={password}
                    onChange={(e) => setPasswordN(e.target.value)}
                    type="password"
                    autoComplete={needsSetup ? "new-password" : "current-password"}
                    placeholder={needsSetup ? "Choose a strong password" : "Enter your password"}
                    className="pl-9 w-full px-3 py-2.5 text-sm bg-white border border-[#DFE1E6] rounded-md focus:border-[#4C9AFF] focus:ring-2 focus:ring-[#4C9AFF]/30 outline-none"
                  />
                </div>
              </label>
              {err && <div className="text-sm text-[#FF5630]" data-testid="login-error">{err}</div>}
              <SubmitBtn loading={loading} testid={needsSetup ? "login-set-password-btn" : "login-password-btn"}>
                {needsSetup ? "Set Password & Enter" : "Sign in"} <ArrowRight className="h-4 w-4" />
              </SubmitBtn>
              <button type="button" onClick={() => { setStep("otp"); setPasswordN(""); }} className="w-full text-xs text-[#5E6C84] hover:text-[#091E42] py-1">
                Back
              </button>
            </form>
          )}

          <div className="mt-10 pt-6 border-t border-[#DFE1E6] text-xs text-[#5E6C84] flex items-start gap-2">
            <ShieldCheck className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            <span>Phone + OTP + Password. The same credentials work in the Trata Provider App. All sign-ins are logged.</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function SubmitBtn({ children, loading, testid }) {
  return (
    <button
      data-testid={testid}
      type="submit"
      disabled={loading}
      className="w-full flex items-center justify-center gap-2 bg-[#0052CC] hover:bg-[#0747A6] text-white py-2.5 rounded-md font-semibold text-sm transition-colors disabled:opacity-60"
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : children}
    </button>
  );
}

function DemoCreds() {
  return (
    <div className="mt-6 p-3 bg-[#F8F9FA] border border-dashed border-[#DFE1E6] rounded-md text-[11px] text-[#42526E] leading-relaxed">
      <div className="font-semibold text-[#091E42] mb-1">Demo accounts (OTP: 123456):</div>
      <ul className="space-y-0.5 font-mono">
        <li>9873117605 · Master admin (set pw)</li>
        <li>9000020001 · Hospital owner · <span className="text-[#091E42]">Trata@123</span></li>
        <li>9000020002 · Clinic doctor · <span className="text-[#091E42]">Trata@123</span></li>
        <li>9000020003 · Ambulance owner · <span className="text-[#091E42]">Trata@123</span></li>
        <li>9000020004 · Path lab owner · <span className="text-[#091E42]">Trata@123</span></li>
      </ul>
    </div>
  );
}
