import { api, copyText, escapeHtml, field, formError, icon, input, sheet, submitForm, toast } from "./ui.js";

window.addEventListener("pageshow", event => {
    if (event.persisted) location.reload();
});

const authForm = document.querySelector("[data-account-form]");
if (authForm) {
    const switchMode = document.querySelector("[data-switch-account]");
    const submit = authForm.querySelector('[type="submit"]');
    let register = false;
    switchMode.onclick = () => {
        register = !register;
        const title = register ? "Créer un compte" : "Se connecter";
        document.querySelector("#auth-title").textContent = title;
        document.querySelector("[data-account-prompt]").textContent = register ? "Déjà un compte ?" : "Première visite ?";
        authForm.elements.password.value = "";
        authForm.elements.password.autocomplete = register ? "new-password" : "current-password";
        document.querySelector("[data-password-hint]").hidden = !register;
        authForm.querySelector("[data-error]").hidden = true;
        submit.textContent = title;
        switchMode.textContent = register ? "Se connecter" : "Créer un compte";
        authForm.elements.username.focus();
    };
    submitForm(authForm, async data => {
        switchMode.disabled = true;
        try {
            await api(register ? "/account/register" : "/account/login", "POST", data);
            location.reload();
        } finally {
            switchMode.disabled = false;
        }
    });
}

function joinWorkspace() {
    const content = sheet("Rejoindre une session", `<form class="stack">
        ${field("Code de connexion", '<input name="code" required minlength="8" maxlength="8" autocapitalize="characters" autocomplete="off" spellcheck="false">')}
        ${formError}
        <div class="sheet-actions"><button class="button primary" type="submit">Rejoindre</button></div>
    </form>`, "Vous accéderez au planning, aux notes, aux événements et aux tâches de cette session.");
    submitForm(content.querySelector("form"), async data => {
        await api("/account/join", "POST", data);
        location.reload();
    });
}

function bindAccountActions(section) {
    const actions = [["share", "/reglages"], ["leave", "/"], ["logout", "/"]];
    const errorOutput = section.querySelector("[data-error]");
    for (const [action, destination] of actions) {
        const button = section.querySelector(`[data-${action}]`);
        if (!button) continue;
        button.onclick = async () => {
            const controls = [...section.querySelectorAll("button:enabled")];
            controls.forEach(control => { control.disabled = true; });
            errorOutput.hidden = true;
            try {
                await api(`/account/${action}`, "POST");
                location.replace(destination);
            } catch (error) {
                errorOutput.textContent = error.message;
                errorOutput.hidden = false;
                controls.forEach(control => { control.disabled = false; });
            }
        };
    }
    section.querySelector("[data-join]")?.addEventListener("click", joinWorkspace);
}

const sessionChoice = document.querySelector("[data-session-choice]");
if (sessionChoice) bindAccountActions(sessionChoice);

export function renderAccountSettings(host, account, page) {
    if (page === "profil") {
        const initials = Array.from(account.username).slice(0, 2).join("").toLocaleUpperCase("fr");
        host.innerHTML = `<div class="settings-profile">
            <span class="settings-avatar" aria-hidden="true">${escapeHtml(initials)}</span>
            <div><p class="muted small">Nom d’utilisateur</p><strong>${escapeHtml(account.username)}</strong></div>
        </div>
        ${formError}
        <div><button class="button secondary" type="button" data-logout>Se déconnecter</button></div>`;
        bindAccountActions(host);
        return;
    }

    if (page === "apparence") {
        host.innerHTML = `<form class="stack">
            ${field("Nom affiché du site", input("name", account.site_name, 'maxlength="40"'))}
            <p class="muted small">Ce nom apparaît dans votre en-tête et dans l’onglet du navigateur. Videz le champ pour rétablir ${escapeHtml(document.body.dataset.defaultSiteName)}.</p>
            ${formError}
            <div><button class="button primary" type="submit">Enregistrer le nom</button></div>
        </form>`;
        submitForm(host.querySelector("form"), async ({ name }) => {
            await api("/account/site-name", "PUT", { name });
            location.reload();
        });
        return;
    }

    if (!account.code) {
        host.innerHTML = `<p class="muted">Quitter la session vous ramènera à l’écran de choix des sessions.</p>
            ${formError}
            <div><button class="button secondary" type="button" data-leave>Quitter la session</button></div>`;
        bindAccountActions(host);
        return;
    }

    host.innerHTML = `<div class="settings-invitation field">
        <label for="session-code">Code de connexion</label>
        <div class="settings-code-actions">
            <input id="session-code" class="session-code" value="${escapeHtml(account.code)}" readonly spellcheck="false">
            <button class="button primary" type="button" data-copy>Copier le code</button>
        </div>
    </div>
    <p class="muted small">Les personnes qui rejoignent avec ce code peuvent consulter et modifier les données de votre session.</p>`;
    host.querySelector("[data-copy]").onclick = async () => {
        const copied = await copyText(host.querySelector("#session-code"));
        toast(copied ? "Code copié." : "Sélectionnez Copier pour récupérer le code.");
    };
}
