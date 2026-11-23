import { capitalize, formatDate, todayIn } from "./calendar.js";
import { renderCourses } from "./courses.js";
import { openParentSettings, renderPlanning, renderSettings } from "./custody.js";
import { renderEvents, renderNotes } from "./records.js";
import { askMaintenanceCode, showWelcome } from "./maintenance.js";
import { startReminders } from "./reminders.js";
import { openSearch, openTrash } from "./organizer.js";
import { renderTasks } from "./tasks.js";
import { api, closeSheet, empty, errorBlock, icon } from "./ui.js";

const main = document.querySelector("#main");
const page = document.querySelector("#page");
const home = page.cloneNode(true);
const builtInZone = "Europe/Paris";
let session = { settings: null, today: todayIn(builtInZone) };
let sessionError;
let ready = false;
let current = location.pathname;
let visit = 0;

const positions = {
    "/planning": { day: null, view: "month" },
    "/evenements": { day: null, view: "month" },
};
const titles = {
    "/": "Planning familial",
    "/planning": "Mon planning",
    "/evenements": "Mes événements",
    "/notes": "Notes",
    "/a-faire": "À faire",
    "/cours": "Cours",
    "/reglages": "Réglages",
};

function updateNavigation() {
    document.title = current === "/" ? "Naoning · Planning familial" : `${titles[current]} · Naoning`;
    document.querySelectorAll('.tab-bar [data-route], .settings-link').forEach(link => {
        if (link.dataset.route === current) link.setAttribute("aria-current", "page");
        else link.removeAttribute("aria-current");
    });
}

function updateHome() {
    const date = page.querySelector("#hero-date");
    if (!date) return;
    date.innerHTML = `${icon("calendar")}<span>${capitalize(formatDate(session.today, {
        weekday: "long", day: "numeric", month: "long",
    }))}</span>`;
    date.hidden = false;
    const setup = page.querySelector("#home-setup");
    setup.innerHTML = ready && !session.settings
        ? `<button type="button" class="button secondary setup-link">${icon("settings")} Configurer le planning</button>`
        : "";
    const trigger = setup.querySelector("button");
    if (trigger) trigger.onclick = setupPlanning;
    if (sessionError) setup.innerHTML = `${errorBlock(sessionError)}
        <button class="button secondary" type="button" data-retry-session>Réessayer</button>`;
    const retry = setup.querySelector("[data-retry-session]");
    if (retry) retry.onclick = connect;
}

async function setupPlanning() {
    openParentSettings(session, async () => {
        await loadSession();
        if (current === "/" || current === "/reglages") move("/planning");
        else render();
    });
}

async function loadSession() {
    session = await api("/session");
    sessionError = undefined;
    ready = true;
}

function selectedRecord(key) {
    const value = Number(new URL(location.href).searchParams.get(key));
    return Number.isSafeInteger(value) && value > 0 ? value : null;
}

function render() {
    updateNavigation();
    if (current === "/") {
        if (!page.querySelector(".home-hero")) {
            page.firstElementChild?.dispatchEvent(new Event("tempo:leave"));
            page.replaceChildren(...Array.from(home.children, child => child.cloneNode(true)));
            page.classList.remove("page-enter");
        }
        updateHome();
        return;
    }
    page.firstElementChild?.dispatchEvent(new Event("tempo:leave"));
    const view = document.createElement("div");
    view.className = "page-enter";
    page.replaceChildren(view);
    if (!ready) {
        view.innerHTML = sessionError
            ? `${errorBlock(sessionError)}<button class="button secondary" type="button" data-retry-session>Réessayer</button>`
            : '<p class="empty panel">Connexion à Naoning…</p>';
        const retry = view.querySelector("[data-retry-session]");
        if (retry) retry.onclick = connect;
        return;
    }
    if (positions[current]) positions[current].day ??= session.today;
    if (current === "/planning") {
        renderPlanning(view, session, positions[current], setupPlanning);
    } else if (current === "/evenements") {
        renderEvents(view, session, positions[current], selectedRecord("event"));
    } else if (current === "/notes") {
        const preferredZone = session.timezone ?? builtInZone;
        let zone = preferredZone;
        try { new Intl.DateTimeFormat("fr-FR", { timeZone: preferredZone }); }
        catch { zone = builtInZone; }
        renderNotes(view, zone, selectedRecord("note"));
    } else if (current === "/a-faire") {
        renderTasks(view, selectedRecord("task"));
    } else if (current === "/cours") {
        renderCourses(view, selectedRecord("course"));
    } else if (current === "/reglages") {
        renderSettings(view, session, setupPlanning, async () => {
            await loadSession();
            render();
        });
        view.insertAdjacentHTML("beforeend", `<section class="view-section section-panel panel">
            <div class="flow"><button type="button" class="button secondary" data-trash>${icon("trash")} Corbeille</button>
            <button type="button" class="button secondary" data-maintenance>${icon("settings")} Maintenance</button></div>
        </section>`);
        view.querySelector("[data-trash]").onclick = openTrash;
        view.querySelector("[data-maintenance]").onclick = askMaintenanceCode;
    } else {
        view.innerHTML = empty("Page introuvable");
    }
}

async function connect() {
    try {
        await loadSession();
    } catch (error) {
        sessionError = error;
    }
    render();
}

function motionEnabled() {
    return typeof Element.prototype.animate === "function" && !matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function transitionCard(card, backwards) {
    const rect = card.getBoundingClientRect();
    if (rect.bottom <= 0 || rect.top >= innerHeight) return null;
    const cover = document.createElement("div");
    cover.className = `space-transition ${[...card.classList].find(name => name.startsWith("tone-"))}`;
    cover.setAttribute("aria-hidden", "true");
    const initial = `inset(${rect.top}px ${innerWidth - rect.right}px ${innerHeight - rect.bottom}px ${rect.left}px round 1.4rem)`;
    const full = "inset(0px 0px 0px 0px round 0rem)";
    document.body.append(cover);
    const sequence = backwards ? [full, initial] : [initial, full];
    const animation = cover.animate(sequence.map(clipPath => ({ clipPath })), {
        duration: backwards ? 245 : 290, easing: "cubic-bezier(.3,.72,.26,1)", fill: "both",
    });
    return { cover, animation };
}

function scrollToTopAndFocus() {
    window.scrollTo(0, 0);
    main.focus({ preventScroll: true });
}

async function move(destination, { card, fromHistory = false } = {}) {
    const target = new URL(destination, location.href);
    const next = target.pathname;
    if (!fromHistory && next === current && target.search === location.search) {
        if (target.search) { closeSheet(); render(); }
        return;
    }
    const ticket = ++visit;
    closeSheet();
    const previous = current;
    const animate = motionEnabled();
    const incoming = animate && card ? transitionCard(card, false) : null;
    if (!fromHistory) history.pushState({}, "", target);
    if (incoming) await incoming.animation.finished;
    if (ticket !== visit) {
        incoming?.cover.remove();
        return;
    }
    current = next;
    render();
    scrollToTopAndFocus();
    const origin = next === "/" && page.querySelector(`.space-card[data-route="${previous}"]`);
    const returning = animate && origin && !incoming ? transitionCard(origin, true) : null;
    if (returning) {
        await returning.animation.finished;
        returning.cover.remove();
    }
    if (incoming) {
        await incoming.cover.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 145, fill: "both" }).finished;
        incoming.cover.remove();
    }
}

document.addEventListener("click", event => {
    const link = event.target.closest("[data-route]");
    if (!link || event.button !== 0 || event.metaKey || event.altKey || event.ctrlKey || event.shiftKey) return;
    event.preventDefault();
    const animated = link.matches(".space-card, .tab-bar a");
    move(link.href, { card: animated ? link : null });
});
document.querySelector("[data-search]").onclick = openSearch;
window.addEventListener("popstate", () => move(location.href, { fromHistory: true }));
window.addEventListener("naoning:data-reset", connect);

render();
connect();
const entrance = page.querySelector(".space-list");
const landCards = () => entrance?.classList.add("space-list-landing");
if (document.body.dataset.welcome === "yes") {
    document.querySelector("#sheet").addEventListener("close", landCards, { once: true });
    showWelcome();
} else {
    landCards();
}
startReminders(id => move(`/evenements?event=${id}`));
