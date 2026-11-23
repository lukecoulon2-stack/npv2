import {
    activeSheet, api, closeSheet, confirmDelete, copyText, empty, errorBlock, escapeHtml, field,
    formError, icon, input, pageHeading, sheet, styleDropdown, submitForm, textarea, toast,
} from "./ui.js";
import { coursePrompt, readCourseFile } from "./course-import.js";

const addCourse = `<button type="button" class="button primary" data-new-course>${icon("plus")} Ajouter un cours</button>`;
const courseFields = [
    ["title", "Nom du cours", 120], ["subject", "Matière", 80], ["theme", "Thème", 120],
    ["level", "Niveau", 80], ["difficulty", "Difficulté", 80],
];
const formatAddedDate = new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium" });
const collator = new Intl.Collator("fr", { numeric: true, sensitivity: "base" });
const schoolLevels = [
    ["PS", /^(ps|petite section)$/], ["MS", /^(ms|moyenne section)$/], ["GS", /^(gs|grande section)$/],
    ["CP", /^(cp|cours preparatoire)$/], ["CE1", /^ce\s*1$/], ["CE2", /^ce\s*2$/],
    ["CM1", /^cm\s*1$/], ["CM2", /^cm\s*2$/],
    ["6e", /^(6(?:e|eme)?|sixieme)$/], ["5e", /^(5(?:e|eme)?|cinquieme)$/],
    ["4e", /^(4(?:e|eme)?|quatrieme)$/], ["3e", /^(3(?:e|eme)?|troisieme)$/],
    ["Seconde", /^(2(?:de|nde|e|eme)?|seconde)$/], ["Première", /^(1(?:re|ere|e|eme)?|premiere)$/],
    ["Terminale", /^(tle|terminale)$/],
];
const difficultyLabels = new Map([
    ["facile", "Facile"], ["intermediaire", "Intermédiaire"], ["difficile", "Difficile"],
]);

function metadataKey(value) {
    return value.normalize("NFKD").replace(/\p{M}/gu, "").trim().replace(/\s+/g, " ").toLowerCase();
}

function difficultyKey(value) {
    const key = metadataKey(value);
    return key === "intermerdiaire" ? "intermediaire" : key;
}

function option(value, label) {
    return `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`;
}

function filterOptions(courses, fieldName, missingLabel, keyFor = metadataKey, preferredLabels = []) {
    const values = new Map();
    for (const course of courses) {
        const value = course[fieldName];
        const key = keyFor(value);
        if (!values.has(key)) values.set(key, value || missingLabel);
    }
    const preferred = [...preferredLabels].filter(([key]) => values.delete(key));
    const remaining = [...values].sort(([left, a], [right, b]) => Number(!left) - Number(!right) || collator.compare(a, b));
    return [...preferred, ...remaining].map(([key, label]) => option(`:${key}`, label)).join("");
}

function coursesByLevel(courses) {
    const groups = new Map();
    for (const course of courses) {
        const key = metadataKey(course.level).replace(/^classe de /, "");
        const position = schoolLevels.findIndex(([, pattern]) => pattern.test(key));
        const schoolLevel = schoolLevels[position]?.[0];
        const groupKey = schoolLevel ?? key;
        if (!groups.has(groupKey)) {
            const label = schoolLevel ?? (course.level || "Niveau non renseigné");
            const order = schoolLevel ? position : schoolLevels.length + Number(!key);
            groups.set(groupKey, { label, order, courses: [] });
        }
        groups.get(groupKey).courses.push(course);
    }
    return [...groups.values()].sort((a, b) => a.order - b.order || collator.compare(a.label, b.label));
}

export function renderCourses(host, initialId) {
    const filters = { subject: "", theme: "", difficulty: "" };
    let revision = 0;
    const refresh = async () => {
        const version = ++revision;
        try {
            const [subjects, courses] = await Promise.all([api("/subjects"), api("/courses")]);
            if (version !== revision || !host.isConnected) return;
            if (initialId) {
                const courseId = initialId;
                initialId = null;
                openCourse(courseId, subjects, reloadCourse);
            }
            const selectedSubject = () => subjects.find(item => item.id === Number(filters.subject));
            const action = `<div class="flow">${addCourse}
                <button type="button" class="button secondary" data-new-subject>Ajouter une matière</button></div>`;
            host.innerHTML = pageHeading("Cours", "book", "tone-courses", action);
            host.querySelector("[data-new-course]").onclick = () => editCourse(null, selectedSubject(), subjects, reloadCourse);
            host.querySelector("[data-new-subject]").onclick = () => editSubject(null, refresh);
            if (!courses.length && !subjects.length) {
                host.insertAdjacentHTML("beforeend", empty("Aucun cours", "Importez un fichier Markdown pour publier votre premier cours."));
                return;
            }

            host.insertAdjacentHTML("beforeend", `<div class="section-panel panel stack course-filters">
                <div class="course-filter-fields">
                    ${field("Matière", `<select name="subject">${option("", "Toutes les matières")}
                        ${subjects.map(subject => option(subject.id, subject.name)).join("")}</select>`)}
                    ${field("Thème", `<select name="theme" ${courses.length ? "" : "disabled"}>${option("", "Tous les thèmes")}
                        ${filterOptions(courses, "theme", "Sans thème")}</select>`)}
                    ${field("Difficulté", `<select name="difficulty" ${courses.length ? "" : "disabled"}>${option("", "Toutes les difficultés")}
                        ${filterOptions(courses, "difficulty", "Non renseignée", difficultyKey, difficultyLabels)}</select>`)}
                </div>
                <div class="flow" data-filter-actions hidden>
                    <button type="button" class="button secondary" data-reset-filters>Effacer les filtres</button>
                    <button type="button" class="button secondary" data-rename>Renommer la matière</button>
                </div>
            </div><div class="stack-lg" data-list></div>`);
            const list = host.querySelector("[data-list]");
            const selectors = [...host.querySelectorAll(".course-filters select")];
            const actions = host.querySelector("[data-filter-actions]");
            const reset = host.querySelector("[data-reset-filters]");
            const rename = host.querySelector("[data-rename]");
            const renderList = () => {
                for (const select of selectors) filters[select.name] = select.value;
                const filtered = Boolean(filters.subject || filters.theme || filters.difficulty);
                actions.hidden = !filtered;
                rename.hidden = !filters.subject;
                const visible = courses.filter(course => (
                    (!filters.subject || String(course.subject_id) === filters.subject)
                    && (!filters.theme || `:${metadataKey(course.theme)}` === filters.theme)
                    && (!filters.difficulty || `:${difficultyKey(course.difficulty)}` === filters.difficulty)
                ));
                list.innerHTML = visible.length ? coursesByLevel(visible).map(group => `<section class="course-level stack">
                    <h2>${escapeHtml(group.label)}</h2>
                    <div class="row-list">${group.courses.sort((a, b) => collator.compare(a.title, b.title) || a.id - b.id).map(course => {
                        const difficulty = difficultyLabels.get(difficultyKey(course.difficulty)) ?? course.difficulty;
                        const details = [filters.subject ? "" : course.subject, course.theme, difficulty].filter(Boolean);
                        return `<button type="button" class="record-row" data-course="${course.id}">
                            ${icon("note")}<span class="row-copy"><strong>${escapeHtml(course.title)}</strong>
                            ${details.length ? `<span class="muted small">${details.map(escapeHtml).join(" · ")}</span>` : ""}
                            </span>${icon("right")}</button>`;
                    }).join("")}</div>
                </section>`).join("") : empty(filtered ? "Aucun cours avec ces filtres" : "Aucun cours");
            };
            for (const select of selectors) {
                select.value = filters[select.name];
                if (select.selectedIndex < 0) select.selectedIndex = 0;
                select.onchange = renderList;
                styleDropdown(select);
            }
            reset.onclick = () => {
                const triggers = selectors.map(select => {
                    select.selectedIndex = 0;
                    return styleDropdown(select);
                });
                renderList();
                triggers[0].focus();
            };
            rename.onclick = () => editSubject(selectedSubject(), refresh);
            list.onclick = event => {
                const button = event.target.closest("[data-course]");
                if (button) openCourse(Number(button.dataset.course), subjects, reloadCourse);
            };
            renderList();
        } catch (error) {
            if (version === revision) host.innerHTML = pageHeading("Cours", "book", "tone-courses") + errorBlock(error);
        }
    };
    const reloadCourse = subject => {
        if (filters.subject) filters.subject = String(subject);
        refresh();
    };
    host.innerHTML = pageHeading("Cours", "book", "tone-courses") + '<p class="empty">Chargement…</p>';
    refresh();
}

function editSubject(subject, refresh) {
    const content = sheet(subject ? "Renommer la matière" : "Ajouter une matière", `<form class="stack">
        ${field("Nom de la matière", input("name", subject?.name, 'required maxlength="80"'))}
        ${formError}
        <div class="sheet-actions"><button type="submit" class="button primary">Enregistrer</button></div>
    </form>`);
    submitForm(content.querySelector("form"), async data => {
        await api(subject ? `/subjects/${subject.id}` : "/subjects", subject ? "PUT" : "POST", data);
        if (activeSheet(content)) closeSheet();
        refresh();
    });
}

async function openCourse(id, subjects, reload) {
    const loading = sheet("Cours", '<p class="muted">Chargement…</p>');
    try {
        const course = await api(`/courses/${id}`);
        if (!activeSheet(loading)) return;
        const details = [
            ["Thème", course.theme], ["Niveau", course.level], ["Difficulté", course.difficulty],
            ["Ajouté le", course.added_at && formatAddedDate.format(new Date(course.added_at))],
        ].filter(([, value]) => value);
        const content = sheet(course.title, `<div class="stack">
            <dl class="course-facts info-block small">${details.map(([label, value]) => `<div>
                <dt class="muted">${label}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl>
            <article class="markdown-course">${course.html}</article>
            <div class="flow">
                <a href="/api/courses/${id}/source" download class="button secondary">Télécharger le .md</a>
                <button type="button" class="button secondary" data-edit>${icon("edit")} Modifier</button>
                <button type="button" class="button danger" data-delete>Supprimer</button>
            </div></div>`, course.subject);
        const back = () => openCourse(id, subjects, reload);
        content.querySelector("[data-edit]").onclick = () => editCourse(course, null, subjects, reload, back);
        content.querySelector("[data-delete]").onclick = () => confirmDelete({
            title: "Supprimer le cours", message: "Placer ce cours dans la corbeille ?", onCancel: back,
            onDelete: async confirmation => {
                await api(`/courses/${id}`, "DELETE");
                if (activeSheet(confirmation)) closeSheet();
                reload(course.subject_id);
            },
        });
    } catch (error) {
        if (activeSheet(loading)) sheet("Cours", errorBlock(error));
    }
}

function editCourse(course, selectedSubject, subjects, reload, back = closeSheet) {
    const defaultSubject = course?.subject ?? selectedSubject?.name ?? "";
    const instructions = course ? "" : `<div class="info-block stack">
        <ol class="course-steps">
            <li>Copiez le prompt, collez-le dans votre IA préférée et ajoutez à la fin le sujet du cours souhaité.</li>
            <li>Importez le fichier .md obtenu.</li>
            <li>Vérifiez les informations détectées et complétez les champs manquants.</li>
            <li>Publiez votre cours.</li>
        </ol>
        <div><button class="button secondary" type="button" data-copy-prompt>Copier le prompt</button></div>
        <details>
            <summary>Voir le prompt</summary>
            ${field("Prompt à copier", textarea("prompt", coursePrompt, 'rows="8" readonly spellcheck="false"'))}
        </details>
    </div>`;
    const metadataFields = courseFields.map(([name, label, limit]) => {
        const value = name === "subject" ? defaultSubject : course?.[name];
        const suggestions = name === "subject" ? 'list="course-subjects"' : name === "difficulty" ? 'list="course-difficulties"' : "";
        const required = !course || name === "title" || name === "subject";
        return field(label, input(name, value, `maxlength="${limit}" ${suggestions} ${required ? "required" : ""}`));
    }).join("");
    const content = sheet(course ? "Modifier le cours" : "Ajouter un cours", `<form class="stack">
        ${instructions}
        ${field(course ? "Remplacer le fichier .md" : "Importer le fichier .md", '<input type="file" name="source" accept=".md,text/markdown">')}
        <p class="muted small" data-import-status role="status" hidden></p>
        <fieldset class="stack" data-course-fields ${course ? "" : "hidden disabled"}>
            ${metadataFields}
            <datalist id="course-subjects">${subjects.map(subject => `<option value="${escapeHtml(subject.name)}"></option>`).join("")}</datalist>
            <datalist id="course-difficulties">${[...difficultyLabels.values()].map(label => option(label, label)).join("")}</datalist>
        </fieldset>
        ${course ? field("Contenu Markdown", textarea("markdown", course.markdown, 'required maxlength="50000" rows="8"')) : ""}
        ${formError}
        <div class="sheet-actions"><button type="button" data-back class="button secondary">Annuler</button>
            <button type="submit" class="button primary" ${course ? "" : "disabled"}>${course ? "Enregistrer" : "Publier le cours"}</button></div>
    </form>`);
    const form = content.querySelector("form");
    const error = form.querySelector("[data-error]");
    const picker = form.elements.source;
    const submit = form.querySelector("[type=submit]");
    const status = form.querySelector("[data-import-status]");
    const fields = form.querySelector("[data-course-fields]");
    let markdown = course?.markdown ?? "";
    form.elements.markdown?.addEventListener("input", () => { markdown = form.elements.markdown.value; });
    form.querySelector("[data-copy-prompt]")?.addEventListener("click", async () => {
        const copied = await copyText(form.elements.prompt);
        toast(copied ? "Prompt copié." : "Sélectionnez Copier pour récupérer le prompt.");
    });
    picker.onchange = async () => {
        const file = picker.files[0];
        if (!file) return;
        picker.disabled = submit.disabled = true;
        error.hidden = status.hidden = true;
        try {
            const rawMarkdown = await readCourseFile(file);
            const prepared = await api("/courses/import", "POST", { markdown: rawMarkdown });
            const detected = prepared.metadata;
            const missing = [];
            for (const [name, label, limit] of courseFields) {
                const control = form.elements[name];
                const value = detected[name];
                if (value && value.length <= limit) control.value = value;
                else if (!course) control.value = name === "subject" ? defaultSubject : "";
                if (!control.value.trim()) missing.push(label.toLowerCase());
            }
            markdown = prepared.markdown;
            if (course) form.elements.markdown.value = markdown;
            fields.hidden = fields.disabled = false;
            status.textContent = missing.length ? `Fichier importé. Champs à compléter · ${missing.join(", ")}.`
                : "Fichier importé. Vérifiez les informations avant de continuer.";
            status.hidden = false;
        } catch (problem) {
            if (!course) {
                markdown = "";
                fields.hidden = fields.disabled = true;
            }
            error.textContent = problem.message;
            error.hidden = false;
            picker.value = "";
        } finally {
            picker.disabled = false;
            submit.disabled = !course && !markdown;
        }
    };
    content.querySelector("[data-back]").onclick = back;
    submitForm(form, async data => {
        if (!markdown.trim()) throw new Error("Importez un fichier .md contenant votre cours.");
        picker.disabled = true;
        try {
            const metadata = Object.fromEntries(courseFields.map(([name]) => [name, data[name]]));
            const saved = await api(course ? `/courses/${course.id}` : "/courses", course ? "PUT" : "POST", { ...metadata, markdown });
            if (activeSheet(content)) closeSheet();
            reload(saved.subject_id);
            toast(course ? "Cours enregistré." : "Cours publié.");
        } finally {
            picker.disabled = false;
        }
    });
}
