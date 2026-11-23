import {
    activeSheet, api, closeSheet, confirmDelete, empty, errorBlock, escapeHtml, field,
    formError, icon, input, pageHeading, sheet, submitForm, textarea, toast,
} from "./ui.js";

export function renderCourses(host, initialId) {
    let selected = null;
    let revision = 0;
    const refresh = async () => {
        const version = ++revision;
        try {
            const subjects = await api("/subjects");
            if (version !== revision || !host.isConnected) return;
            if (initialId) {
                const courseId = initialId;
                initialId = null;
                openCourse(courseId, subjects, reloadCourse);
            }
            const subject = subjects.find(item => item.id === selected);
            const action = subject
                ? `<button type="button" class="button primary" data-new-course>${icon("plus")} Ajouter un cours</button>`
                : `<button type="button" class="button primary" data-new-subject>${icon("plus")} Ajouter une matière</button>`;
            host.innerHTML = pageHeading("Cours", "book", "tone-courses", action);
            if (!subject) {
                host.querySelector("[data-new-subject]").onclick = () => editSubject(null, refresh);
                host.insertAdjacentHTML("beforeend", subjects.length ? `<div class="subject-grid">
                    ${subjects.map(item => `<button type="button" class="record-row" data-subject="${item.id}">
                        ${icon("book")}<span class="row-copy"><strong>${escapeHtml(item.name)}</strong>
                            <span class="muted small">${item.course_count} cours</span></span>${icon("right")}
                    </button>`).join("")}</div>` : empty("Aucune matière", "Ajoutez une matière pour classer vos cours Markdown."));
                for (const button of host.querySelectorAll("[data-subject]")) button.onclick = () => {
                    selected = Number(button.dataset.subject);
                    refresh();
                };
                return;
            }

            host.querySelector("[data-new-course]").onclick = () => editCourse(null, subject.id, subjects, reloadCourse);
            host.insertAdjacentHTML("beforeend", `<div class="section-heading">
                <h2>${escapeHtml(subject.name)}</h2><div class="flow">
                    <button type="button" class="button secondary" data-rename aria-label="Renommer la matière">${icon("edit")}</button>
                    <button type="button" class="button secondary" data-subjects>Toutes les matières</button></div>
                </div><div data-list></div>`);
            host.querySelector("[data-subjects]").onclick = () => { selected = null; refresh(); };
            host.querySelector("[data-rename]").onclick = () => editSubject(subject, refresh);
            const list = host.querySelector("[data-list]");
            const courses = await api(`/subjects/${subject.id}/courses`);
            if (version !== revision || !list.isConnected) return;
            list.innerHTML = courses.length ? `<div class="row-list">
                ${courses.map(course => `<button type="button" class="record-row" data-course="${course.id}">
                    ${icon("note")}<span class="row-copy"><strong>${escapeHtml(course.title)}</strong></span>${icon("right")}
                </button>`).join("")}</div>` : empty("Aucun cours dans cette matière");
            for (const button of list.querySelectorAll("[data-course]")) button.onclick = () => {
                openCourse(Number(button.dataset.course), subjects, reloadCourse);
            };
        } catch (error) {
            if (version === revision) host.innerHTML = pageHeading("Cours", "book", "tone-courses") + errorBlock(error);
        }
    };
    const reloadCourse = subject => { selected = subject; refresh(); };
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
        const content = sheet(course.title, `<div class="stack">
            <article class="markdown-course">${course.html}</article>
            <div class="flow">
                <a href="/api/courses/${id}/source" download class="button secondary">Télécharger le .md</a>
                <button type="button" class="button secondary" data-edit>${icon("edit")} Modifier</button>
                <button type="button" class="button danger" data-delete>Supprimer</button>
            </div></div>`, subjects.find(subject => subject.id === course.subject_id)?.name);
        const back = () => openCourse(id, subjects, reload);
        content.querySelector("[data-edit]").onclick = () => editCourse(course, course.subject_id, subjects, reload, back);
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

function editCourse(course, subjectId, subjects, reload, back = closeSheet) {
    const choices = subjects.map(subject => `<option value="${subject.id}" ${subject.id === subjectId ? "selected" : ""}>
        ${escapeHtml(subject.name)}</option>`).join("");
    const content = sheet(course ? "Modifier le cours" : "Ajouter un cours", `<form class="stack">
        ${field("Matière", `<select name="subject" required>${choices}</select>`)}
        ${field("Titre", input("title", course?.title, 'required maxlength="120"'))}
        ${field("Importer un fichier .md", '<input type="file" name="source" accept=".md,text/markdown">')}
        ${field("Contenu Markdown", textarea("markdown", course?.markdown, 'required maxlength="50000" rows="8"'))}
        ${formError}
        <div class="sheet-actions"><button type="button" data-back class="button secondary">Annuler</button>
            <button type="submit" class="button primary">Enregistrer</button></div>
    </form>`);
    const form = content.querySelector("form");
    const error = form.querySelector("[data-error]");
    const picker = form.elements.source;
    const submit = form.querySelector("[type=submit]");
    picker.onchange = async () => {
        const file = picker.files[0];
        if (!file) return;
        picker.disabled = submit.disabled = true;
        error.hidden = true;
        try {
            if (!/\.md$/i.test(file.name) || file.size > 200 * 1024) {
                throw new Error("Choisissez un fichier .md de 200 Kio maximum.");
            }
            let text;
            try { text = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer()); }
            catch { throw new Error("Enregistrez le fichier Markdown en UTF-8 avant de l’importer."); }
            if (text.length > 50000) throw new Error("Le cours est limité à 50 000 caractères.");
            form.elements.markdown.value = text;
            if (!form.elements.title.value.trim()) form.elements.title.value = file.name.slice(0, -3).slice(0, 120);
        } catch (problem) {
            error.textContent = problem.message;
            error.hidden = false;
        } finally {
            picker.disabled = submit.disabled = false;
            picker.value = "";
        }
    };
    content.querySelector("[data-back]").onclick = back;
    submitForm(form, async data => {
        const subject = Number(data.subject);
        await api(course ? `/courses/${course.id}` : "/courses", course ? "PUT" : "POST",
            { subject, title: data.title, markdown: data.markdown });
        if (activeSheet(content)) closeSheet();
        reload(subject);
        toast("Cours enregistré.");
    });
}
