self.addEventListener('push', (event) => {
  if (!event.data) return;
  const notice = event.data.json();
  const url = new URL(notice.url || '/lk', self.location.origin);
  if (url.origin !== self.location.origin || url.pathname !== '/lk') return;
  event.waitUntil(self.registration.showNotification(notice.title, {
    body: notice.body,
    icon: '/assets/account-pwa-512.png',
    tag: notice.tag,
    data: {url:url.href},
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = new URL(event.notification.data?.url || '/lk', self.location.origin);
  if (url.origin !== self.location.origin || url.pathname !== '/lk') return;
  event.waitUntil(clients.openWindow(url.href));
});
