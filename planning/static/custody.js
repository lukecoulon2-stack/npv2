import { capitalize, formatDate, parentMarks, parents, renderCalendar, WEEKDAYS } from "./calendar.js";
import {
    activeSheet, api, closeSheet, colorDot, confirmDelete, empty, errorBlock, escapeHtml, field,
    formError, icon, input, pageHeading, safeColor, sheet, submitForm, textarea, toast,
} from "./ui.js";

const dateAttributes = 'type="date" min="0001-01-01" max="9999-12-31" required';

function parentLegend(list) {
    const marks = parentMarks(list);
    return `<div class="legend" aria-label="Légende">${list.map((item, index) =>
        `<span class="legend-item">${colorDot(item.color)} ${marks[0] === "1" ? `${marks[index]} · ` : ""}${escapeHtml(item.name)}</span>`).join("")}
        <span class="legend-item">${icon("user")} Garde</span>
        <span class="legend-item">${icon("note")} Notes</span></div>`;
}

export function renderPlanning(host, session, position, onSetup) {
    const settings = session.settings;
    if (!settings) {
        host.innerHTML = pageHeading("Mon planning", "calendar", "tone-planning") + empty(
            "Configurer l’alternance",
            "Choisissez les deux parents, leurs couleurs et la première semaine de garde.",
            '<button type="button" class="button primary" data-setup>Configurer le planning</button>',
        );
        host.querySelector("[data-setup]").onclick = onSetup;
        return;
    }
    host.innerHTML = pageHeading(
        "Mon planning", "calendar", "tone-planning",
        `<button type="button" class="button primary" data-period>${icon("swap")} Modifier une période</button>`,
    ) + '<div class="calendar-host"></div>';
    const list = parents(settings);
    const calendar = renderCalendar(host.querySelector(".calendar-host"), "planning", position, {
        today: session.today,
        timezone: settings.timezone,
        parents: list,
        legend: parentLegend(list),
        onDay: day => openDay(day, settings, calendar.refresh),
    });
    host.querySelector("[data-period]").onclick = () => {
        openAssignment(settings, position.day, { period: true, onDone: calendar.refresh });
    };
}

export function openParentSettings(session, onSave) {
    const settings = session.settings;
    const list = settings ? parents(settings) : [
        { name: "", color: "#9368db" },
        { name: "", color: "#5c9bbb" },
    ];
    const names = list.map((parent, index) => {
        const key = index === 0 ? "a" : "b";
        return `<div class="name-and-color">
            ${field(`Parent ${index + 1}`, input(`name_${key}`, parent.name, 'required maxlength="50" autocomplete="off"'))}
            ${field("Couleur", input(`color_${key}`, safeColor(parent.color), 'type="color" required'))}
        </div>`;
    }).join("");
    const content = sheet(settings ? "Modifier les parents" : "Configurer le planning", `<form class="stack">
        ${names}
        ${settings ? "" : `<div class="fields-two">
            ${field("Semaine de référence", input("anchor", session.today, dateAttributes))}
            ${field("Parent qui commence", '<select name="first_parent"><option value="1">Parent 1</option><option value="2">Parent 2</option></select>')}
        </div>
        <p class="muted small">Le planning démarre le lundi de la semaine choisie.</p>`}
        ${field("Fuseau horaire", input("timezone", session.timezone || "Europe/Paris", 'list="timezones" maxlength="80" required autocomplete="off"'))}
        <datalist id="timezones">
            <option value="Europe/Paris"><option value="Europe/Brussels"><option value="Europe/Zurich">
            <option value="America/Montreal"><option value="America/Guadeloupe"><option value="Indian/Reunion">
            <option value="UTC">
        </datalist>
        ${formError}
        <div class="sheet-actions"><button type="submit" class="button primary">${settings ? "Enregistrer" : "Créer le planning"}</button></div>
    </form>`, settings ? "" : "Renseignez les deux parents pour démarrer l’alternance.");
    const form = content.querySelector("form");
    if (!settings) {
        const select = form.elements.first_parent;
        for (const [index, name] of [form.elements.name_a, form.elements.name_b].entries()) {
            name.addEventListener("input", () => {
                select.options[index].textContent = name.value.trim() || `Parent ${index + 1}`;
            });
        }
    }
    submitForm(form, async data => {
        if (!settings) data.first_parent = Number(data.first_parent);
        await api("/settings", settings ? "PUT" : "POST", data);
        if (activeSheet(content)) closeSheet();
        toast(settings ? "Réglages enregistrés." : "Planning configuré.");
        await onSave();
    });
}

function openAssignment(settings, day, { period = false, manual = false, parent = 1, onDone, onCancel }) {
    const people = parents(settings);
    const dateInputs = period ? `<div class="fields-two">
        ${field("Début", input("start", day, dateAttributes))}
        ${field("Fin", input("end", day, dateAttributes))}
    </div>` : `<input type="hidden" name="start" value="${day}"><input type="hidden" name="end" value="${day}">`;
    const content = sheet(period ? "Modifier une période" : "Modifier l’attribution", `<form class="stack">
        ${dateInputs}
        ${field("Action", `<select name="action"><option value="assign">Attribuer à un parent</option>
            <option value="invert">Inverser l’attribution</option>
            ${period || manual ? '<option value="clear">Retirer les exceptions</option>' : ""}</select>`)}
        <div data-parent-field>${field("Parent", `<select name="parent">${people.map(person =>
            `<option value="${person.id}" ${person.id === parent ? "selected" : ""}>${escapeHtml(person.name)}</option>`,
        ).join("")}</select>`)}</div>
        <div class="info-block" data-preview hidden></div>
        ${formError}
        <div class="sheet-actions">
            ${onCancel ? '<button type="button" class="button secondary" data-cancel>Retour</button>' : ""}
            <button type="submit" class="button secondary" data-preview-button>Calculer l’aperçu</button>
            <button type="submit" class="button primary" data-commit hidden>Appliquer</button>
        </div>
    </form>`, period ? "La modification inclut le premier et le dernier jour." : capitalize(formatDate(day)));
    const form = content.querySelector("form");
    const preview = content.querySelector("[data-preview]");
    const commit = content.querySelector("[data-commit]");
    const error = content.querySelector("[data-error]");
    let previewToken = null;
    let revision = 0;
    if (onCancel) content.querySelector("[data-cancel]").onclick = onCancel;

    function invalidate() {
        revision += 1;
        previewToken = null;
        preview.hidden = commit.hidden = true;
        error.hidden = true;
        content.querySelector("[data-parent-field]").hidden = form.elements.action.value !== "assign";
        if (period && form.elements.start.value) form.elements.end.min = form.elements.start.value;
    }

    form.addEventListener("input", invalidate);
    submitForm(form, async (data, button) => {
        data.parent = Number(data.parent);
        if (button === commit) {
            if (!previewToken) throw new Error("Calculez d’abord l’aperçu.");
            try {
                await api("/assignments", "POST", { ...data, token: previewToken });
            } catch (problem) {
                if (problem.status === 409) invalidate();
                throw problem;
            }
            toast(period ? "Période mise à jour." : "Attribution mise à jour.");
            if (activeSheet(content)) {
                if (onCancel) onCancel();
                else closeSheet();
            }
            onDone();
            return;
        }
        invalidate();
        const requestRevision = revision;
        const result = await api("/assignments/preview", "POST", data);
        if (revision !== requestRevision || !activeSheet(content)) return;
        previewToken = result.token;
        const count = result.counts[1] + result.counts[2];
        const summary = people.map(person => `<span class="legend-item">${colorDot(person.color)}
            ${escapeHtml(person.name)} · ${result.counts[person.id]} j</span>`).join("");
        preview.innerHTML = `<p class="detail-subhead">Après modification · ${count} jour${count > 1 ? "s" : ""}</p>
            <div class="legend">${summary}</div>
            <ul class="period-sample">${result.sample.map(item => `<li>
                <span>${formatDate(item.day, { day: "numeric", month: "short", year: "numeric" })}</span>
                <span>${escapeHtml(people[item.after - 1].name)}</span>
            </li>`).join("")}</ul>
            ${count > result.sample.length ? '<p class="muted small">Les sept premiers jours sont affichés.</p>' : ""}`;
        preview.hidden = commit.hidden = false;
        commit.focus();
    });
}

async function openDay(day, settings, refresh) {
    const title = capitalize(formatDate(day));
    const loading = sheet(title, '<p class="empty">Chargement de la journée…</p>');
    try {
        const [days, notes] = await Promise.all([
            api(`/planning?start=${day}&end=${day}`),
            api(`/day-notes?day=${day}`),
        ]);
        if (!activeSheet(loading)) return;
        const item = days[day];
        const parent = parents(settings)[item.parent - 1];
        const reopen = () => openDay(day, settings, refresh);
        const afterNote = content => {
            refresh();
            if (activeSheet(content)) reopen();
        };
        const content = sheet(title, `<div class="stack-lg">
            <div class="info-block stack">
                <div><p class="muted small">Parent responsable</p>
                    <p class="legend-item">${colorDot(parent.color)} <strong>${escapeHtml(parent.name)}</strong></p>
                    ${item.custom ? '<p class="muted small">Attribution manuelle</p>' : ""}
                </div>
                ${item.carers.length ? `<p class="info-line">${icon("user")} <span>Garde · ${escapeHtml(item.carers.join(", "))}</span></p>` : ""}
                <div><button type="button" class="button secondary" data-assignment>${icon("swap")} Modifier l’attribution</button></div>
            </div>
            <div class="stack">
                <h3 class="detail-subhead">Notes de la journée</h3>
                ${notes.length ? notes.map(note => `<div class="detail-note">
                    ${note.checked !== null ? `<input type="checkbox" class="note-check" data-check="${note.id}"
                        aria-label="Cocher la note de ${escapeHtml(note.author)}" ${note.checked ? "checked" : ""}>` : ""}
                    <div class="row-copy"><strong>${escapeHtml(note.author)}</strong>
                        <p class="preformatted">${escapeHtml(note.content)}</p></div>
                    <button type="button" class="icon-button" data-edit="${note.id}" aria-label="Modifier la note de ${escapeHtml(note.author)}">${icon("edit")}</button>
                </div>`).join("") : '<p class="muted">Aucune note pour cette journée.</p>'}
                ${formError}
                <div><button type="button" class="button primary" data-new>${icon("plus")} Ajouter une note</button></div>
            </div>
        </div>`);
        content.querySelector("[data-assignment]").onclick = () => openAssignment(settings, day, {
            manual: item.custom, parent: item.parent, onDone: refresh, onCancel: reopen,
        });
        content.querySelector("[data-new]").onclick = () => editDayNote(day, settings, null, reopen, afterNote);
        content.querySelectorAll("[data-edit]").forEach(button => {
            button.onclick = () => editDayNote(day, settings, notes.find(note => note.id === Number(button.dataset.edit)), reopen, afterNote);
        });
        content.querySelectorAll("[data-check]").forEach(checkbox => {
            checkbox.onchange = async () => {
                checkbox.disabled = true;
                const error = content.querySelector("[data-error]");
                error.hidden = true;
                try {
                    await api(`/day-notes/${checkbox.dataset.check}`, "PATCH", { checked: checkbox.checked });
                } catch (problem) {
                    checkbox.checked = !checkbox.checked;
                    error.textContent = problem.message;
                    error.hidden = false;
                } finally {
                    checkbox.disabled = false;
                }
            };
        });
    } catch (error) {
        if (activeSheet(loading)) sheet(title, errorBlock(error));
    }
}

function editDayNote(day, settings, note, onCancel, onDone) {
    const content = sheet(note ? "Modifier la note" : "Ajouter une note", `<form class="stack">
        ${field("Auteur", input("author", note?.author, 'required maxlength="80" list="authors"'))}
        <datalist id="authors">${parents(settings).map(parent => `<option value="${escapeHtml(parent.name)}"></option>`).join("")}</datalist>
        ${field("Note", textarea("content", note?.content, 'rows="4" maxlength="16000" required'))}
        <label class="check-line"><input name="checkable" type="checkbox" ${note?.checked != null ? "checked" : ""}> Ajouter une case à cocher</label>
        ${formError}
        <div class="sheet-actions">
            <button type="button" class="button secondary" data-cancel>Retour</button>
            ${note ? '<button type="button" class="button danger" data-delete>Supprimer</button>' : ""}
            <button type="submit" class="button primary">Enregistrer</button>
        </div>
    </form>`, capitalize(formatDate(day)));
    const path = note ? `/day-notes/${note.id}` : "/day-notes";
    content.querySelector("[data-cancel]").onclick = onCancel;
    submitForm(content.querySelector("form"), async data => {
        await api(path, note ? "PUT" : "POST", {
            day, author: data.author, content: data.content, checked: data.checkable ? note?.checked ?? false : null,
        });
        toast("Note enregistrée.");
        onDone(content);
    });
    if (note) content.querySelector("[data-delete]").onclick = () => confirmDelete({
        title: "Supprimer la note",
        message: "Supprimer cette note de la journée ?",
        onCancel: () => editDayNote(day, settings, note, onCancel, onDone),
        onDelete: async confirmation => {
            await api(path, "DELETE");
            toast("Note supprimée.");
            onDone(confirmation);
        },
    });
}

export function renderSettings(host, session, onSetup, onUpdate) {
    host.innerHTML = pageHeading("Réglages", "settings", "tone-planning");
    if (!session.settings) {
        host.insertAdjacentHTML("beforeend", empty(
            "Planning à configurer",
            "Renseignez les parents pour accéder aux réglages de garde.",
            '<button type="button" class="button primary" data-setup>Configurer le planning</button>',
        ));
        host.querySelector("[data-setup]").onclick = onSetup;
        return;
    }

    const settings = session.settings;
    const list = parents(settings);
    host.insertAdjacentHTML("beforeend", `<div class="stack-lg">
        <section class="section-panel panel stack">
            <h2>Parents et alternance</h2>
            <div class="legend">${list.map(item => `<span class="legend-item">${colorDot(item.color)} ${escapeHtml(item.name)}</span>`).join("")}</div>
            <p class="muted small">Semaine du ${formatDate(settings.anchor, { day: "numeric", month: "long", year: "numeric" })}
                · ${escapeHtml(list[settings.first_parent - 1].name)} commence<br>Fuseau horaire · ${escapeHtml(settings.timezone)}</p>
            <div><button type="button" class="button secondary" data-parents>${icon("edit")} Modifier</button></div>
        </section>
        <section class="section-panel panel stack" data-weekends>
            <h2>Inversion des week-ends</h2><p class="muted">Chargement…</p>
        </section>
        <section class="section-panel panel stack" data-carers>
            <h2>Personnes de garde</h2><p class="muted">Chargement…</p>
        </section>
    </div>`);
    host.querySelector("[data-parents]").onclick = () => openParentSettings(session, onUpdate);
    loadWeekends(host.querySelector("[data-weekends]"), Number(session.today.slice(0, 4)));
    loadCarers(host.querySelector("[data-carers]"));
}

async function loadWeekends(section, year) {
    try {
        const years = await api("/weekends");
        if (!section.isConnected) return;
        section.innerHTML = `<h2>Inversion des week-ends</h2>
            <p class="muted">Inverse l’alternance des samedis et dimanches de l’année choisie. Les attributions manuelles restent prioritaires.</p>
            <form class="stack">
                <div class="flow weekend-fields">
                    ${field("Année", input("year", year, 'type="number" min="1" max="9999" step="1" required'))}
                    <label class="check-line"><input name="enabled" type="checkbox"> Inverser les week-ends</label>
                </div>
                ${formError}
                <div><button type="submit" class="button secondary">Enregistrer l’inversion</button></div>
            </form>
            <p class="muted small" data-years></p>`;
        const form = section.querySelector("form");
        const selected = form.elements.year;
        const checkbox = form.elements.enabled;
        function display() {
            const value = Number(selected.value);
            checkbox.checked = years.includes(value);
            checkbox.disabled = value < 1 || value > 9999 || !Number.isInteger(value);
            section.querySelector("[data-years]").textContent = years.length
                ? `Années inversées · ${years.join(", ")}` : "Aucune année inversée.";
        }
        selected.addEventListener("input", display);
        display();
        submitForm(form, async data => {
            const value = Number(data.year);
            const enabled = checkbox.checked;
            await api(`/weekends/${value}`, "PUT", { enabled });
            const index = years.indexOf(value);
            if (enabled && index < 0) years.push(value);
            else if (!enabled && index >= 0) years.splice(index, 1);
            years.sort((a, b) => a - b);
            display();
            toast("Réglage des week-ends enregistré.");
        });
    } catch (error) {
        section.innerHTML = `<h2>Inversion des week-ends</h2>${errorBlock(error)}`;
    }
}

async function loadCarers(section) {
    try {
        const carers = await api("/carers");
        if (!section.isConnected) return;
        section.innerHTML = `<h2>Personnes de garde</h2>
            ${carers.length ? `<div class="row-list">${carers.map(carer => `<button type="button" class="record-row" data-carer="${carer.id}">
                ${icon("user")}<span class="row-copy"><strong>${escapeHtml(carer.name)}</strong>
                <span class="small muted">${carer.days.map(day => WEEKDAYS[day]).join(", ")}${carer.active ? "" : " · Suspendue"}</span></span>
                ${icon("right")}</button>`).join("")}</div>` : '<p class="muted">Aucune garde récurrente.</p>'}
            <div><button type="button" class="button primary" data-new-carer>${icon("plus")} Ajouter une personne</button></div>`;
        const redraw = () => loadCarers(section);
        section.querySelector("[data-new-carer]").onclick = () => editCarer(null, redraw);
        section.querySelectorAll("[data-carer]").forEach(button => {
            button.onclick = () => editCarer(carers.find(carer => carer.id === Number(button.dataset.carer)), redraw);
        });
    } catch (error) {
        section.innerHTML = `<h2>Personnes de garde</h2>${errorBlock(error)}`;
    }
}

function editCarer(carer, refresh) {
    const content = sheet(carer ? "Modifier la personne de garde" : "Ajouter une personne de garde", `<form class="stack">
        ${field("Nom", input("name", carer?.name, 'required maxlength="80"'))}
        <fieldset><legend>Jours de garde</legend><div class="flow">
            ${WEEKDAYS.map((name, index) => `<label class="day-choice"><input name="days" type="checkbox" value="${index}"
                ${carer?.days.includes(index) ? "checked" : ""}> ${name}</label>`).join("")}
        </div></fieldset>
        <label class="check-line"><input name="active" type="checkbox" ${carer && !carer.active ? "" : "checked"}> Garde active</label>
        ${formError}
        <div class="sheet-actions">
            ${carer ? '<button type="button" class="button danger" data-delete>Supprimer</button>' : ""}
            <button type="submit" class="button primary">Enregistrer</button>
        </div>
    </form>`);
    const form = content.querySelector("form");
    const path = carer ? `/carers/${carer.id}` : "/carers";
    submitForm(form, async data => {
        await api(path, carer ? "PUT" : "POST", {
            name: data.name, active: data.active === "on", days: new FormData(form).getAll("days").map(Number),
        });
        if (activeSheet(content)) closeSheet();
        toast("Garde enregistrée.");
        refresh();
    });
    if (carer) content.querySelector("[data-delete]").onclick = () => confirmDelete({
        title: "Supprimer la personne de garde",
        message: `Retirer ${carer.name} du planning des gardes ?`,
        onCancel: () => editCarer(carer, refresh),
        onDelete: async confirmation => {
            await api(path, "DELETE");
            if (activeSheet(confirmation)) closeSheet();
            toast("Personne de garde supprimée.");
            refresh();
        },
    });
}
