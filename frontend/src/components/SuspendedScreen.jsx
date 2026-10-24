import React, { useEffect } from "react";
import { ShieldOff, LogOut } from "lucide-react";
import api from "../lib/api";
import { useAuth } from "../lib/auth";

export default function SuspendedScreen() {
  const { user, logout } = useAuth();
  useEffect(() => {
    const id = setInterval(() => {
      api.get("/auth/me").then(({ data }) => {
        if (!data.user.suspended) { localStorage.setItem("trata_user", JSON.stringify(data.user)); window.location.reload(); }
      }).catch(() => {});
    }, 60000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="min-h-screen bg-[#F4F5F7] grid place-items-center p-4" data-testid="suspended-screen">
      <div className="max-w-lg w-full bg-white border border-[#FFBDAD] rounded-lg shadow-sm overflow-hidden">
        <div className="h-1.5 bg-[#DE350B]" />
        <div className="p-6 sm:p-8">
          <img src="/brand/trata-doc-logo.png" alt="Trata Health" className="h-12 mb-6" />
          <div className="flex items-center gap-2 text-[#BF2600]">
            <ShieldOff className="h-5 w-5" />
            <h1 className="font-heading text-xl font-black" data-testid="suspended-title">Your account has been suspended</h1>
          </div>
          <p className="text-sm text-[#42526E] mt-3 leading-relaxed">
            {user?.name ? <b>{user.name}</b> : "This account"} can't use the Trata CRM, the Trata Provider app or TrataX until the suspension is lifted.
          </p>
          {user?.suspended_reason && (
            <div className="mt-4 bg-[#FFF4E5] border-l-4 border-[#FF8B00] px-4 py-3 text-sm text-[#172B4D]" data-testid="suspended-reason">
              <div className="text-[10px] uppercase tracking-wider font-bold text-[#974F0C] mb-0.5">Reason</div>
              {user.suspended_reason}
            </div>
          )}
          {user?.suspended_at && <p className="text-[11px] text-[#5E6C84] mt-3">Suspended on {new Date(user.suspended_at).toLocaleString()}</p>}
          <p className="text-xs text-[#5E6C84] mt-4">If you think this is a mistake, contact your Trata relationship manager. This page refreshes on its own once access is restored.</p>
          <button onClick={logout} className="mt-6 inline-flex items-center gap-2 px-3 py-2 text-sm border border-[#DFE1E6] rounded-md hover:bg-[#F8F9FA]" data-testid="suspended-logout">
            <LogOut className="h-4 w-4" /> Sign out
          </button>
        </div>
      </div>
    </div>
  );
}
