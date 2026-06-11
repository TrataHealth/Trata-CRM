import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { ShieldCheck, Mail, Loader2, ArrowRight } from "lucide-react";

/**
 * Forced setup of recovery email + 2 security questions.
 * Shown automatically on first login (or whenever user.security_setup_required is true).
 * Props: { onComplete?: () => void } — if rendered as a route, falls back to navigate('/')
 */
export default function SecuritySetup({ onComplete }) {
  const navigate = useNavigate();
  const { user, refresh } = useAuth();
  const [questions, setQuestions] = useState([]);
  const [email, setEmail] = useState("");
  const [pick1, setPick1] = useState("");
  const [pick2, setPick2] = useState("");
  const [ans1, setAns1] = useState("");
  const [ans2, setAns2] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.get("/auth/security-questions").then((r) => setQuestions(r.data.items));
  }, []);

  const finish = () => {
    if (onComplete) onComplete();
    else navigate(user?.role === "provider_owner" ? "/provider" : user?.role === "sales_rep" ? "/agent" : "/");
  };

  const submit = async (e) => {
    e?.preventDefault();
    setErr("");
    if (!email.trim()) return setErr("Enter your recovery email");
    if (!pick1 || !pick2) return setErr("Pick two security questions");
    if (pick1 === pick2) return setErr("Pick two different questions");
    if (ans1.trim().length < 2 || ans2.trim().length < 2) return setErr("Answers must be at least 2 characters");
    setSaving(true);
    try {
      await api.post("/auth/security-setup", {
        recovery_email: email.trim(),
        questions: [
          { question_id: pick1, answer: ans1 },
          { question_id: pick2, answer: ans2 },
        ],
      });
      // Refresh stored user so security_setup_required flips to false
      if (refresh) await refresh();
      finish();
    } catch (e) {
      setErr(e?.response?.data?.detail || "Could not save");
    }
    setSaving(false);
  };

  const options2 = questions.filter((q) => q.id !== pick1);
  const options1 = questions.filter((q) => q.id !== pick2);

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#F4F5F7] p-6" data-testid="security-setup-page">
      <div className="w-full max-w-lg bg-white border border-[#DFE1E6] rounded-lg shadow-sm p-8">
        <div className="flex items-center gap-2 mb-6">
          <img src="/brand/shield.png" alt="" className="h-9 w-9 object-contain" />
          <div>
            <div className="font-heading font-bold text-[#091E42] leading-none">Trata Health</div>
            <div className="text-[10px] text-[#5E6C84] tracking-wider uppercase mt-0.5">CRM · Account security</div>
          </div>
        </div>
        <div className="overline mb-1">One-time setup</div>
        <h2 className="font-heading text-2xl font-bold tracking-tight text-[#091E42] mb-1">Secure your account</h2>
        <p className="text-sm text-[#5E6C84] mb-6">Add a recovery email and two security questions. You&apos;ll use these if you ever forget your password.</p>

        <form onSubmit={submit} className="space-y-4">
          <label className="block">
            <span className="overline flex items-center gap-1.5"><Mail className="h-3 w-3" /> Recovery email</span>
            <input
              data-testid="ss-email-input"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="mt-2 w-full px-3 py-2.5 text-sm border border-[#DFE1E6] rounded-md focus:border-[#4C9AFF] outline-none"
            />
            <div className="text-[11px] text-[#5E6C84] mt-1">We&apos;ll send your reset code here.</div>
          </label>

          {[1, 2].map((n) => (
            <div key={n} className="space-y-2 p-3 border border-[#DFE1E6] rounded-md bg-[#FAFBFC]">
              <div className="overline">Question {n}</div>
              <select
                data-testid={`ss-pick-${n}`}
                value={n === 1 ? pick1 : pick2}
                onChange={(e) => (n === 1 ? setPick1(e.target.value) : setPick2(e.target.value))}
                className="w-full px-3 py-2 text-sm bg-white border border-[#DFE1E6] rounded-md focus:border-[#4C9AFF] outline-none"
              >
                <option value="">— Choose a question —</option>
                {(n === 1 ? options1 : options2).map((q) => (
                  <option key={q.id} value={q.id}>{q.text}</option>
                ))}
              </select>
              <input
                data-testid={`ss-ans-${n}`}
                value={n === 1 ? ans1 : ans2}
                onChange={(e) => (n === 1 ? setAns1(e.target.value) : setAns2(e.target.value))}
                placeholder="Your answer (case-insensitive)"
                className="w-full px-3 py-2 text-sm border border-[#DFE1E6] rounded-md focus:border-[#4C9AFF] outline-none"
              />
            </div>
          ))}

          {err && <div className="text-sm text-[#FF5630]" data-testid="ss-error">{err}</div>}

          <button
            data-testid="ss-submit-btn"
            type="submit"
            disabled={saving}
            className="w-full flex items-center justify-center gap-2 bg-[#0052CC] hover:bg-[#0747A6] text-white py-2.5 rounded-md font-semibold text-sm transition-colors disabled:opacity-60"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
            Save & continue <ArrowRight className="h-4 w-4" />
          </button>
        </form>
      </div>
    </div>
  );
}
