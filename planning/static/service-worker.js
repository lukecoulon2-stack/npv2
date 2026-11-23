self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", event => event.waitUntil(self.clients.claim()));

self.addEventListener("notificationclick", event => {
    event.notification.close();
    const id = event.notification.data?.id;
    const url = id ? `/evenements?event=${encodeURIComponent(id)}` : "/evenements";
    event.waitUntil((async () => {
        const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
        for (const client of windows) {
            if (new URL(client.url).origin === self.location.origin && "focus" in client) {
                const page = await client.navigate(url);
                if (page) return page.focus();
            }
        }
        return self.clients.openWindow(url);
    })());
});
