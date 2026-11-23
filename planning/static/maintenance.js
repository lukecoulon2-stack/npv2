import { activeSheet, api, closeSheet, confirmDelete, errorBlock, escapeHtml, field, formError, icon, sheet, submitForm, toast } from "./ui.js";

const resetActions = {
    planning: {
        label: "Réinitialiser le planning",
        message: "Les parents, l’alternance, les exceptions, les personnes de garde et les notes journalières seront effacés. Le planning devra être configuré à nouveau.",
        done: "Planning réinitialisé.",
    },
    notes: {
        label: "Effacer toutes les notes du bloc-notes",
        message: "Toutes les notes du bloc-notes seront définitivement supprimées.",
        done: "Bloc-notes vidé.",
    },
    events: {
        label: "Effacer tous les événements",
        message: "Tous les événements et leurs rappels seront définitivement supprimés.",
        done: "Événements effacés.",
    },
};
const connectionDate = new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "medium" });

function connectionTime(timestamp) {
    return `<time datetime="${escapeHtml(timestamp)}">${connectionDate.format(new Date(timestamp))}</time>`;
}

export function askMaintenanceCode() {
    const content = sheet("Maintenance", `<form class="stack">
        ${field("Code de maintenance", '<input name="code" type="password" inputmode="numeric" required autocomplete="off">')}
        ${formError}
        <div class="sheet-actions"><button type="submit" class="button primary">Déverrouiller</button></div>
    </form>`);
    submitForm(content.querySelector("form"), async ({ code }) => {
        await api("/maintenance/unlock", "POST", { code });
        if (activeSheet(content)) await openMaintenance();
    });
}

export async function openMaintenance({ accountsOpen = false, dataOpen = false } = {}) {
    const loading = sheet("Maintenance", '<p class="empty">Chargement…</p>');
    try {
        const info = await api("/maintenance");
        if (!activeSheet(loading)) return;
        const rows = info.logs.map(row => `<tr>
            <td>${escapeHtml(row.username ?? "—")}</td><td>#${row.visitor_id}</td><td>${escapeHtml(row.ip)}</td>
            <td>${connectionTime(row.connected_at)}</td>
        </tr>`).join("");
        const accounts = info.accounts.map(account => `<li>
            <button type="button" class="record-row" data-maintenance-account="${account.id}">
                ${icon("user")}<span class="row-copy"><strong>${escapeHtml(account.username)}</strong>
                <span class="muted small">Compte #${account.id} · ${account.visitor_count} identifiant${account.visitor_count === 1 ? "" : "s"}</span></span>
                ${icon("right")}
            </button>
        </li>`).join("");
        const content = sheet("Maintenance", `<div class="stack-lg">
            <section class="info-block stack">
                <h3>Mise à jour</h3>
                <p class="muted small">Les sources viennent de GitHub. La configuration et les données restent sur cet ordinateur.</p>
                <form class="stack">
                    <p class="muted small" data-update-status>${info.pending
                        ? `Révision ${escapeHtml(info.pending.slice(0, 12))} prête. Arrêtez et relancez start.py pour l’appliquer.`
                        : info.can_update ? "Source · lukecoulon2-stack/npv2" : "Mise à jour disponible en mode normal."}</p>
                    ${formError}
                    <div><button type="submit" class="button primary" ${info.can_update && !info.pending ? "" : "disabled"}>
                        Mise à jour</button></div>
                </form>
            </section>
            <details class="info-block" data-raw><summary>Données brutes</summary>
                <pre class="raw-data" aria-live="polite"></pre>
            </details>
            <details class="info-block" ${dataOpen ? "open" : ""}>
                <summary>Gestion des données</summary>
                <div class="stack maintenance-data-actions">
                    ${Object.entries(resetActions).map(([scope, action]) => `<button type="button"
                        class="button danger" data-reset="${scope}">${action.label}</button>`).join("")}
                </div>
            </details>
            <details class="info-block" ${accountsOpen ? "open" : ""}><summary>Comptes (${info.accounts.length})</summary>
                ${accounts ? `<ul class="visitor-list row-list">${accounts}</ul>` : '<p class="muted">Aucun compte enregistré.</p>'}
            </details>
            <section class="stack">
                <div class="flow"><h3>Dernières connexions</h3><button type="button" class="button secondary" data-refresh>Actualiser</button></div>
                ${rows ? `<div class="maintenance-scroll" tabindex="0"><table class="maintenance-table">
                    <thead><tr><th scope="col">Compte</th><th scope="col">ID de visite</th><th scope="col">IP</th><th scope="col">Date et heure</th></tr></thead>
                    <tbody>${rows}</tbody></table></div>` : '<p class="muted">Aucune connexion enregistrée.</p>'}
            </section>
            <div><button type="button" class="button secondary" data-lock>Verrouiller</button></div>
        </div>`);
        const form = content.querySelector("form");
        const showData = () => openMaintenance({ dataOpen: true });
        for (const button of content.querySelectorAll("[data-reset]")) {
            const scope = button.dataset.reset;
            const action = resetActions[scope];
            button.onclick = () => confirmDelete({
                title: action.label,
                message: action.message,
                onCancel: showData,
                onDelete: async confirmation => {
                    try {
                        await api(`/maintenance/data/${scope}`, "DELETE");
                        window.dispatchEvent(new Event("naoning:data-reset"));
                        toast(action.done);
                        if (activeSheet(confirmation)) await showData();
                    } catch (error) {
                        if (error.status === 401 && activeSheet(confirmation)) askMaintenanceCode();
                        else throw error;
                    }
                },
            });
        }
        for (const button of content.querySelectorAll("[data-maintenance-account]")) {
            button.onclick = () => openMaintenanceAccount(button.dataset.maintenanceAccount);
        }
        const status = content.querySelector("[data-update-status]");
        submitForm(form, async () => {
            status.textContent = "Récupération des sources GitHub…";
            try {
                const { revision } = await api("/maintenance/update", "POST");
                if (revision && activeSheet(content)) await openMaintenance();
                else status.textContent = "Les sources sont déjà à jour.";
            } catch (error) {
                status.textContent = "Aucune source installée.";
                if (error.status === 401 && activeSheet(content)) askMaintenanceCode();
                else throw error;
            }
        });
        const details = content.querySelector("[data-raw]");
        details.addEventListener("toggle", async () => {
            if (!details.open || details.dataset.loaded) return;
            const output = details.querySelector("pre");
            output.textContent = "Chargement…";
            try {
                const data = await api("/maintenance/data");
                output.textContent = JSON.stringify(data, null, 2);
                details.dataset.loaded = "yes";
            } catch (error) {
                if (error.status === 401 && activeSheet(content)) askMaintenanceCode();
                else output.textContent = error.message;
            }
        });
        content.querySelector("[data-refresh]").onclick = openMaintenance;
        content.querySelector("[data-lock]").onclick = async event => {
            const button = event.currentTarget;
            try {
                await api("/maintenance/lock", "POST");
                if (activeSheet(content)) closeSheet();
            } catch (error) {
                button.insertAdjacentHTML("afterend", errorBlock(error));
            }
        };
    } catch (error) {
        if (!activeSheet(loading)) return;
        if (error.status === 401) askMaintenanceCode();
        else sheet("Maintenance", errorBlock(error));
    }
}

async function openMaintenanceAccount(id) {
    const path = `/maintenance/accounts/${id}`;
    const back = () => openMaintenance({ accountsOpen: true });
    const redraw = () => openMaintenanceAccount(id);
    const backButton = `<button type="button" class="button secondary" data-back>${icon("left")} Retour aux comptes</button>`;
    const loading = sheet("Compte", '<p class="empty">Chargement…</p>');
    try {
        const account = await api(path);
        if (!activeSheet(loading)) return;
        const visitors = account.visitors.map(visitor => `<li class="visitor-row info-block">
            <div><strong>Identifiant #${visitor.id}</strong><p class="muted small">${escapeHtml(visitor.ip)}</p>
                <p class="muted small">Dernière connexion · ${connectionTime(visitor.last_connected_at)}</p></div>
            <button type="button" class="button danger" data-delete-visitor="${visitor.id}"
                aria-label="Supprimer l’identifiant nº ${visitor.id}">${icon("trash")} Supprimer</button>
        </li>`).join("");
        const content = sheet(account.username, `<div class="stack">
            <h3>Identifiants de visite</h3>
            ${visitors ? `<ul class="visitor-list row-list">${visitors}</ul>` : '<p class="muted">Aucun identifiant de visite associé.</p>'}
            <div class="flow">${backButton}
                <button type="button" class="button danger" data-delete-account>${icon("trash")} Supprimer le compte</button>
            </div>
        </div>`, `Compte #${account.id}`);
        content.querySelector("[data-back]").onclick = back;

        async function remove(confirmation, endpoint, done, next) {
            try {
                await api(endpoint, "DELETE");
                toast(done);
                if (account.is_current && endpoint === path) location.replace("/");
                else if (activeSheet(confirmation)) await next();
            } catch (error) {
                if (error.status === 401 && activeSheet(confirmation)) askMaintenanceCode();
                else throw error;
            }
        }

        for (const button of content.querySelectorAll("[data-delete-visitor]")) {
            const visitor = button.dataset.deleteVisitor;
            button.onclick = () => confirmDelete({
                title: `Supprimer l’identifiant nº ${visitor}`,
                message: "Cet identifiant et son historique seront effacés. Un nouvel identifiant sera attribué à la prochaine visite depuis ce navigateur et cette adresse IP.",
                onCancel: redraw,
                onDelete: confirmation => remove(confirmation, `${path}/visitors/${visitor}`, "Identifiant supprimé.", redraw),
            });
        }
        content.querySelector("[data-delete-account]").onclick = () => confirmDelete({
            title: `Supprimer le compte ${account.username}`,
            message: "Le compte, ses identifiants et son historique seront effacés. Ses connexions seront révoquées."
                + (account.hosts_session ? " Le code de la session créée par ce compte restera utilisable." : "")
                + (account.is_current ? " Vous serez déconnecté." : ""),
            onCancel: redraw,
            onDelete: confirmation => remove(confirmation, path, "Compte supprimé.", back),
        });
    } catch (error) {
        if (!activeSheet(loading)) return;
        if (error.status === 401) askMaintenanceCode();
        else {
            const content = sheet("Compte", `<div class="stack">${errorBlock(error)}<div>${backButton}</div></div>`);
            content.querySelector("[data-back]").onclick = back;
        }
    }
}

export function showWelcome() {
    const content = sheet("Bienvenue sur la version 2.0 du site", `<div class="stack">
        <p>Mis à jour le <time datetime="2026-11-23">23/11/2026</time>.</p>
        <p class="version-label">${icon("check")} Version actuelle · <strong>2.1.63</strong></p>
        <div class="sheet-actions"><button type="button" class="button primary" data-continue>Continuer</button></div>
    </div>`);
    content.querySelector("[data-continue]").onclick = closeSheet;
}
