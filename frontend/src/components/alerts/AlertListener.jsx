import React, { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { playChime, soundOn, pushSupported } from "../../lib/push";

/** While the console is open: chime + toast for every push the service worker receives. */
export function AlertListener() {
  const nav = useNavigate();
  useEffect(() => {
    if (!pushSupported()) return;
    const onMsg = (e) => {
      if (e.data?.type !== "trata-alert") return;
      if (soundOn()) playChime(!!e.data.urgent);
      toast(e.data.title, { description: e.data.body, action: e.data.url ? { label: "Open", onClick: () => nav(e.data.url) } : undefined });
    };
    navigator.serviceWorker.addEventListener("message", onMsg);
    return () => navigator.serviceWorker.removeEventListener("message", onMsg);
  }, [nav]);
  return null;
}
