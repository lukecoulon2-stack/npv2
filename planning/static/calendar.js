import { api, colorDot, errorBlock, escapeHtml, icon, safeColor } from "./ui.js";

export const WEEKDAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"];
const ABBREVIATED = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
const DAY_MS = 86_400_000;

function utcDate(year, month, day) {
    const date = new Date(0);
    date.setUTCFullYear(year, month, day);
    return date;
}

function parseDay(day) {
    return new Date(`${day}T00:00:00Z`);
}

function dateISO(date) {
    const year = date.getUTCFullYear();
    return year >= 1 && year <= 9999 ? date.toISOString().slice(0, 10) : null;
}

function addDays(day, amount) {
    return dateISO(new Date(parseDay(day).getTime() + amount * DAY_MS));
}

function weekday(day) {
    return (parseDay(day).getUTCDay() + 6) % 7;
}

function longFormat(day, options) {
    return new Intl.DateTimeFormat("fr-FR", { timeZone: "UTC", ...options }).format(parseDay(day));
}

export function formatDate(day, options = { weekday: "long", day: "numeric", month: "long", year: "numeric" }) {
    return longFormat(day, options);
}

export function capitalize(value) {
    return value.charAt(0).toLocaleUpperCase("fr-FR") + value.slice(1);
}

export function todayIn(timezone = "Europe/Paris", fallback) {
    try {
        const parts = new Intl.DateTimeFormat("fr-FR", {
            timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit",
        }).formatToParts(new Date());
        const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
        return `${values.year}-${values.month}-${values.day}`;
    } catch {
        return fallback ?? new Date().toISOString().slice(0, 10);
    }
}

export function parents(settings) {
    return [
        { id: 1, name: settings.name_a, color: settings.color_a },
        { id: 2, name: settings.name_b, color: settings.color_b },
    ];
}

function monthCells(year, month) {
    const first = dateISO(utcDate(year, month, 1));
    const offset = weekday(first);
    const last = utcDate(year, month + 1, 0).getUTCDate();
    return Array.from({ length: Math.ceil((last + offset) / 7) * 7 }, (_, index) => {
        const number = index - offset + 1;
        return { day: addDays(first, number - 1), outside: number < 1 || number > last };
    });
}

function viewRange(day, view) {
    const anchor = parseDay(day);
    const year = anchor.getUTCFullYear();
    const month = anchor.getUTCMonth();
    if (view === "year") {
        return { start: `${day.slice(0, 4)}-01-01`, end: `${day.slice(0, 4)}-12-31`, title: String(year), year };
    }
    if (view === "month") {
        const cells = monthCells(year, month);
        const dates = cells.filter(cell => cell.day);
        return {
            start: dates[0].day, end: dates.at(-1).day, cells,
            firstInView: dateISO(utcDate(year, month, 1)), lastInView: dateISO(utcDate(year, month + 1, 0)),
            title: capitalize(longFormat(day, { month: "long", year: "numeric" })),
        };
    }
    const offset = weekday(day);
    const cells = Array.from({ length: 7 }, (_, index) => ({ day: addDays(day, index - offset) }));
    const dates = cells.filter(cell => cell.day);
    const start = dates[0].day;
    const end = dates.at(-1).day;
    const endLabel = longFormat(end, { day: "numeric", month: "long", year: "numeric" });
    const startLabel = start.slice(0, 7) === end.slice(0, 7)
        ? String(parseDay(start).getUTCDate())
        : longFormat(start, { day: "numeric", month: "short", ...(start.slice(0, 4) === end.slice(0, 4) ? {} : { year: "numeric" }) });
    return { start, end, cells, title: `${startLabel} – ${endLabel}` };
}

function shiftPosition(position, delta) {
    const { day, view } = position;
    if (view === "week") {
        const monday = addDays(day, -weekday(day)) ?? day;
        return addDays(monday, delta * 7);
    }
    const date = parseDay(day);
    const year = date.getUTCFullYear();
    const month = date.getUTCMonth();
    return view === "month" ? dateISO(utcDate(year, month + delta, 1)) : dateISO(utcDate(year + delta, 0, 1));
}

function eventDays(events) {
    const byDay = new Map();
    for (const event of events) {
        if (!byDay.has(event.day)) byDay.set(event.day, []);
        byDay.get(event.day).push(event);
    }
    return byDay;
}

export function parentMarks(list) {
    const initials = list.map(parent => Array.from(parent.name)[0].toLocaleUpperCase("fr-FR"));
    return initials[0] === initials[1] ? ["1", "2"] : initials;
}

function custodyDay(item, list, marksByParent) {
    if (!item) return { marks: "", meta: "", color: "", description: "" };
    const parent = list[item.parent - 1];
    const mark = marksByParent[item.parent - 1];
    const marks = `${item.carers.length ? icon("user") : ""}${item.note_count ? icon("note") : ""}`;
    const meta = `<span class="day-person">${escapeHtml(parent.name)}</span>
        <span class="day-person-short" aria-hidden="true">${escapeHtml(mark)}</span>`;
    const description = [
        parent.name, item.custom ? "attribution manuelle" : "",
        item.carers.length ? `garde ${item.carers.join(", ")}` : "",
        item.note_count ? `${item.note_count} note${item.note_count > 1 ? "s" : ""}` : "",
    ].filter(Boolean).join(", ");
    return { marks, meta, color: safeColor(parent.color), description };
}

function appointmentDay(items) {
    const count = items?.length ?? 0;
    const marks = items?.slice(0, 2).map(item => colorDot(item.color)).join("") ?? "";
    return {
        marks: marks + (count > 2 ? `<span class="more-count">+${count - 2}</span>` : ""),
        meta: "", color: count ? safeColor(items[0].color) : "",
        description: count ? `${count} événement${count > 1 ? "s" : ""}` : "",
    };
}

function dayGrid(range, today, getItem) {
    return `<div class="calendar-grid weekdays" aria-hidden="true">${ABBREVIATED.map(name => `<span>${name}</span>`).join("")}</div>
        <div class="calendar-grid calendar-cells">${range.cells.map(cell => {
            if (!cell.day) return "<span></span>";
            const { marks, meta, color, description } = getItem(cell.day);
            const label = `${capitalize(formatDate(cell.day))}${description ? `, ${description}` : ""}`;
            return `<button type="button" class="day-cell${cell.outside ? " outside" : ""}${cell.day === today ? " is-today" : ""}"
                data-day="${cell.day}" aria-label="${escapeHtml(label)}" ${cell.day === today ? 'aria-current="date"' : ""}
                ${color ? `style="--day-color:${color}"` : ""}>
                <span class="day-number">${Number(cell.day.slice(-2))}</span>
                ${meta ? `<span class="day-meta">${meta}</span>` : ""}
                ${marks ? `<span class="day-marks" aria-hidden="true">${marks}</span>` : ""}
            </button>`;
        }).join("")}</div>`;
}

function yearGrid(year, today, getItem) {
    return `<div class="year-grid">${Array.from({ length: 12 }, (_, month) => {
        const first = dateISO(utcDate(year, month, 1));
        const label = capitalize(longFormat(first, { month: "long" }));
        const cells = monthCells(year, month);
        return `<button type="button" class="mini-month" data-month="${first}" aria-label="Ouvrir ${label} ${year}">
            <strong>${label}</strong><span class="mini-grid" aria-hidden="true">${cells.map(({ day, outside }) => {
                if (outside || !day) return '<span class="mini-cell blank"></span>';
                const { color } = getItem(day);
                return `<span class="mini-cell${day === today ? " today" : ""}" ${color ? `style="--item-color:${color}"` : ""}></span>`;
            }).join("")}</span>
        </button>`;
    }).join("")}</div>`;
}

export function renderCalendar(host, kind, position, options) {
    host.innerHTML = `<section class="calendar-shell panel" aria-label="Calendrier">
        <div class="calendar-tools">
            <div class="segmented" role="group" aria-label="Vue du calendrier">
                <button type="button" data-view="week">Semaine</button>
                <button type="button" data-view="month">Mois</button>
                <button type="button" data-view="year">Année</button>
            </div>
            <button type="button" class="button secondary" data-today>Aujourd’hui</button>
        </div>
        <div class="calendar-period">
            <button type="button" class="icon-button" data-step="-1" aria-label="Précédent">${icon("left")}</button>
            <h2 aria-live="polite"></h2>
            <button type="button" class="icon-button" data-step="1" aria-label="Suivant">${icon("right")}</button>
        </div>
        <div class="calendar-swipe"></div>
        ${options.legend ? `<div class="calendar-footer">${options.legend}</div>` : ""}
    </section>`;

    const shell = host.firstElementChild;
    const swipe = shell.querySelector(".calendar-swipe");
    const heading = shell.querySelector("h2");
    const views = [...shell.querySelectorAll("[data-view]")];
    const steps = [...shell.querySelectorAll("[data-step]")];
    const marksByParent = options.parents ? parentMarks(options.parents) : [];
    let requestNumber = 0;
    let touch = null;
    const todayDate = () => todayIn(options.timezone, options.today);

    async function refresh() {
        const serial = ++requestNumber;
        const range = viewRange(position.day, position.view);
        heading.textContent = range.title;
        for (const button of views) button.setAttribute("aria-pressed", String(button.dataset.view === position.view));
        for (const button of steps) button.disabled = !shiftPosition(position, Number(button.dataset.step));
        swipe.setAttribute("aria-busy", "true");
        swipe.innerHTML = '<p class="empty">Chargement du calendrier…</p>';
        options.onLoading?.();
        try {
            const data = await api(`/${kind}?start=${range.start}&end=${range.end}`);
            if (serial !== requestNumber || !shell.isConnected) return;
            const days = kind === "events" ? eventDays(data) : null;
            const getItem = days
                ? day => appointmentDay(days.get(day))
                : day => custodyDay(data[day], options.parents, marksByParent);
            const today = todayDate();
            swipe.innerHTML = position.view === "year" ? yearGrid(range.year, today, getItem)
                : dayGrid(range, today, getItem);
            options.onLoaded?.(data, range);
        } catch (error) {
            if (serial !== requestNumber || !shell.isConnected) return;
            swipe.innerHTML = `${errorBlock(error)}<button type="button" class="button" data-retry>Réessayer</button>`;
        } finally {
            if (serial === requestNumber) swipe.removeAttribute("aria-busy");
        }
    }

    function step(amount) {
        const next = shiftPosition(position, amount);
        if (next && next !== position.day) {
            position.day = next;
            refresh();
        }
    }

    shell.addEventListener("click", event => {
        const button = event.target.closest("button");
        if (!button) return;
        const { view, step: direction, month, day } = button.dataset;
        if (view) {
            if (position.view === view) return;
            position.view = view;
            refresh();
        } else if (direction) {
            step(Number(direction));
        } else if (button.hasAttribute("data-today")) {
            position.day = todayDate();
            refresh();
        } else if (month) {
            position.view = "month";
            position.day = month;
            refresh();
            shell.querySelector('[data-view="month"]').focus();
        } else if (day) {
            options.onDay(day);
        } else if (button.hasAttribute("data-retry")) {
            refresh();
        }
    });
    swipe.addEventListener("touchstart", event => {
        touch = event.touches.length === 1 ? event.touches[0] : null;
    }, { passive: true });
    swipe.addEventListener("touchend", event => {
        if (!touch) return;
        const end = Array.from(event.changedTouches).find(item => item.identifier === touch.identifier);
        if (end) {
            const horizontal = end.clientX - touch.clientX;
            const vertical = end.clientY - touch.clientY;
            if (Math.abs(horizontal) >= 50 && Math.abs(horizontal) > 1.4 * Math.abs(vertical)) {
                if (event.cancelable) event.preventDefault();
                step(horizontal < 0 ? 1 : -1);
            }
        }
        touch = null;
    }, { passive: false });
    swipe.addEventListener("touchcancel", () => { touch = null; }, { passive: true });
    refresh();
    return {
        refresh,
        goTo(day) {
            position.day = day;
            return refresh();
        },
    };
}
