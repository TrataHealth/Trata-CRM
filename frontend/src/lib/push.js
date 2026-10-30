import api from "./api";

export const ALERT_KINDS = [
  { key: "kyc", label: "New KYC submitted for review" },
  { key: "signup", label: "New patient or provider sign-up" },
  { key: "order", label: "New medicine order or booking" },
  { key: "sos", label: "New emergency / SOS case" },
  { key: "access", label: "New provider access request" },
];

export const pushSupported = () => typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

const toBytes = (b64) => {
  const raw = atob((b64 + "=".repeat((4 - (b64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
};

async function registration() {
  const existing = await navigator.serviceWorker.getRegistration("/");
  if (existing) return existing;
  await navigator.serviceWorker.register(process.env.NODE_ENV === "production" ? "/service-worker.js" : "/push-sw.js", { scope: "/" });
  return navigator.serviceWorker.ready;
}

export async function currentSubscription() {
  if (!pushSupported()) return null;
  const reg = await navigator.serviceWorker.getRegistration("/");
  return reg ? reg.pushManager.getSubscription() : null;
}

export async function enablePush(prefs) {
  if (!pushSupported()) throw new Error("This browser can't receive push alerts. On iPhone, add the console to your Home Screen first.");
  const perm = await Notification.requestPermission();
  if (perm !== "granted") throw new Error("Notifications are blocked for this site — allow them in your browser settings.");
  const reg = await registration();
  const { data } = await api.get("/admin/alerts/public-key");
  const sub = (await reg.pushManager.getSubscription()) || await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: toBytes(data.public_key) });
  await api.post("/admin/alerts/subscribe", { subscription: sub.toJSON(), prefs, user_agent: navigator.userAgent });
  return sub;
}

export async function disablePush() {
  const sub = await currentSubscription();
  if (!sub) return;
  await api.post("/admin/alerts/unsubscribe", { endpoint: sub.endpoint }).catch(() => {});
  await sub.unsubscribe();
}

export const soundOn = () => localStorage.getItem("trata_alert_sound") !== "off";
export const setSound = (on) => localStorage.setItem("trata_alert_sound", on ? "on" : "off");

export function playChime(urgent = false) {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const notes = urgent ? [880, 660, 880, 660] : [660, 880];
    notes.forEach((f, i) => {
      const o = ctx.createOscillator(); const g = ctx.createGain();
      o.type = "sine"; o.frequency.value = f; o.connect(g); g.connect(ctx.destination);
      const t = ctx.currentTime + i * 0.18;
      g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.35, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.16);
      o.start(t); o.stop(t + 0.17);
    });
    setTimeout(() => ctx.close(), 1200);
  } catch { /* audio unavailable */ }
}
