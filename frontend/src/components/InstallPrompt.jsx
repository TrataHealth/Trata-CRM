import React from "react";
import { Download, X, Share, Plus } from "lucide-react";

const DISMISS_KEY = "trata_pwa_dismissed_at";
const DISMISS_DAYS = 7;

function isStandalone() {
  return (
    window.matchMedia?.("(display-mode: standalone)").matches ||
    window.navigator.standalone === true
  );
}

function isIos() {
  const ua = window.navigator.userAgent;
  return /iPad|iPhone|iPod/.test(ua) && !window.MSStream;
}

function recentlyDismissed() {
  const t = parseInt(localStorage.getItem(DISMISS_KEY) || "0", 10);
  if (!t) return false;
  return Date.now() - t < DISMISS_DAYS * 24 * 60 * 60 * 1000;
}

export default function InstallPrompt() {
  const [deferred, setDeferred] = React.useState(null);
  const [show, setShow] = React.useState(false);
  const [iosTip, setIosTip] = React.useState(false);

  React.useEffect(() => {
    if (isStandalone()) return;
    if (recentlyDismissed()) return;

    const onBeforeInstall = (e) => {
      e.preventDefault();
      setDeferred(e);
      setShow(true);
    };
    window.addEventListener("beforeinstallprompt", onBeforeInstall);

    // iOS Safari doesn't fire beforeinstallprompt — show our own tip after 8s
    let iosTimer;
    if (isIos()) {
      iosTimer = setTimeout(() => setShow(true), 8000);
    }

    const onInstalled = () => {
      setShow(false);
      setDeferred(null);
    };
    window.addEventListener("appinstalled", onInstalled);

    return () => {
      window.removeEventListener("beforeinstallprompt", onBeforeInstall);
      window.removeEventListener("appinstalled", onInstalled);
      if (iosTimer) clearTimeout(iosTimer);
    };
  }, []);

  const dismiss = () => {
    localStorage.setItem(DISMISS_KEY, String(Date.now()));
    setShow(false);
    setIosTip(false);
  };

  const install = async () => {
    if (deferred) {
      deferred.prompt();
      try {
        await deferred.userChoice;
      } catch {}
      setDeferred(null);
      setShow(false);
    } else if (isIos()) {
      setIosTip(true);
    }
  };

  if (!show) return null;

  return (
    <>
      {/* Banner */}
      {!iosTip && (
        <div className="fixed bottom-4 left-4 right-4 lg:left-auto lg:right-6 lg:bottom-6 lg:w-[380px] z-[60] bg-white border border-[#DFE1E6] rounded-lg shadow-xl p-4 flex items-start gap-3 animate-in fade-in slide-in-from-bottom-4"
          data-testid="pwa-install-banner"
        >
          <img src="/brand/shield.png" alt="" className="h-10 w-10 object-contain shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="text-sm font-heading font-bold text-[#091E42]">Install Trata Health CRM</div>
            <div className="text-xs text-[#5E6C84] mt-0.5 leading-snug">
              Add to your home screen for one-tap access, full-screen view and faster loads.
            </div>
            <div className="mt-3 flex gap-2">
              <button
                data-testid="pwa-install-btn"
                onClick={install}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-[#0052CC] hover:bg-[#0747A6] text-white rounded-md"
              >
                <Download className="h-3.5 w-3.5" /> Install app
              </button>
              <button
                data-testid="pwa-dismiss-btn"
                onClick={dismiss}
                className="px-3 py-1.5 text-xs font-semibold text-[#5E6C84] hover:bg-[#F1F2F4] rounded-md"
              >
                Not now
              </button>
            </div>
          </div>
          <button
            onClick={dismiss}
            aria-label="Close"
            className="p-1 text-[#5E6C84] hover:text-[#091E42]"
            data-testid="pwa-close-btn"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* iOS share-sheet instructions */}
      {iosTip && (
        <div
          data-testid="pwa-ios-tip"
          className="fixed inset-0 z-[70] flex items-end justify-center p-4 bg-black/40"
          onClick={dismiss}
        >
          <div
            className="w-full max-w-md bg-white rounded-lg p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-3">
              <img src="/brand/shield.png" alt="" className="h-10 w-10 object-contain shrink-0" />
              <div className="flex-1">
                <div className="font-heading text-base font-bold text-[#091E42]">Add to Home Screen</div>
                <div className="text-xs text-[#5E6C84] mt-1">Install Trata Health CRM on your iPhone/iPad in two taps.</div>
              </div>
              <button onClick={dismiss} aria-label="Close" className="p-1 text-[#5E6C84]"><X className="h-4 w-4" /></button>
            </div>
            <ol className="mt-4 space-y-3 text-sm text-[#091E42]">
              <li className="flex items-center gap-2">
                <span className="h-6 w-6 rounded-full bg-[#F1F2F4] flex items-center justify-center text-xs font-bold">1</span>
                <span className="flex-1">Tap the <span className="font-semibold">Share</span> button in Safari</span>
                <Share className="h-4 w-4 text-[#0052CC]" />
              </li>
              <li className="flex items-center gap-2">
                <span className="h-6 w-6 rounded-full bg-[#F1F2F4] flex items-center justify-center text-xs font-bold">2</span>
                <span className="flex-1">Scroll down and tap <span className="font-semibold">Add to Home Screen</span></span>
                <Plus className="h-4 w-4 text-[#0052CC]" />
              </li>
              <li className="flex items-center gap-2">
                <span className="h-6 w-6 rounded-full bg-[#F1F2F4] flex items-center justify-center text-xs font-bold">3</span>
                <span className="flex-1">Tap <span className="font-semibold">Add</span> — TrataCRM is now on your home screen.</span>
              </li>
            </ol>
          </div>
        </div>
      )}
    </>
  );
}
