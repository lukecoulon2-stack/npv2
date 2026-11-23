import { formatDate } from "./calendar.js";
import { api, toast } from "./ui.js";

const storageKey = "tempo.reminder-client";
let sessionClient;
let registration;
let registerFailed = false;
let polling = false;

function randomClient() {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
    return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join("-");
}

function browserClient() {
    try {
        const current = localStorage.getItem(storageKey);
        if (current && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(current)) {
            return current;
        }
        sessionClient ??= randomClient();
        localStorage.setItem(storageKey, sessionClient);
        return sessionClient;
    } catch {
        sessionClient ??= randomClient();
        return sessionClient;
    }
}

export function notificationStatus() {
    if (!window.isSecureContext) {
        return { label: "Notifications système disponibles avec HTTPS. Les rappels s’affichent ici.", canEnable: false };
    }
    if (!("Notification" in window) || !("serviceWorker" in navigator) || registerFailed) {
        return { label: "Les rappels s’affichent dans Naoning sur ce navigateur.", canEnable: false };
    }
    if (Notification.permission === "granted") {
        return { label: "Notifications autorisées pendant que Naoning est ouvert.", canEnable: false };
    }
    if (Notification.permission === "denied") {
        return { label: "Notifications bloquées par le navigateur. Les rappels s’affichent dans Naoning.", canEnable: false };
    }
    return { label: "Les rappels s’affichent dans Naoning. Vous pouvez aussi activer les notifications système.", canEnable: true };
}

export async function enableNotifications() {
    if (notificationStatus().canEnable) await Notification.requestPermission();
}

async function showReminder(item, openEvent) {
    const date = formatDate(item.day, { day: "numeric", month: "short" });
    const when = item.start_time ? `${date} · ${item.start_time}` : date;
    if (registration?.active && window.Notification?.permission === "granted") {
        try {
            await registration.showNotification("Rappel Naoning", {
                body: `${item.title} · ${when}`,
                icon: "/static/tempo-192.png",
                tag: `tempo-${item.id}-${item.remind_at}`,
                data: { id: item.id },
            });
            return;
        } catch {
            // The browser may allow notifications only in an installed web app.
        }
    }
    toast(`Rappel · ${item.title} · ${when}`, () => openEvent(item.id));
}

export function startReminders(openEvent) {
    if (window.isSecureContext && "serviceWorker" in navigator) {
        navigator.serviceWorker.register("/service-worker.js")
            .then(() => navigator.serviceWorker.ready)
            .then(worker => { registration = worker; })
            .catch(() => { registerFailed = true; })
            .finally(() => window.dispatchEvent(new Event("tempo:notification-state")));
    }

    async function poll() {
        if (polling) return;
        polling = true;
        try {
            const reminders = await api("/reminders", "POST", { client: browserClient() });
            for (const item of reminders) await showReminder(item, openEvent);
        } catch {
            // Retry at the next interval or when connectivity returns.
        } finally {
            polling = false;
        }
    }
    window.setInterval(poll, 25_000);
    window.addEventListener("online", poll);
    window.addEventListener("tempo:event-saved", poll);
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) poll();
        window.dispatchEvent(new Event("tempo:notification-state"));
    });
    poll();
}
