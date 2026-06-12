import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import api from "../lib/api";
import { ShieldCheck, ArrowRight, Loader2, KeyRound, Mail, Lock, Eye, EyeOff } from "lucide-react";

export default function ForgotPassword() {
  const navigate = useNavigate();
  const [step, setStep] = useState("phone");
  const [phone, setPhone] = useState("");
  const [info, setInfo] = useState(null);    // {name, recovery_email_masked, questions[]}
  const [answers, setAnswers] = useState({}); // {question_id: text}
  const [code, setCode] = useState("");
  const [devCode, setDevCode] = useState(null);
  const [newPassword, setNewPassword] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [emailMasked, setEmailMasked] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [notice, setNotice] = useState("");

  const startForgot = async (e) => {
    e?.preventDefault();
    setErr(""); setNotice("");
    if (phone.length < 10) return setErr("Enter a valid 10-digit phone");
    setLoading(true);
    try {
      const { data } = await api.post("/auth/forgot/start", { phone });
      if (!data.ok) {
        setErr(data.message || "Recovery not available for this account.");
      } else {
        setInfo(data);
        setEmailMasked(data.recovery_email_masked);
        setStep("questions");
      }
    } catch (e) {
      setErr(e?.response?.data?.detail || "Could not start recovery");
    }
    setLoading(false);
  };

  const submitAnswers = async (e) => {
    e?.preventDefault();
    setErr(""); setNotice(""); setDevCode(null);
    const a = info.questions.map((q) => ({ question_id: q.id, answer: answers[q.id] || "" }));
    if (a.every((x) => !x.answer.trim())) return setErr("Answer at least one question");
    setLoading(true);
    try {
      const { data } = await api.post("/auth/forgot/request-code", { phone, answers: a });
      setEmailMasked(data.recovery_email_masked || emailMasked);
      if (data.email_sent) {
        setNotice(`A 6-digit code was emailed to ${data.recovery_email_masked}. It expires in ${data.expires_in_minutes} minutes.`);
      } else {
        setDevCode(data.dev_code || null);
        setNotice(
          data.dev_code
            ? `Email service is in test mode — copy the code below directly. (To send to real inboxes, verify a domain at resend.com/domains.)`
            : `Code was generated but email delivery failed. Try again or contact your admin.`
        );
      }
      setStep("reset");
    } catch (e) {
      setErr(e?.response?.data?.detail || "Could not verify your answers");
    }
    setLoading(false);
  };

  const submitReset = async (e) => {
    e?.preventDefault();
    setErr(""); setNotice("");
    if (code.length !== 6) return setErr("Enter the 6-digit code");
    if (newPassword.length < 6) return setErr("Password must be at least 6 characters");
    setLoading(true);
    try {
      await api.post("/auth/forgot/reset", { phone, code, new_password: newPassword });
      setNotice("Password reset. Redirecting to sign-in…");
      setTimeout(() => navigate("/login"), 1200);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Could not reset password");
    }
    setLoading(false);
  };

  const titles = {
    phone: { kicker: "Step 1 of 3", title: "Forgot your password?", sub: "Enter your registered phone to start recovery." },
    questions: { kicker: "Step 2 of 3", title: "Quick security check", sub: `Answer at least one question to receive a code at ${emailMasked}.` },
    reset: { kicker: "Step 3 of 3", title: "Enter code & new password", sub: `A 6-digit code was sent to ${emailMasked}.` },
  };
  const t = titles[step];

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#F4F5F7] p-6" data-testid="forgot-page">
      <div className="w-full max-w-md bg-white border border-[#DFE1E6] rounded-lg shadow-sm p-8">
        <div className="flex items-center gap-2 mb-6">
          <img src="/brand/shield.png" alt="" className="h-9 w-9 object-contain" />
          <div>
            <div className="font-heading font-bold text-[#091E42] leading-none">Trata Health</div>
            <div className="text-[10px] text-[#5E6C84] tracking-wider uppercase mt-0.5">CRM · Account recovery</div>
          </div>
        </div>

        <div className="overline mb-1">{t.kicker}</div>
        <h2 className="font-heading text-2xl font-bold tracking-tight text-[#091E42] mb-1">{t.title}</h2>
        <p className="text-sm text-[#5E6C84] mb-6">{t.sub}</p>

        {step === "phone" && (
          <form onSubmit={startForgot} className="space-y-4">
            <label className="block">
              <span className="overline">Phone Number</span>
              <div className="mt-2 flex">
                <span className="px-3 inline-flex items-center bg-[#F1F2F4] border border-r-0 border-[#DFE1E6] rounded-l-md text-sm text-[#091E42] font-medium">+91</span>
                <input
                  data-testid="fp-phone-input"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value.replace(/[^0-9]/g, ""))}
                  maxLength={10}
                  placeholder="9000000002"
                  className="flex-1 px-3 py-2.5 text-sm bg-white border border-[#DFE1E6] rounded-r-md focus:border-[#4C9AFF] focus:ring-2 focus:ring-[#4C9AFF]/30 outline-none"
                />
              </div>
            </label>
            {err && <div className="text-sm text-[#FF5630]" data-testid="fp-error">{err}</div>}
            <SubmitBtn loading={loading} testid="fp-start-btn">
              Continue <ArrowRight className="h-4 w-4" />
            </SubmitBtn>
          </form>
        )}

        {step === "questions" && info && (
          <form onSubmit={submitAnswers} className="space-y-4">
            {info.questions.map((q) => (
              <label key={q.id} className="block">
                <span className="overline">{q.text}</span>
                <input
                  data-testid={`fp-answer-${q.id}`}
                  value={answers[q.id] || ""}
                  onChange={(e) => setAnswers({ ...answers, [q.id]: e.target.value })}
                  className="mt-2 w-full px-3 py-2 text-sm border border-[#DFE1E6] rounded-md focus:border-[#4C9AFF] outline-none"
                  placeholder="Your answer"
                />
              </label>
            ))}
            <div className="text-[11px] text-[#5E6C84]">Only one correct answer is needed to proceed.</div>
            {err && <div className="text-sm text-[#FF5630]" data-testid="fp-error">{err}</div>}
            <SubmitBtn loading={loading} testid="fp-answers-btn">
              <Mail className="h-4 w-4" /> Send code
            </SubmitBtn>
            <button type="button" onClick={() => setStep("phone")} className="w-full text-xs text-[#5E6C84] hover:text-[#091E42] py-1">Use a different phone</button>
          </form>
        )}

        {step === "reset" && (
          <form onSubmit={submitReset} className="space-y-4">
            {notice && (
              <div className="text-sm bg-[#DEEBFF] border border-[#0052CC]/20 text-[#0747A6] rounded-md p-3" data-testid="fp-notice">
                {notice}
                {devCode && (
                  <div className="mt-2 font-mono font-bold text-lg tracking-[0.4em] text-center bg-white border border-dashed border-[#0052CC]/40 rounded p-2" data-testid="fp-dev-code">
                    {devCode}
                  </div>
                )}
              </div>
            )}
            <label className="block">
              <span className="overline">6-digit code</span>
              <input
                data-testid="fp-code-input"
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/[^0-9]/g, ""))}
                maxLength={6}
                placeholder="123456"
                className="mt-2 w-full px-3 py-2.5 text-lg tracking-[0.5em] text-center font-mono bg-white border border-[#DFE1E6] rounded-md focus:border-[#4C9AFF] focus:ring-2 focus:ring-[#4C9AFF]/30 outline-none"
              />
            </label>
            <label className="block">
              <span className="overline">New password</span>
              <div className="mt-2 relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#5E6C84]" />
                <input
                  data-testid="fp-newpass-input"
                  type={showPwd ? "text" : "password"}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="Choose a new password"
                  className="pl-9 pr-11 w-full px-3 py-2.5 text-sm bg-white border border-[#DFE1E6] rounded-md focus:border-[#4C9AFF] outline-none"
                />
                <button
                  type="button"
                  onClick={() => setShowPwd((v) => !v)}
                  aria-label={showPwd ? "Hide password" : "Show password"}
                  data-testid="fp-newpass-toggle"
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-[#5E6C84] hover:text-[#091E42] rounded"
                  tabIndex={-1}
                >
                  {showPwd ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </label>
            {err && <div className="text-sm text-[#FF5630]" data-testid="fp-error">{err}</div>}
            <SubmitBtn loading={loading} testid="fp-reset-btn">
              <KeyRound className="h-4 w-4" /> Reset password
            </SubmitBtn>
            <button type="button" onClick={() => setStep("questions")} className="w-full text-xs text-[#5E6C84] hover:text-[#091E42] py-1">Back</button>
          </form>
        )}

        <div className="mt-8 pt-6 border-t border-[#DFE1E6] text-xs text-[#5E6C84] flex items-center justify-between">
          <Link to="/login" className="hover:text-[#091E42] flex items-center gap-1" data-testid="fp-back-login"><ShieldCheck className="h-3.5 w-3.5" /> Back to sign in</Link>
          <span className="text-[10px]">All actions are logged</span>
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
