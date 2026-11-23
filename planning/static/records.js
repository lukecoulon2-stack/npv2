import { capitalize, formatDate, renderCalendar } from "./calendar.js";
import { enableNotifications, notificationStatus } from "./reminders.js";
import {
    activeSheet, api, closeSheet, colorDot, confirmDelete, empty, errorBlock, escapeHtml, field,
    formError, icon, input, pageHeading, safeColor, sheet, submitForm, textarea, toast,
} from "./ui.js";

const DATE = 'type="date" min="0001-01-01" max="9999-12-31"';
const REMINDER_OPTIONS = [
    ["", "Aucun rappel"], [0, "À l’heure de l’événement"], [5, "5 minutes avant"], [15, "15 minutes avant"],
    [30, "30 minutes avant"], [60, "1 heure avant"], [120, "2 heures avant"],
    [1440, "1 jour avant"], [10080, "1 semaine avant"],
];

function eventTime(event) {
    if (!event.start_time) return "Toute la journée";
    return event.end_time ? `${event.start_time} – ${event.end_time}` : event.start_time;
}

function dateTitle(day) {
    return capitalize(formatDate(day));
}

function eventRow(item) {
    return `<button type="button" class="event-row" data-event="${item.id}" style="--item-color:${safeColor(item.color)}">
        <span class="event-stripe" aria-hidden="true"></span><span class="row-copy">
        <strong>${escapeHtml(item.title)}</strong><span class="small muted">${eventTime(item)}${item.location ? ` · ${escapeHtml(item.location)}` : ""}</span>
        </span>${item.reminder_minutes !== null ? icon("bell") : ""}${icon("right")}</button>`;
}

function eventGroups(events) {
    const groups = new Map();
    for (const event of events) {
        if (!groups.has(event.day)) groups.set(event.day, []);
        groups.get(event.day).push(event);
    }
    return `<div class="event-groups">${Array.from(groups, ([day, items]) => `<div>
        <h3 class="event-day">${dateTitle(day)}</h3><div class="row-list">${items.map(eventRow).join("")}</div>
    </div>`).join("")}</div>`;
}

export function renderEvents(host, session, position, initialId) {
    host.innerHTML = pageHeading(
        "Mes événements", "event", "tone-events",
        `<button class="button primary" type="button" data-new-event>${icon("plus")} Ajouter</button>`,
    ) + `<div class="calendar-host"></div>
        <section class="view-section" aria-labelledby="event-list-title"><div class="section-heading"><h2 id="event-list-title">Événements de la période</h2></div>
        <div class="event-list"></div></section>
        <section class="view-section section-panel panel stack" data-notifications>
            <h2>Notifications</h2><p class="muted" data-notification-text></p>
            <div data-notification-action hidden><button type="button" class="button secondary" data-enable>
                ${icon("bell")} Activer les notifications</button></div>${formError}
        </section>`;
    const eventList = host.querySelector(".event-list");
    const notifications = host.querySelector("[data-notifications]");
    const calendar = renderCalendar(host.querySelector(".calendar-host"), "events", position, {
        today: session.today,
        timezone: session.timezone,
        onLoading: () => { eventList.innerHTML = ""; },
        onLoaded: (items, range) => {
            const visible = range.firstInView
                ? items.filter(item => item.day >= range.firstInView && item.day <= range.lastInView)
                : items;
            eventList.innerHTML = visible.length ? eventGroups(visible) : empty("Aucun événement prévu");
            attachEvents(eventList);
        },
        onDay: day => openEventDay(day, options),
    });
    const options = {
        refresh: calendar.refresh,
        goTo: calendar.goTo,
        open: id => openEvent(id, options),
    };
    function attachEvents(container) {
        container.querySelectorAll("[data-event]").forEach(button => {
            button.onclick = () => options.open(Number(button.dataset.event));
        });
    }
    host.querySelector("[data-new-event]").onclick = () => editEvent(null, position.day, options);
    const enable = notifications.querySelector("[data-enable]");
    function updateStatus() {
        const current = notificationStatus();
        notifications.querySelector("[data-notification-text]").textContent = current.label;
        notifications.querySelector("[data-notification-action]").hidden = !current.canEnable;
    }
    enable.onclick = async () => {
        const error = notifications.querySelector("[data-error]");
        enable.disabled = true;
        error.hidden = true;
        try {
            await enableNotifications();
        } catch {
            error.textContent = "Le navigateur n’a pas pu activer les notifications.";
            error.hidden = false;
        } finally {
            enable.disabled = false;
            updateStatus();
        }
    };
    window.addEventListener("tempo:notification-state", updateStatus);
    host.addEventListener("tempo:leave", () => window.removeEventListener("tempo:notification-state", updateStatus), { once: true });
    updateStatus();
    if (initialId) options.open(initialId);
}

async function openEventDay(day, options) {
    const title = dateTitle(day);
    const loading = sheet(title, '<p class="empty">Chargement des événements…</p>');
    try {
        const events = await api(`/events?start=${day}&end=${day}`);
        if (!activeSheet(loading)) return;
        const content = sheet(title, `<div class="stack">
            ${events.length ? `<div class="row-list">${events.map(eventRow).join("")}</div>` : '<p class="muted">Aucun événement ce jour.</p>'}
            <div><button type="button" class="button primary" data-new>${icon("plus")} Ajouter un événement</button></div>
        </div>`);
        const back = () => openEventDay(day, options);
        content.querySelector("[data-new]").onclick = () => editEvent(null, day, { ...options, back });
        content.querySelectorAll("[data-event]").forEach(button => {
            button.onclick = () => openEvent(Number(button.dataset.event), { ...options, back });
        });
    } catch (error) {
        if (activeSheet(loading)) sheet(title, errorBlock(error));
    }
}

function remindLabel(minutes) {
    const option = REMINDER_OPTIONS.find(([value]) => value === minutes);
    return option?.[1] ?? `${minutes} minutes avant`;
}

async function openEvent(id, options) {
    const loading = sheet("Événement", '<p class="empty">Chargement…</p>');
    try {
        const item = await api(`/events/${id}`);
        if (!activeSheet(loading)) return;
        const content = sheet(item.title, `<div class="stack">
            <div class="info-block stack">
                <p class="info-line">${icon("calendar")} <span>${dateTitle(item.day)}</span></p>
                <p class="info-line">${icon("clock")} <span>${eventTime(item)}</span></p>
                ${item.location ? `<p class="info-line">${icon("pin")} <span>${escapeHtml(item.location)}</span></p>` : ""}
                ${item.reminder_minutes !== null ? `<p class="info-line">${icon("bell")} <span>${remindLabel(item.reminder_minutes)}</span></p>` : ""}
            </div>
            ${item.note ? `<div><h3 class="detail-subhead">Note</h3><p class="preformatted">${escapeHtml(item.note)}</p></div>` : ""}
            <div class="sheet-actions">
                ${options.back ? '<button type="button" class="button secondary" data-back>Retour</button>' : ""}
                <button type="button" class="button danger" data-delete>Supprimer</button>
                <button type="button" class="button primary" data-edit>${icon("edit")} Modifier</button>
            </div>
        </div>`);
        if (options.back) content.querySelector("[data-back]").onclick = options.back;
        const reopen = () => openEvent(id, options);
        content.querySelector("[data-edit]").onclick = () => editEvent(item, item.day, { ...options, back: reopen });
        content.querySelector("[data-delete]").onclick = () => confirmDelete({
            title: "Supprimer l’événement",
            message: `Placer « ${item.title} » dans la corbeille ?`,
            onCancel: reopen,
            onDelete: async confirmation => {
                await api(`/events/${id}`, "DELETE");
                if (activeSheet(confirmation)) closeSheet();
                options.refresh();
                toast("Événement supprimé.");
            },
        });
    } catch (error) {
        if (activeSheet(loading)) sheet("Événement", errorBlock(error));
    }
}

function editEvent(item, day, options) {
    const reminder = item?.reminder_minutes ?? "";
    const choices = REMINDER_OPTIONS.some(([value]) => value === reminder)
        ? REMINDER_OPTIONS : [...REMINDER_OPTIONS, [reminder, remindLabel(reminder)]];
    const content = sheet(item ? "Modifier l’événement" : "Ajouter un événement", `<form class="stack">
        ${field("Titre", input("title", item?.title, 'required maxlength="120"'))}
        ${field("Date", input("day", day, `${DATE} required`))}
        <div class="fields-two">
            ${field("Heure de début", input("start_time", item?.start_time, 'type="time" step="60"'))}
            ${field("Heure de fin", input("end_time", item?.end_time, 'type="time" step="60"'))}
        </div>
        ${field("Lieu", input("location", item?.location, 'maxlength="200"'))}
        ${field("Note attachée", textarea("note", item?.note, 'rows="3" maxlength="16000"'))}
        <div class="fields-two">
            ${field("Rappel", `<select name="reminder_minutes">${choices.map(([value, text]) =>
                `<option value="${value}" ${reminder === value ? "selected" : ""}>${text}</option>`,
            ).join("")}</select>`)}
            ${field("Couleur", input("color", safeColor(item?.color, "#6389dc"), 'type="color" required'))}
        </div>
        <p class="small muted" data-no-time hidden>Pour un événement sans heure, le rappel prend 9 h comme heure de départ.</p>
        ${formError}
        <div class="sheet-actions">
            ${options.back ? '<button type="button" class="button secondary" data-cancel>Retour</button>' : ""}
            <button type="submit" class="button primary">Enregistrer</button>
        </div>
    </form>`);
    const form = content.querySelector("form");
    const noTime = content.querySelector("[data-no-time]");
    function syncHours() {
        noTime.hidden = !!form.elements.start_time.value || form.elements.reminder_minutes.value === "";
    }
    form.addEventListener("input", syncHours);
    syncHours();
    if (options.back) content.querySelector("[data-cancel]").onclick = options.back;
    submitForm(form, async data => {
        data.reminder_minutes = data.reminder_minutes === "" ? null : Number(data.reminder_minutes);
        await api(item ? `/events/${item.id}` : "/events", item ? "PUT" : "POST", data);
        if (activeSheet(content)) closeSheet();
        options.goTo(data.day);
        toast("Événement enregistré.");
        window.dispatchEvent(new Event("tempo:event-saved"));
    });
}

export function renderNotes(host, timezone, initialId) {
    host.innerHTML = pageHeading(
        "Notes", "note", "tone-notes",
        `<button type="button" class="button primary" data-new-note>${icon("plus")} Ajouter</button>`,
    ) + '<div class="notes-list"></div>';
    const notesList = host.querySelector(".notes-list");
    const formatter = new Intl.DateTimeFormat("fr-FR", {
        dateStyle: "medium", timeStyle: "short", timeZone: timezone,
    });
    const dateTime = stamp => formatter.format(new Date(stamp));
    const refresh = async () => {
        notesList.innerHTML = '<p class="empty">Chargement du bloc-notes…</p>';
        try {
            const notes = await api("/notes");
            if (!notesList.isConnected) return;
            notesList.innerHTML = notes.length ? `<div class="notes-grid">${notes.map(note => `<button type="button"
                class="note-card" data-note="${note.id}" style="--item-color:${safeColor(note.color)}"
                aria-label="Lire la note ${escapeHtml(note.title)}">
                <h2>${colorDot(note.color)} ${escapeHtml(note.title)}</h2>
                <p class="note-preview">${escapeHtml(note.content.slice(0, 320))}</p>
                <span class="muted small">${note.day ? formatDate(note.day, { day: "numeric", month: "short", year: "numeric" }) : dateTime(note.updated_at)}</span>
            </button>`).join("")}</div>` : empty("Aucune note", "Ajoutez une première note à votre bloc-notes.");
            notesList.querySelectorAll("[data-note]").forEach(button => {
                button.onclick = () => openNote(notes.find(note => note.id === Number(button.dataset.note)), dateTime, refresh);
            });
            if (initialId) {
                const selected = notes.find(note => note.id === initialId);
                initialId = null;
                if (selected) openNote(selected, dateTime, refresh);
            }
        } catch (error) {
            notesList.innerHTML = `${errorBlock(error)}<button type="button" class="button secondary" data-retry>Réessayer</button>`;
            notesList.querySelector("[data-retry]").onclick = refresh;
        }
    };
    host.querySelector("[data-new-note]").onclick = () => editNote(null, refresh);
    refresh();
}

function openNote(item, dateTime, refresh) {
    const content = sheet(item.title, `<div class="stack">
        <p class="preformatted">${escapeHtml(item.content)}</p>
        ${item.day || item.people || item.location ? `<div class="info-block stack">
            ${item.day ? `<p class="info-line">${icon("calendar")} <span>${dateTitle(item.day)}</span></p>` : ""}
            ${item.people ? `<p class="info-line">${icon("user")} <span>${escapeHtml(item.people)}</span></p>` : ""}
            ${item.location ? `<p class="info-line">${icon("pin")} <span>${escapeHtml(item.location)}</span></p>` : ""}
        </div>` : ""}
        <p class="small muted">Créée le ${dateTime(item.created_at)}<br>Modifiée le ${dateTime(item.updated_at)}</p>
        <div class="sheet-actions">
            <button type="button" class="button danger" data-delete>Supprimer</button>
            <button type="button" class="button primary" data-edit>${icon("edit")} Modifier</button>
        </div>
    </div>`);
    const reopen = () => openNote(item, dateTime, refresh);
    content.querySelector("[data-edit]").onclick = () => editNote(item, refresh, reopen);
    content.querySelector("[data-delete]").onclick = () => confirmDelete({
        title: "Supprimer la note", message: `Placer « ${item.title} » dans la corbeille ?`, onCancel: reopen,
        onDelete: async confirmation => {
            await api(`/notes/${item.id}`, "DELETE");
            if (activeSheet(confirmation)) closeSheet();
            refresh();
            toast("Note supprimée.");
        },
    });
}

function editNote(item, refresh, back) {
    const content = sheet(item ? "Modifier la note" : "Ajouter une note", `<form class="stack">
        ${field("Titre", input("title", item?.title, 'required maxlength="120"'))}
        ${field("Contenu", textarea("content", item?.content, 'required rows="5" maxlength="16000"'))}
        <div class="fields-two">
            ${field("Date associée", input("day", item?.day, DATE))}
            ${field("Couleur", input("color", safeColor(item?.color, "#e39161"), 'type="color" required'))}
        </div>
        ${field("Personnes", input("people", item?.people, 'maxlength="200"'))}
        ${field("Lieu", input("location", item?.location, 'maxlength="200"'))}
        ${formError}
        <div class="sheet-actions">
            ${back ? '<button class="button secondary" type="button" data-back>Retour</button>' : ""}
            <button type="submit" class="button primary">Enregistrer</button>
        </div>
    </form>`);
    if (back) content.querySelector("[data-back]").onclick = back;
    submitForm(content.querySelector("form"), async data => {
        await api(item ? `/notes/${item.id}` : "/notes", item ? "PUT" : "POST", data);
        if (activeSheet(content)) closeSheet();
        toast("Note enregistrée.");
        refresh();
    });
}
