import { icon, pageHeading } from "./ui.js";
import {
    FIELD_HEIGHT, FIELD_WIDTH, FUSION_GOAL, FUSION_SIZE, addTile, canSlide,
    cellsOf, emptyField, fits, newPiece, placePiece, rotatePiece, shuffled, slideTiles,
} from "./game-rules.js";

const catalog = {
    orbitale: { title: "Orbitale", mark: "▦", tone: "orbit", info: "Place les pièces et complète des lignes.", mount: orbitale },
    fusion: { title: "Fusion 243", mark: "3", tone: "fusion", info: "Associe les tuiles identiques pour atteindre 243.", mount: fusion },
    paires: { title: "Paires flash", mark: "✦", tone: "pairs", info: "Retourne les cartes et retrouve les six paires.", mount: pairs },
};

const keys = { ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right" };
const formatNumber = new Intl.NumberFormat("fr-FR");

export function renderGames(host, selection) {
    const game = Object.hasOwn(catalog, selection) ? catalog[selection] : null;
    if (!game) {
        host.innerHTML = pageHeading("Mini-jeux", "games", "tone-games") + `<div class="game-picker">
            ${Object.entries(catalog).map(([id, item]) => `
                <a href="/jeux?jeu=${id}" data-route="/jeux" class="game-tile game-${item.tone}">
                    <span class="game-mark" aria-hidden="true">${item.mark}</span>
                    <span class="row-copy"><strong>${item.title}</strong><span class="muted small">${item.info}</span></span>
                    ${icon("right")}
                </a>`).join("")}
        </div>`;
        return;
    }
    host.classList.remove("page-enter");
    host.innerHTML = pageHeading(game.title, "games", "tone-games",
        '<a href="/jeux" data-route="/jeux" class="button secondary">Tous les jeux</a>') +
        '<section class="panel game-area" data-game-area></section>';
    const lifecycle = new AbortController();
    host.addEventListener("tempo:leave", () => lifecycle.abort(), { once: true });
    game.mount(host.querySelector("[data-game-area]"), lifecycle.signal);
}

function keyboard(area, signal, commands) {
    document.addEventListener("keydown", event => {
        const command = Object.hasOwn(commands, event.key) && commands[event.key];
        if (!command || !area.isConnected || document.querySelector("dialog[open]") ||
            event.altKey || event.ctrlKey || event.metaKey || event.target.closest?.("input, textarea, select, a, [contenteditable]")) return;
        if (event.key === " " && event.target.closest?.("button")) return;
        event.preventDefault();
        command();
    }, { signal });
}

function control(command, label, text) {
    return `<button type="button" class="button secondary game-pad-button" data-move="${command}" aria-label="${label}">${text}</button>`;
}

function gameMotion(signal) {
    const active = new Set();
    const reduced = matchMedia("(prefers-reduced-motion: reduce)");
    const clear = () => { for (const animation of active) animation.cancel(); };
    signal.addEventListener("abort", clear, { once: true });
    reduced.addEventListener("change", clear, { signal });
    return {
        clear,
        enabled: () => !reduced.matches && typeof Element.prototype.animate === "function",
        play(element, frames, options, cleanup = () => {}) {
            const animation = element.animate(frames, options);
            active.add(animation);
            const done = () => { active.delete(animation); cleanup(); };
            animation.finished.then(done, done);
        },
    };
}

function placeEffect(board, cell, className) {
    const effect = document.createElement("div");
    effect.className = className;
    effect.setAttribute("aria-hidden", "true");
    effect.style.cssText = `left:${cell.offsetLeft}px;top:${cell.offsetTop}px;width:${cell.offsetWidth}px;height:${cell.offsetHeight}px`;
    board.append(effect);
    return effect;
}

function orbitale(area, signal) {
    area.classList.add("orbit-area");
    area.innerHTML = `<div class="game-stats orbit-stats">
        <span>Score <strong data-score>0</strong></span><span>Lignes <strong data-lines>0</strong></span>
        <button type="button" class="button secondary" data-pause hidden>Pause</button>
    </div>
    <div class="orbit-stage">
        <div class="orbit-field" role="img" tabindex="0" aria-label="Grille Orbitale de 9 colonnes sur 15 lignes"></div>
        <div class="orbit-cover" data-cover>
            <p data-orbit-message>Complète des lignes avec les pièces qui tombent.</p>
            <button type="button" class="button primary" data-start>Jouer</button>
        </div>
    </div>
    <div class="game-pad orbit-controls" aria-label="Commandes Orbitale">
        ${control("left", "Déplacer à gauche", "←")}
        ${control("rotate", "Tourner la pièce", "Tourner")}
        ${control("right", "Déplacer à droite", "→")}
        ${control("down", "Descendre d’une case", "↓")}
        ${control("drop", "Poser immédiatement", "Poser")}
    </div>
    <p class="game-help small muted">Clavier · flèches pour déplacer et tourner, espace pour poser, P pour mettre en pause.</p>`;

    const grid = area.querySelector(".orbit-field");
    const tiles = Array.from({ length: FIELD_HEIGHT * FIELD_WIDTH }, () => document.createElement("span"));
    grid.append(...tiles);
    const pauseControl = area.querySelector("[data-pause]");
    const start = area.querySelector("[data-start]");
    const cover = area.querySelector("[data-cover]");
    const message = area.querySelector("[data-orbit-message]");
    const score = area.querySelector("[data-score]");
    const lines = area.querySelector("[data-lines]");
    const controls = Array.from(area.querySelectorAll("[data-move]"));
    const motion = gameMotion(signal);
    let field = emptyField();
    let piece = null;
    let points = 0;
    let cleared = 0;
    let timer;
    let phase = "ready";

    function draw() {
        const snapshot = field.flat();
        if (piece) {
            let landing = piece;
            while (fits(field, { ...landing, y: landing.y + 1 })) landing = { ...landing, y: landing.y + 1 };
            for (const [x, y] of cellsOf(landing)) snapshot[y * FIELD_WIDTH + x] = "ghost";
            for (const [x, y] of cellsOf(piece)) snapshot[y * FIELD_WIDTH + x] = piece.color;
        }
        snapshot.forEach((value, index) => { tiles[index].dataset.tile = value || ""; });
        score.textContent = formatNumber.format(points);
        lines.textContent = formatNumber.format(cleared);
    }

    function changePhase(next) {
        phase = next;
        cover.hidden = next === "running";
        pauseControl.hidden = next !== "running";
        controls.forEach(button => { button.disabled = next !== "running"; });
        const words = {
            ready: ["Complète des lignes avec les pièces qui tombent.", "Jouer"],
            paused: ["Partie en pause", "Reprendre"],
            over: ["La grille est pleine", "Rejouer"],
        };
        if (next !== "running") {
            [message.textContent, start.textContent] = words[next];
            clearTimeout(timer);
        }
    }

    function schedule() {
        clearTimeout(timer);
        if (phase !== "running") return;
        const delay = Math.max(130, 790 - Math.floor(cleared / 4) * 80);
        timer = setTimeout(() => {
            action("down");
            schedule();
        }, delay);
    }

    function action(type) {
        if (phase !== "running") return;
        motion.clear();
        const previous = piece;
        let landed, linesCleared = [];
        if (type === "rotate") {
            piece = rotatePiece(field, piece);
        } else if (type === "left" || type === "right") {
            const move = { ...piece, x: piece.x + (type === "left" ? -1 : 1) };
            if (fits(field, move)) piece = move;
        } else {
            const next = { ...piece, y: piece.y + 1 };
            if (type === "down" && fits(field, next)) {
                piece = next;
            } else {
                if (type === "drop") {
                    while (fits(field, { ...piece, y: piece.y + 1 })) piece = { ...piece, y: piece.y + 1 };
                }
                const result = placePiece(field, piece);
                landed = piece;
                linesCleared = result.clearedRows;
                field = result.field;
                cleared += result.cleared;
                points += 5 + result.cleared ** 2 * 75;
                piece = newPiece();
                if (!fits(field, piece)) {
                    piece = null;
                    changePhase("over");
                }
                schedule();
            }
        }
        draw();
        if (!motion.enabled()) return;
        if (linesCleared.length) {
            for (const row of linesCleared) {
                const first = tiles[row * FIELD_WIDTH];
                const last = tiles[(row + 1) * FIELD_WIDTH - 1];
                const light = placeEffect(grid, first, "orbit-clear");
                light.style.width = `${last.offsetLeft + last.offsetWidth - first.offsetLeft}px`;
                motion.play(light, [{ opacity: .9 }, { opacity: 0, transform: "scaleX(.86)" }],
                    { duration: 250, easing: "ease-out" }, () => light.remove());
            }
            return;
        }
        const nextPiece = landed ?? piece;
        if (nextPiece === previous || !nextPiece) return;
        const rotate = type === "rotate";
        for (const [x, y] of cellsOf(previous)) {
            const origin = tiles[y * FIELD_WIDTH + x];
            const targetX = nextPiece.x + (rotate ? previous.shape.length - 1 - (y - previous.y) : x - previous.x);
            const targetY = nextPiece.y + (rotate ? x - previous.x : y - previous.y);
            const target = tiles[targetY * FIELD_WIDTH + targetX];
            const dx = origin.offsetLeft - target.offsetLeft;
            const dy = origin.offsetTop - target.offsetTop;
            if (dx || dy) motion.play(target,
                [{ transform: `translate(${dx}px, ${dy}px)`, zIndex: 1 }, { transform: "none", zIndex: 1 }],
                { duration: landed ? 145 : 105, easing: "cubic-bezier(.2,.75,.35,1)" });
        }
    }

    const togglePause = () => {
        if (phase === "running") changePhase("paused");
        else if (phase === "paused") {
            changePhase("running");
            schedule();
        }
    };
    pauseControl.onclick = () => {
        togglePause();
        start.focus();
    };
    start.onclick = () => {
        if (phase !== "paused") {
            field = emptyField();
            points = cleared = 0;
            piece = newPiece();
        }
        changePhase("running");
        grid.focus({ preventScroll: true });
        draw();
        schedule();
    };
    controls.forEach(button => { button.onclick = () => action(button.dataset.move); });
    keyboard(area, signal, {
        ArrowLeft: () => action("left"), ArrowRight: () => action("right"), ArrowUp: () => action("rotate"),
        ArrowDown: () => action("down"), " ": () => action("drop"), p: togglePause, P: togglePause,
    });
    document.addEventListener("visibilitychange", () => {
        if (document.hidden && phase === "running") changePhase("paused");
    }, { signal });
    signal.addEventListener("abort", () => clearTimeout(timer), { once: true });
    changePhase("ready");
    draw();
}

function fusion(area, signal) {
    area.classList.add("fusion-area");
    area.innerHTML = `<div class="game-stats">
        <span>Score <strong data-score>0</strong></span>
        <button type="button" class="button secondary" data-new>Nouvelle partie</button>
    </div>
    <div class="fusion-board" role="img" tabindex="0" aria-label="Grille de fusion de 5 colonnes sur 5 lignes"></div>
    <p class="game-status" role="status"></p>
    <div class="game-pad fusion-controls" aria-label="Déplacements">
        ${control("left", "Glisser à gauche", "←")}${control("up", "Glisser vers le haut", "↑")}
        ${control("down", "Glisser vers le bas", "↓")}${control("right", "Glisser à droite", "→")}
    </div>
    <p class="game-help small muted">Glisse sur la grille ou utilise les flèches. Deux tuiles identiques donnent la valeur suivante jusqu’à 243.</p>`;
    const grid = area.querySelector(".fusion-board");
    const status = area.querySelector(".game-status");
    const score = area.querySelector("[data-score]");
    const controls = Array.from(area.querySelectorAll("[data-move]"));
    const tiles = Array.from({ length: FUSION_SIZE ** 2 }, () => document.createElement("span"));
    const chips = tiles.map(tile => tile.appendChild(document.createElement("span")));
    chips.forEach(chip => { chip.className = "fusion-chip"; });
    grid.append(...tiles);
    const motion = gameMotion(signal);
    let board, points, ended, gesture;

    function draw() {
        tiles.forEach((tile, index) => {
            const value = board[index];
            tile.dataset.number = value || "";
            chips[index].textContent = value || "";
            chips[index].dataset.number = value || "";
        });
        const rows = Array.from({ length: FUSION_SIZE }, (_, row) =>
            board.slice(row * FUSION_SIZE, (row + 1) * FUSION_SIZE).map(number => number || "vide").join(", "));
        grid.setAttribute("aria-label", `Grille de fusion. ${rows.join(" · ")}`);
        score.textContent = formatNumber.format(points);
        controls.forEach(button => { button.disabled = ended; });
    }

    function reset() {
        motion.clear();
        board = addTile(addTile(Array(FUSION_SIZE ** 2).fill(0)));
        points = 0;
        ended = false;
        status.textContent = "";
        draw();
    }

    function move(direction) {
        if (ended) return;
        const next = slideTiles(board, direction);
        if (!next.changed) return;
        motion.clear();
        points += next.score;
        board = addTile([...next.board]);
        const won = board.includes(FUSION_GOAL);
        ended = won || !canSlide(board);
        if (ended) status.textContent = won ? "Objectif atteint · 243 !" : "Plus de déplacement possible.";
        draw();
        if (!motion.enabled()) return;
        const merged = new Set(next.movements.filter(item => item.merge).map(item => item.target));
        const moving = next.movements.filter(item => item.source !== item.target || merged.has(item.target));
        const targets = new Set(moving.map(item => item.target));
        for (const item of moving) {
            const start = tiles[item.source], end = tiles[item.target];
            const copy = placeEffect(grid, start, "fusion-chip fusion-motion");
            copy.dataset.number = item.tile;
            copy.textContent = item.tile;
            motion.play(copy, [{ transform: "none" },
                { transform: `translate(${end.offsetLeft - start.offsetLeft}px, ${end.offsetTop - start.offsetTop}px)` }],
                { duration: 135, easing: "ease-out" }, () => copy.remove());
        }
        for (const target of targets) {
            motion.play(chips[target], [{ opacity: 0 }, { opacity: 0 }],
                { duration: 135 });
        }
        for (const target of merged) {
            motion.play(chips[target], [{ transform: "scale(1)" }, { transform: "scale(1.14)" }, { transform: "scale(1)" }],
                { duration: 145, delay: 135, easing: "ease-out" });
        }
        const spawned = board.findIndex((value, index) => value && !next.board[index]);
        if (spawned >= 0) motion.play(chips[spawned], [{ transform: "scale(.45)", opacity: 0 }, { transform: "none", opacity: 1 }],
            { duration: 160, delay: 115, fill: "backwards", easing: "ease-out" });
    }

    area.querySelector("[data-new]").onclick = reset;
    controls.forEach(button => { button.onclick = () => move(button.dataset.move); });
    keyboard(area, signal, Object.fromEntries(Object.entries(keys).map(([key, direction]) => [key, () => move(direction)])));
    grid.addEventListener("touchstart", event => {
        gesture = event.touches.length === 1 ? event.touches[0] : null;
    }, { passive: true });
    grid.addEventListener("touchend", event => {
        if (!gesture) return;
        const end = Array.from(event.changedTouches).find(touch => touch.identifier === gesture.identifier);
        if (!end) return;
        const x = end.clientX - gesture.clientX;
        const y = end.clientY - gesture.clientY;
        gesture = null;
        if (Math.max(Math.abs(x), Math.abs(y)) < 25) return;
        if (event.cancelable) event.preventDefault();
        move(Math.abs(x) >= Math.abs(y) ? x > 0 ? "right" : "left" : y > 0 ? "down" : "up");
    }, { passive: false });
    grid.addEventListener("touchcancel", () => { gesture = null; }, { passive: true });
    reset();
}

const symbols = [["✦", "Étoile"], ["☾", "Lune"], ["◈", "Losange"], ["✿", "Fleur"], ["♥", "Cœur"], ["☀", "Soleil"]];

function pairs(area, signal) {
    area.classList.add("pairs-area");
    area.innerHTML = `<div class="game-stats">
        <span>Essais <strong data-turns>0</strong></span><span>Paires <strong data-count>0 / 6</strong></span>
        <button type="button" class="button secondary" data-new>Rejouer</button>
    </div>
    <div class="pairs-board" aria-label="Cartes de mémoire"></div>
    <p class="game-status" role="status"></p>
    <p class="game-help small muted">Retourne deux cartes à la fois pour retrouver les six paires.</p>`;

    const grid = area.querySelector(".pairs-board");
    const status = area.querySelector(".game-status");
    const turns = area.querySelector("[data-turns]");
    const count = area.querySelector("[data-count]");
    let cards, visible, matched, attempts, timer;

    function draw() {
        Array.from(grid.children).forEach((button, index) => {
            const show = visible.includes(index) || matched.has(index);
            button.dataset.revealed = String(show);
            button.dataset.matched = String(matched.has(index));
            button.querySelector(".pair-face-front").textContent = symbols[cards[index]][0];
            button.setAttribute("aria-label", show ?
                `Carte ${index + 1} · ${symbols[cards[index]][1]}${matched.has(index) ? ", paire trouvée" : ""}`
                : `Retourner la carte ${index + 1}`);
            button.setAttribute("aria-pressed", String(show));
        });
        turns.textContent = formatNumber.format(attempts);
        count.textContent = `${matched.size / 2} / ${symbols.length}`;
    }

    function reveal(index) {
        if (visible.length === 2 || matched.has(index) || visible.includes(index)) return;
        visible.push(index);
        if (visible.length === 2) {
            attempts += 1;
            const [first, second] = visible;
            if (cards[first] === cards[second]) {
                matched.add(first).add(second);
                visible = [];
                if (matched.size === cards.length) status.textContent = `Toutes les paires en ${attempts} essais !`;
            } else {
                timer = setTimeout(() => { visible = []; draw(); }, 730);
            }
        }
        draw();
    }

    function reset() {
        clearTimeout(timer);
        const faces = symbols.map((_, index) => index);
        cards = shuffled([...faces, ...faces]);
        visible = [];
        matched = new Set();
        attempts = 0;
        status.textContent = "";
        draw();
    }

    for (let index = 0; index < symbols.length * 2; index += 1) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "pair-card";
        button.innerHTML = '<span class="pair-faces" aria-hidden="true"><span class="pair-face pair-face-back">✧</span><span class="pair-face pair-face-front"></span></span>';
        button.onclick = () => reveal(index);
        grid.append(button);
    }
    area.querySelector("[data-new]").onclick = reset;
    signal.addEventListener("abort", () => clearTimeout(timer), { once: true });
    reset();
}
