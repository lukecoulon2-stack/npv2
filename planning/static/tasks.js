import { capitalize, formatDate } from "./calendar.js";
import {
    activeSheet, api, closeSheet, confirmDelete, empty, errorBlock, escapeHtml, field,
    formError, icon, input, pageHeading, sheet, submitForm, textarea, toast,
} from "./ui.js";

function taskRow(task) {
    const done = !!task.completed_at;
    return `<li class="task-row ${done ? "task-done" : ""}">
        <input type="checkbox" data-task-check="${task.id}" ${done ? "checked" : ""}
            aria-label="${done ? "Rouvrir" : "Terminer"} ${escapeHtml(task.title)}">
        <button type="button" class="task-detail" data-task="${task.id}">
            <span class="row-copy"><strong>${escapeHtml(task.title)}</strong>
                <span class="muted small">${task.due ? escapeHtml(capitalize(formatDate(task.due))) : "Sans échéance"}
                ${task.photo_count ? ` · ${task.photo_count} photo${task.photo_count !== 1 ? "s" : ""}` : ""}</span>
            </span>${icon("right")}
        </button>
    </li>`;
}

export function renderTasks(host, initialId) {
    host.innerHTML = pageHeading("À faire", "task", "tone-tasks",
        `<button type="button" class="button primary" data-new>${icon("plus")} Ajouter</button>`) + '<div data-list></div>';
    const list = host.querySelector("[data-list]");
    const refresh = async () => {
        list.innerHTML = '<p class="empty">Chargement…</p>';
        try {
            const tasks = await api("/tasks");
            if (!list.isConnected) return;
            const pending = tasks.filter(task => !task.completed_at);
            const done = tasks.filter(task => task.completed_at);
            list.innerHTML = `<div class="stack-lg">
                ${pending.length ? `<ul class="task-list">${pending.map(taskRow).join("")}</ul>`
                    : empty("Aucune tâche à faire")}
                ${done.length ? `<section class="stack"><h2 class="list-heading">Terminées</h2><ul class="task-list">
                    ${done.map(taskRow).join("")}</ul></section>` : ""}
            </div>`;
            list.onclick = event => {
                const trigger = event.target.closest("[data-task]");
                if (trigger) openTask(Number(trigger.dataset.task), refresh);
            };
            list.onchange = async event => {
                const checkbox = event.target.closest("[data-task-check]");
                if (!checkbox) return;
                const task = tasks.find(item => item.id === Number(checkbox.dataset.taskCheck));
                checkbox.checked = !!task.completed_at;
                if (task.completed_at) await changeCompletion(task, false, refresh);
                else completeTask(task, refresh);
            };
        } catch (error) {
            list.innerHTML = errorBlock(error);
        }
    };
    host.querySelector("[data-new]").onclick = () => editTask(null, refresh);
    refresh();
    if (initialId) openTask(initialId, refresh);
}

async function openTask(id, refresh) {
    const loading = sheet("Tâche", '<p class="muted">Chargement…</p>');
    try {
        const task = await api(`/tasks/${id}`);
        if (!activeSheet(loading)) return;
        const open = () => openTask(id, refresh);
        const content = sheet(task.title, `<div class="stack">
            <p class="muted small">${task.completed_at ? "Terminée" : "À faire"}
                ${task.due ? ` · Échéance ${escapeHtml(formatDate(task.due))}` : ""}</p>
            ${task.content ? `<p class="preformatted">${escapeHtml(task.content)}</p>` : ""}
            ${task.course_title ? `<div><a class="button secondary" href="/cours?course=${task.course_id}" data-route="/cours">
                ${icon("book")} Ouvrir le cours · ${escapeHtml(task.course_title)}</a></div>`
                : task.course_id ? '<p class="muted small">Le cours lié est dans la corbeille.</p>' : ""}
            ${task.photos.length ? `<div class="task-photos">${task.photos.map((photo, index) => `<figure>
                <a href="/api/tasks/photos/${photo.id}" target="_blank" rel="noopener">
                    <img loading="lazy" src="/api/tasks/photos/${photo.id}" alt="Photo de réalisation ${index + 1}">
                </a>
                <button type="button" class="icon-button" data-remove-photo="${photo.id}"
                    aria-label="Supprimer la photo ${index + 1}">${icon("trash")}</button>
                </figure>`).join("")}</div>` : ""}
            <div class="flow">
                ${task.completed_at ? '<button type="button" data-reopen class="button secondary">Rouvrir</button>' : ""}
                <button type="button" data-complete class="button primary">${task.completed_at ? "Ajouter des photos" : "Marquer comme terminée"}</button>
            </div>
            <div class="flow">
                <button type="button" data-edit class="button secondary">${icon("edit")} Modifier</button>
                <button type="button" data-delete class="button danger">Supprimer</button>
            </div>
        </div>`);
        content.querySelector("[data-edit]").onclick = () => editTask(task, refresh, open);
        content.querySelector("[data-complete]").onclick = () => completeTask(task, refresh, open);
        const reopen = content.querySelector("[data-reopen]");
        if (reopen) reopen.onclick = () => changeCompletion(task, false, refresh, open);
        content.querySelector("[data-delete]").onclick = () => confirmDelete({
            title: "Supprimer la tâche", message: "Placer la tâche et ses photos dans la corbeille ?", onCancel: open,
            onDelete: async confirmation => {
                await api(`/tasks/${id}`, "DELETE");
                if (activeSheet(confirmation)) closeSheet();
                refresh();
            },
        });
        for (const button of content.querySelectorAll("[data-remove-photo]")) {
            button.onclick = () => confirmDelete({
                title: "Supprimer la photo", message: "Retirer cette photo de la tâche ?", onCancel: open,
                onDelete: async confirmation => {
                    await api(`/tasks/photos/${button.dataset.removePhoto}`, "DELETE");
                    if (activeSheet(confirmation)) open();
                    refresh();
                },
            });
        }
    } catch (error) {
        if (activeSheet(loading)) sheet("Tâche", errorBlock(error));
    }
}

async function editTask(task, refresh, back = closeSheet) {
    const loading = sheet("Tâche", '<p class="muted">Chargement…</p>');
    let courses;
    try {
        courses = await api("/courses");
    } catch (error) {
        if (activeSheet(loading)) sheet("Tâche", errorBlock(error));
        return;
    }
    if (!activeSheet(loading)) return;
    const unavailable = task?.course_id && !courses.some(course => course.id === task.course_id);
    const courseOptions = courses.map(course => `<option value="${course.id}" ${course.id === task?.course_id ? "selected" : ""}>
        ${escapeHtml(course.subject)} · ${escapeHtml(course.title)}</option>`).join("");
    const content = sheet(task ? "Modifier la tâche" : "Ajouter une tâche", `<form class="stack">
        ${field("Titre", input("title", task?.title, 'required maxlength="120"'))}
        ${field("Détails", textarea("content", task?.content, 'rows="4" maxlength="16000"'))}
        ${field("Échéance", input("due", task?.due, 'type="date" min="0001-01-01" max="9999-12-31"'))}
        ${field("Cours à réviser", `<select name="course_id"><option value="">Aucun cours</option>
            ${unavailable ? '<option value="keep" selected>Cours dans la corbeille</option>' : ""}${courseOptions}</select>`)}
        ${formError}
        <div class="sheet-actions"><button type="button" class="button secondary" data-back>Annuler</button>
            <button type="submit" class="button primary">Enregistrer</button></div></form>`);
    content.querySelector("[data-back]").onclick = back;
    const form = content.querySelector("form");
    form.elements.course_id.addEventListener("change", event => {
        const course = courses.find(item => item.id === Number(event.target.value));
        if (course && !form.elements.title.value.trim()) form.elements.title.value = `Réviser ${course.title}`.slice(0, 120);
    });
    submitForm(form, async data => {
        if (data.course_id === "keep") delete data.course_id;
        else data.course_id = data.course_id ? Number(data.course_id) : null;
        await api(task ? `/tasks/${task.id}` : "/tasks", task ? "PUT" : "POST", data);
        if (activeSheet(content)) back();
        refresh();
    });
}

function completeTask(task, refresh, back = closeSheet) {
    const content = sheet(task.completed_at ? "Ajouter des photos" : "Terminer la tâche", `<form class="stack">
        <p>${escapeHtml(task.title)}</p>
        ${field("Photos de réalisation", '<input type="file" name="photos" multiple accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp">')}
        <p class="muted small">Facultatif. Jusqu’à 4 photos JPEG, PNG ou WebP de 3 Mio chacune.</p>
        ${formError}
        <div class="sheet-actions"><button type="button" class="button secondary" data-back>Annuler</button>
            <button type="submit" class="button primary">${task.completed_at ? "Ajouter" : "Terminer"}</button></div></form>`);
    content.querySelector("[data-back]").onclick = back;
    const form = content.querySelector("form");
    submitForm(form, async () => {
        const photos = [...form.elements.photos.files];
        if (task.completed_at && !photos.length) throw new Error("Choisissez au moins une photo.");
        if (photos.length > 4 || photos.some(photo => photo.size > 3 * 1024 * 1024)) {
            throw new Error("Choisissez jusqu’à 4 photos de 3 Mio chacune.");
        }
        const payload = new FormData();
        payload.set("completed", "true");
        for (const photo of photos) payload.append("photos", photo);
        await api(`/tasks/${task.id}/completion`, "PUT", payload);
        if (activeSheet(content)) back();
        refresh();
        toast(task.completed_at ? "Photos ajoutées." : "Tâche terminée.");
    });
}

async function changeCompletion(task, completed, refresh, back) {
    const payload = new FormData();
    payload.set("completed", String(completed));
    try {
        await api(`/tasks/${task.id}/completion`, "PUT", payload);
        back?.();
        refresh();
    } catch (error) {
        sheet("Tâche", errorBlock(error));
    }
}
