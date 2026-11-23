import { activeSheet, api, confirmDelete, errorBlock, escapeHtml, field, icon, input, sheet, toast } from "./ui.js";

const kinds = {
    notes: { label: "Notes", path: "/notes", key: "note", icon: "note" },
    events: { label: "Événements", path: "/evenements", key: "event", icon: "event" },
    tasks: { label: "À faire", path: "/a-faire", key: "task", icon: "task" },
    courses: { label: "Cours", path: "/cours", key: "course", icon: "book" },
};

export function openSearch() {
    const content = sheet("Rechercher", `<div class="stack">
        ${field("Recherche", input("search-query", "", 'type="search" placeholder="Titre, mot-clé…" maxlength="120"'))}
        ${field("Rubrique", `<select name="search-kind"><option value="">Toutes les rubriques</option>
            ${Object.entries(kinds).map(([key, kind]) => `<option value="${key}">${kind.label}</option>`).join("")}
        </select>`)}
        <div data-results aria-live="polite"></div>
    </div>`);
    const query = content.querySelector('[name="search-query"]');
    const type = content.querySelector('[name="search-kind"]');
    const results = content.querySelector("[data-results]");
    let ticket = 0, timer;
    function search() {
        const version = ++ticket;
        clearTimeout(timer);
        const phrase = query.value.trim();
        results.replaceChildren();
        if (!phrase) return;
        timer = setTimeout(async () => {
            if (!activeSheet(content)) return;
            try {
                const rows = await api(`/search?${new URLSearchParams({ q: phrase, type: type.value })}`);
                if (version !== ticket || !activeSheet(content)) return;
                results.innerHTML = rows.length ? `<div class="row-list">${rows.map(row => {
                    const kind = kinds[row.kind];
                    return `<a class="record-row" href="${kind.path}?${kind.key}=${row.id}" data-route="${kind.path}">
                        ${icon(kind.icon)}<span class="row-copy"><strong>${escapeHtml(row.title)}</strong>
                        <span class="small muted">${kind.label}</span></span>${icon("right")}</a>`;
                }).join("")}</div>` : '<p class="muted">Aucun résultat.</p>';
            } catch (error) {
                if (version === ticket && activeSheet(content)) results.innerHTML = errorBlock(error);
            }
        }, 160);
    }
    query.addEventListener("input", search);
    type.addEventListener("change", search);
    query.focus();
}

export async function openTrash() {
    const loading = sheet("Corbeille", '<p class="muted">Chargement…</p>');
    try {
        const rows = await api("/trash");
        if (!activeSheet(loading)) return;
        const formatter = new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium" });
        const content = sheet("Corbeille", `<div class="row-list">
            ${rows.length ? rows.map((row, index) => `<article class="info-block stack">
                <div class="row-copy"><strong>${escapeHtml(row.title)}</strong>
                    <span class="muted small">${kinds[row.kind].label} · ${formatter.format(new Date(row.deleted_at))}</span></div>
                <div class="flow"><button type="button" class="button secondary" data-restore="${index}">Restaurer</button>
                    <button type="button" class="button danger" data-purge="${index}">Supprimer définitivement</button></div>
            </article>`).join("") : '<p class="muted">La corbeille est vide.</p>'}
            <p class="error" data-error role="alert" hidden></p>
        </div>`);
        const path = row => `/trash/${row.kind}/${row.id}`;
        for (const button of content.querySelectorAll("[data-restore]")) button.onclick = async () => {
            button.disabled = true;
            try {
                await api(path(rows[button.dataset.restore]), "POST");
                toast("Élément restauré.");
                if (activeSheet(content)) openTrash();
            } catch (error) {
                const output = content.querySelector("[data-error]");
                output.textContent = error.message;
                output.hidden = false;
            } finally {
                button.disabled = false;
            }
        };
        for (const button of content.querySelectorAll("[data-purge]")) button.onclick = () => {
            const row = rows[button.dataset.purge];
            confirmDelete({
                title: "Supprimer définitivement",
                message: `« ${row.title} » sera effacé de la corbeille.`,
                onCancel: openTrash,
                onDelete: async confirmation => {
                    await api(path(row), "DELETE");
                    if (activeSheet(confirmation)) await openTrash();
                },
            });
        };
    } catch (error) {
        if (activeSheet(loading)) sheet("Corbeille", errorBlock(error));
    }
}
