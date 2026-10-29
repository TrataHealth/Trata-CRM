/* Trata Admin Console — push alerts for master admins (imported by service-worker.js, registered alone in dev). */
self.addEventListener('push', (event) => {
  let d = {};
  try { d = event.data ? event.data.json() : {}; } catch (e) { d = { title: 'Admin alert', body: event.data ? event.data.text() : '' }; }
  const title = d.title || 'Admin alert';
  const opts = {
    body: d.body || '',
    icon: '/icons/icon-192.png',
    badge: '/icons/icon-192.png',
    tag: d.tag || 'trata-alert',
    renotify: true,
    silent: false,
    requireInteraction: !!d.urgent,
    vibrate: d.urgent ? [300, 100, 300, 100, 300] : [200, 100, 200],
    data: { url: d.url || '/' },
  };
  event.waitUntil(Promise.all([
    self.registration.showNotification(title, opts),
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((cs) => cs.forEach((c) => c.postMessage({ type: 'trata-alert', ...d }))),
  ]));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = new URL((event.notification.data && event.notification.data.url) || '/', self.location.origin).href;
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((cs) => {
    const c = cs.find((x) => x.url.startsWith(self.location.origin));
    if (c) { return c.focus().then(() => c.navigate(url)); }
    return self.clients.openWindow(url);
  }));
});

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
