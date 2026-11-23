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
        if (document.body.dataset.account) headers["X-Tempo-Account"] = document.body.dataset.account;
        if (method !== "GET") headers["X-Tempo-Request"] = "1";
        if (data !== undefined && !multipart) headers["Content-Type"] = "application/json";
        response = await fetch(`/api${path}`, {
            method,
            headers,
            body: multipart || data === undefined ? data : JSON.stringify(data),
            cache: "no-store",
        });
    } catch {
        throw new Error("Le serveur est injoignable. Réessayez.");
    }
    if (response.status === 204) return null;
    const body = await response.json().catch(() => null);
    if (!response.ok || body === null) {
        if (body?.refresh && document.body.dataset.account) location.reload();
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

export async function copyText(control) {
    if (navigator.clipboard) {
        try {
            await navigator.clipboard.writeText(control.value);
            return true;
        } catch {
            // Use text selection when the clipboard API is unavailable.
        }
    }
    const details = control.closest("details");
    if (details) details.open = true;
    control.focus();
    control.select();
    try { return document.execCommand("copy"); }
    catch { return false; }
}

const styledSelects = new WeakMap();
let activeDropdown;

for (const event of ["pointerdown", "focusin"]) {
    document.addEventListener(event, ({ target }) => {
        if (activeDropdown && !activeDropdown.wrapper.contains(target)) activeDropdown.close();
    });
}
document.addEventListener("scroll", () => activeDropdown?.position(), true);
window.addEventListener("resize", () => activeDropdown?.position());
window.visualViewport?.addEventListener("resize", () => activeDropdown?.position());
window.visualViewport?.addEventListener("scroll", () => activeDropdown?.position());

function choiceKey(value) {
    return value.normalize("NFD").replace(/\p{M}/gu, "").trim().toLowerCase();
}

function wrapChoice(control) {
    const wrapper = document.createElement("div");
    wrapper.className = "dropdown";
    control.before(wrapper);
    wrapper.append(control);
    return wrapper;
}

function choicePopup(wrapper, trigger, onPick, label, toggle = trigger) {
    const list = document.createElement("div");
    list.className = "dropdown-list";
    list.id = `${trigger.id}-list`;
    list.setAttribute("role", "listbox");
    if (label) list.setAttribute("aria-labelledby", label.id);
    list.hidden = true;
    const floating = typeof list.showPopover === "function";
    if (floating) list.setAttribute("popover", "manual");
    wrapper.append(list);

    trigger.setAttribute("role", "combobox");
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-controls", list.id);
    toggle.setAttribute("aria-controls", list.id);
    let entries = [];
    let active = -1;

    function expanded(value) {
        trigger.setAttribute("aria-expanded", String(value));
        toggle.setAttribute("aria-expanded", String(value));
    }
    expanded(false);

    function close() {
        if (activeDropdown !== popup) return;
        activeDropdown = undefined;
        if (floating && list.matches(":popover-open")) list.hidePopover();
        list.hidden = true;
        trigger.removeAttribute("aria-activedescendant");
        expanded(false);
    }

    function position() {
        if (!trigger.isConnected || !trigger.getClientRects().length) {
            close();
            return;
        }
        if (!floating) return;
        const rect = trigger.getBoundingClientRect();
        const viewport = window.visualViewport;
        const viewportTop = viewport?.offsetTop ?? 0;
        const viewportBottom = viewportTop + (viewport?.height ?? window.innerHeight);
        if (rect.bottom <= viewportTop || rect.top >= viewportBottom) {
            close();
            return;
        }
        const gap = 6;
        const above = rect.top - viewportTop - gap;
        const below = viewportBottom - rect.bottom - gap;
        const viewportLeft = viewport?.offsetLeft ?? 0;
        const viewportWidth = viewport?.width ?? window.innerWidth;
        const width = Math.min(Math.max(rect.width, 220), viewportWidth - 16);
        list.style.width = `${width}px`;
        list.style.left = `${Math.max(viewportLeft + 8, Math.min(rect.left, viewportLeft + viewportWidth - width - 8))}px`;
        const opensAbove = below < Math.min(list.scrollHeight + 2, 272) && above > below;
        list.style.maxHeight = `${Math.max(0, Math.min(272, (opensAbove ? above : below) - 6))}px`;
        list.style.top = `${opensAbove ? rect.top - gap - list.offsetHeight : rect.bottom + gap}px`;
    }

    function highlight(index) {
        const option = list.children[index];
        if (!option || entries[index].disabled) return;
        list.children[active]?.removeAttribute("data-highlighted");
        active = index;
        option.setAttribute("data-highlighted", "");
        trigger.setAttribute("aria-activedescendant", option.id);
        const top = option.offsetTop;
        const bottom = top + option.offsetHeight;
        if (top < list.scrollTop) list.scrollTop = top;
        if (bottom > list.scrollTop + list.clientHeight) list.scrollTop = bottom - list.clientHeight;
    }

    function pick(index) {
        const entry = entries[index];
        if (!entry || entry.disabled) return;
        close();
        onPick(entry);
    }

    function show(options) {
        if (!options.length || !trigger.getClientRects().length) { close(); return; }
        if (activeDropdown !== popup) activeDropdown?.close();
        entries = options;
        active = -1;
        trigger.removeAttribute("aria-activedescendant");
        list.replaceChildren(...options.map((entry, index) => {
            const option = document.createElement("div");
            option.id = `${list.id}-option-${index}`;
            option.setAttribute("role", "option");
            option.setAttribute("aria-selected", String(entry.selected));
            if (entry.disabled) option.setAttribute("aria-disabled", "true");
            option.innerHTML = `<span></span>${icon("check")}`;
            option.firstElementChild.textContent = entry.label;
            option.onclick = () => pick(index);
            return option;
        }));
        if (activeDropdown !== popup) {
            activeDropdown = popup;
            list.hidden = false;
            if (floating) list.showPopover();
            expanded(true);
        }
        position();
        if (activeDropdown !== popup) return;
        const selected = options.findIndex(entry => entry.selected && !entry.disabled);
        highlight(selected >= 0 ? selected : options.findIndex(entry => !entry.disabled));
    }

    function move(key) {
        const available = entries.map((entry, index) => entry.disabled ? -1 : index).filter(index => index >= 0);
        const current = available.indexOf(active);
        if (key === "Home") highlight(available[0]);
        else if (key === "End") highlight(available.at(-1));
        else if (key === "ArrowDown") highlight(available[Math.min(current + 1, available.length - 1)]);
        else highlight(available[Math.max(0, current - 1)]);
    }

    list.addEventListener("mousedown", event => {
        if (event.target.closest('[role="option"]')) event.preventDefault();
    });
    const popup = {
        wrapper, close, position, show, move,
        isOpen: () => activeDropdown === popup,
        pick: () => pick(active),
        find: prefix => highlight(entries.findIndex(entry => !entry.disabled && choiceKey(entry.label).startsWith(prefix))),
    };
    return popup;
}

function choiceKeys(trigger, popup, open, editable = false) {
    let search = "";
    let lastKey = 0;
    trigger.addEventListener("keydown", event => {
        const { key } = event;
        if (key === "Tab") { popup.close(); return; }
        if (key === "Escape" && popup.isOpen()) {
            event.preventDefault();
            event.stopPropagation();
            popup.close();
            return;
        }
        if (event.isComposing) return;
        if (popup.isOpen() && (key === "Enter" || (!editable && key === " "))) {
            event.preventDefault();
            popup.pick();
            return;
        }
        const edge = !editable && (key === "Home" || key === "End");
        if (key === "ArrowDown" || key === "ArrowUp" || edge) {
            event.preventDefault();
            if (popup.isOpen()) popup.move(key);
            else {
                open();
                if (edge) popup.move(key);
            }
            return;
        }
        if (!editable && key.length === 1 && key !== " " && !event.ctrlKey && !event.metaKey && !event.altKey) {
            event.preventDefault();
            const wasOpen = popup.isOpen();
            if (!wasOpen) open();
            const now = performance.now();
            search = (wasOpen && now - lastKey < 700 ? search : "") + choiceKey(key);
            lastKey = now;
            popup.find(search);
        }
    });
}

function changeChoice(control) {
    control.dispatchEvent(new Event("input", { bubbles: true }));
    control.dispatchEvent(new Event("change", { bubbles: true }));
}

export function styleDropdown(select) {
    const styled = styledSelects.get(select);
    if (styled) {
        styled.sync();
        return styled.trigger;
    }
    if (select.multiple || select.size > 1) return select;

    const wrapper = wrapChoice(select);
    select.hidden = true;
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "dropdown-trigger";
    trigger.id = `${select.id}-trigger`;
    trigger.innerHTML = `<span></span>${icon("right")}`;
    wrapper.append(trigger);
    const label = select.labels?.[0];
    if (label) {
        label.id ||= `${select.id}-label`;
        label.htmlFor = trigger.id;
        trigger.setAttribute("aria-labelledby", label.id);
    }

    const popup = choicePopup(wrapper, trigger, entry => {
        if (select.selectedIndex === entry.index) return;
        select.selectedIndex = entry.index;
        sync();
        changeChoice(select);
    }, label);
    const open = () => popup.show(Array.from(select.options, (option, index) => ({
        index, label: option.label, selected: option.selected, disabled: option.matches(":disabled"),
    })));
    function sync() {
        trigger.firstElementChild.textContent = select.selectedOptions[0]?.label.trim() || "Choisir";
        trigger.disabled = select.matches(":disabled");
        if (trigger.disabled) popup.close();
        else if (popup.isOpen()) open();
    }
    trigger.onclick = () => popup.isOpen() ? popup.close() : open();
    choiceKeys(trigger, popup, open);
    select.addEventListener("change", sync);
    select.addEventListener("invalid", event => {
        event.preventDefault();
        trigger.focus();
        open();
    });
    new MutationObserver(sync).observe(select, { subtree: true, childList: true, characterData: true, attributes: true });
    styledSelects.set(select, { trigger, sync });
    sync();
    return trigger;
}

function styleSuggestions(input) {
    const options = input.list?.options;
    if (!options?.length) return;
    const wrapper = wrapChoice(input);
    wrapper.classList.add("dropdown-suggest");
    input.removeAttribute("list");
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.tabIndex = -1;
    toggle.className = "dropdown-toggle";
    toggle.innerHTML = icon("right");
    const label = input.labels?.[0];
    if (label) label.id ||= `${input.id}-label`;
    toggle.setAttribute("aria-label", label ? `Suggestions pour ${label.textContent.trim()}` : "Suggestions");
    input.setAttribute("aria-autocomplete", "list");
    wrapper.append(toggle);

    let picking = false;
    const popup = choicePopup(wrapper, input, entry => {
        input.focus({ preventScroll: true });
        if (input.value === entry.value) return;
        input.value = entry.value;
        picking = true;
        changeChoice(input);
        picking = false;
    }, label, toggle);
    const open = (query = "") => {
        const entries = Array.from(options, option => ({
            value: option.value, label: option.label || option.value,
            selected: option.value === input.value, disabled: option.disabled,
        }));
        popup.show(entries.filter(entry => choiceKey(entry.label).includes(query)));
    };
    toggle.onclick = () => {
        if (input.disabled) return;
        input.focus({ preventScroll: true });
        if (popup.isOpen()) popup.close();
        else open();
    };
    choiceKeys(input, popup, open, true);
    input.addEventListener("input", () => {
        if (!picking) open(choiceKey(input.value));
    });
}

export function sheet(title, body, subtitle = "") {
    activeDropdown?.close();
    dialog.innerHTML = `<div class="sheet-window">
        <header class="sheet-header"><div>
            <h2 id="sheet-title" tabindex="-1">${escapeHtml(title)}</h2>
            ${subtitle ? `<p>${escapeHtml(subtitle)}</p>` : ""}
        </div><button type="button" class="icon-button" data-close aria-label="Fermer">${icon("close")}</button></header>
        ${body}
    </div>`;
    dialog.querySelectorAll("select").forEach(styleDropdown);
    dialog.querySelectorAll("input[list]").forEach(styleSuggestions);
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
    activeDropdown?.close();
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
