const dialog = document.querySelector("#sheet");
const toasts = document.querySelector("#toasts");
let fieldCount = 0;

export function escapeHtml(value) {
    const characters = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
    return String(value ?? "").replace(/[&<>"']/g, character => characters[character]);
}

export function icon(name) {
    return `<svg class="icon" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
}

export function safeColor(value, fallback = "#9165d0") {
    return /^#[\da-f]{6}$/i.test(value ?? "") ? value : fallback;
}

export function colorDot(value) {
    return `<span class="dot" style="--item-color:${safeColor(value)}" aria-hidden="true"></span>`;
}

export async function api(path, method = "GET", data) {
    let response;
    try {
        const headers = { Accept: "application/json" };
        const multipart = data instanceof FormData;
        if (method !== "GET") headers["X-Tempo-Request"] = "1";
        if (data !== undefined && !multipart) headers["Content-Type"] = "application/json";
        response = await fetch(`/api${path}`, {
            method,
            headers,
            body: multipart || data === undefined ? data : JSON.stringify(data),
            cache: "no-store",
        });
    } catch {
        throw new Error("Le serveur Naoning est injoignable. Réessayez.");
    }
    if (response.status === 204) return null;
    const body = await response.json().catch(() => null);
    if (!response.ok || body === null) {
        const error = new Error(body?.error || "Une erreur est survenue. Réessayez.");
        error.status = response.status;
        throw error;
    }
    return body;
}

export function pageHeading(title, symbol, tone, action = "") {
    return `<div class="page-heading"><div class="page-title ${tone}">
        <span class="space-icon">${icon(symbol)}</span><h1>${title}</h1></div>${action}</div>`;
}

export function empty(title, content = "", action = "") {
    return `<div class="empty panel"><h2>${title}</h2>${content ? `<p>${content}</p>` : ""}${action}</div>`;
}

export function errorBlock(error) {
    return `<p class="empty error" role="alert">${escapeHtml(error.message)}</p>`;
}

export function field(label, control) {
    const id = `field-${++fieldCount}`;
    const labelled = control.replace(/^<(input|textarea|select)\b/, `<$1 id="${id}"`);
    return `<div class="field"><label for="${id}">${label}</label>${labelled}</div>`;
}

export function input(name, value, attributes = "") {
    return `<input name="${name}" value="${escapeHtml(value)}" ${attributes}>`;
}

export function textarea(name, value, attributes = "") {
    return `<textarea name="${name}" ${attributes}>\n${escapeHtml(value)}</textarea>`;
}

function styleDropdown(select) {
    const wrapper = document.createElement("div");
    wrapper.className = "dropdown";
    select.before(wrapper);
    wrapper.append(select);
    select.hidden = true;
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "dropdown-trigger";
    trigger.id = `${select.id}-trigger`;
    trigger.setAttribute("aria-expanded", "false");
    trigger.setAttribute("aria-haspopup", "listbox");
    const list = document.createElement("div");
    list.id = `${select.id}-list`;
    list.className = "dropdown-list";
    list.setAttribute("role", "listbox");
    list.hidden = true;
    trigger.setAttribute("aria-controls", list.id);
    const label = select.labels?.[0];
    if (label) {
        label.htmlFor = trigger.id;
        list.setAttribute("aria-label", label.textContent);
    }
    wrapper.append(trigger, list);
    const close = (focus = false) => {
        list.hidden = true;
        trigger.setAttribute("aria-expanded", "false");
        if (focus) trigger.focus();
    };
    function sync() {
        trigger.innerHTML = `<span>${escapeHtml(select.selectedOptions[0]?.textContent.trim() || "Choisir")}</span>${icon("right")}`;
        trigger.disabled = select.disabled;
        list.replaceChildren(...Array.from(select.options, (option, index) => {
            const button = document.createElement("button");
            button.type = "button";
            button.tabIndex = -1;
            button.disabled = option.disabled;
            button.setAttribute("role", "option");
            button.setAttribute("aria-selected", String(option.selected));
            button.textContent = option.textContent.trim();
            button.onclick = () => {
                select.selectedIndex = index;
                select.dispatchEvent(new Event("input", { bubbles: true }));
                select.dispatchEvent(new Event("change", { bubbles: true }));
                close(true);
            };
            return button;
        }));
    }
    function options() { return [...list.querySelectorAll("button:enabled")]; }
    function open(direction) {
        wrapper.closest("dialog").querySelectorAll(".dropdown-trigger[aria-expanded=true]").forEach(other => {
            if (other !== trigger) other.click();
        });
        list.hidden = false;
        trigger.setAttribute("aria-expanded", "true");
        const choices = options();
        (direction === "last" ? choices.at(-1) : list.querySelector('[aria-selected="true"]:enabled') || choices[0])?.focus();
    }
    trigger.onclick = () => list.hidden ? open() : close(true);
    wrapper.addEventListener("focusout", event => {
        if (!wrapper.contains(event.relatedTarget)) close();
    });
    wrapper.addEventListener("keydown", event => {
        if (event.key === "Escape" && !list.hidden) {
            event.preventDefault();
            close(true);
            return;
        }
        if (!["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        if (list.hidden) { open(event.key === "End" ? "last" : undefined); return; }
        const choices = options();
        const index = choices.indexOf(document.activeElement);
        const step = event.key === "ArrowUp" ? -1 : 1;
        const next = event.key === "Home" ? 0 : event.key === "End" ? choices.length - 1
            : (index + step + choices.length) % choices.length;
        choices[next]?.focus();
    });
    select.addEventListener("change", sync);
    select.addEventListener("invalid", event => {
        event.preventDefault();
        open();
    });
    new MutationObserver(sync).observe(select, { subtree: true, childList: true, characterData: true, attributes: true });
    sync();
}

export function sheet(title, body, subtitle = "") {
    dialog.innerHTML = `<div class="sheet-window">
        <header class="sheet-header"><div>
            <h2 id="sheet-title" tabindex="-1">${escapeHtml(title)}</h2>
            ${subtitle ? `<p>${escapeHtml(subtitle)}</p>` : ""}
        </div><button type="button" class="icon-button" data-close aria-label="Fermer">${icon("close")}</button></header>
        ${body}
    </div>`;
    dialog.querySelectorAll("select").forEach(styleDropdown);
    dialog.querySelector("[data-close]").onclick = closeSheet;
    if (!dialog.open) {
        dialog.showModal();
        document.body.classList.add("sheet-open");
    }
    dialog.scrollTop = 0;
    dialog.querySelector("#sheet-title").focus({ preventScroll: true });
    return dialog.firstElementChild;
}

export function activeSheet(container) {
    return dialog.open && dialog.contains(container);
}

export function closeSheet() {
    if (dialog.open) dialog.close();
    document.body.classList.remove("sheet-open");
}

dialog.addEventListener("close", () => {
    if (!dialog.open) document.body.classList.remove("sheet-open");
});
dialog.addEventListener("click", event => {
    if (event.target === dialog) closeSheet();
});

export const formError = '<p class="error" data-error role="alert" hidden></p>';

export function submitForm(form, handler, output = form.querySelector("[data-error]")) {
    form.addEventListener("submit", async event => {
        event.preventDefault();
        const submitter = event.submitter ?? form.querySelector('[type="submit"]');
        if (submitter.disabled) return;
        submitter.disabled = true;
        output.hidden = true;
        try {
            await handler(Object.fromEntries(new FormData(form)), submitter);
        } catch (error) {
            output.textContent = error.message;
            output.hidden = false;
        } finally {
            submitter.disabled = false;
        }
    });
}

export function confirmDelete({ title, message, onDelete, onCancel = closeSheet }) {
    const content = sheet(title, `<form class="stack">
        <p>${escapeHtml(message)}</p>${formError}
        <div class="sheet-actions">
            <button class="button secondary" type="button" data-cancel>Annuler</button>
            <button class="button danger" type="submit">Supprimer</button>
        </div></form>`);
    content.querySelector("[data-cancel]").onclick = onCancel;
    submitForm(content.querySelector("form"), () => onDelete(content));
}

export function toast(message, action) {
    const element = document.createElement("div");
    element.className = "toast";
    element.innerHTML = `${icon(action ? "bell" : "check")}<span>${escapeHtml(message)}</span>
        ${action ? '<button type="button" class="button secondary" data-action>Voir</button>' : ""}
        <button type="button" class="icon-button" data-dismiss aria-label="Fermer le message">${icon("close")}</button>`;
    element.querySelector("[data-dismiss]").onclick = () => element.remove();
    if (action) {
        element.querySelector("[data-action]").onclick = () => {
            element.remove();
            action();
        };
    } else {
        window.setTimeout(() => element.remove(), 4700);
    }
    toasts.append(element);
}
