export const FIELD_WIDTH = 9;
export const FIELD_HEIGHT = 15;
export const FUSION_SIZE = 5;
export const FUSION_GOAL = 243;

const pieces = [
    [[1, 1, 1]],
    [[1, 0], [1, 1]],
    [[0, 1, 0], [1, 1, 1], [0, 1, 0]],
    [[1, 1, 1], [0, 0, 1], [0, 0, 1]],
    [[1, 1, 0], [0, 1, 1], [0, 0, 1]],
    [[1, 0, 1], [1, 1, 1]],
];

export function emptyField() {
    return Array.from({ length: FIELD_HEIGHT }, () => Array(FIELD_WIDTH).fill(0));
}

export function newPiece(random = Math.random) {
    const index = Math.floor(random() * pieces.length);
    const shape = pieces[index];
    return { shape, x: Math.floor((FIELD_WIDTH - shape[0].length) / 2), y: 0, color: index + 1 };
}

export function cellsOf(piece) {
    return piece.shape.flatMap((row, y) => row.flatMap((block, x) => block ? [[piece.x + x, piece.y + y]] : []));
}

export function fits(field, piece) {
    return cellsOf(piece).every(([x, y]) => x >= 0 && x < FIELD_WIDTH && y >= 0 && y < FIELD_HEIGHT && field[y][x] === 0);
}

export function rotatePiece(field, piece) {
    const shape = piece.shape[0].map((_, x) => piece.shape.map(row => row[x]).reverse());
    for (const offset of [0, -1, 1, -2, 2]) {
        const rotated = { ...piece, x: piece.x + offset, shape };
        if (fits(field, rotated)) return rotated;
    }
    return piece;
}

export function placePiece(field, piece) {
    for (const [x, y] of cellsOf(piece)) field[y][x] = piece.color;
    const clearedRows = field.flatMap((row, index) => row.every(Boolean) ? [index] : []);
    const remaining = field.filter(row => row.some(value => !value));
    const cleared = clearedRows.length;
    const blank = Array.from({ length: cleared }, () => Array(FIELD_WIDTH).fill(0));
    return { field: [...blank, ...remaining], cleared, clearedRows };
}

export function addTile(board, random = Math.random) {
    const empty = board.map((value, index) => value === 0 ? index : -1).filter(index => index >= 0);
    if (empty.length) board[empty[Math.floor(random() * empty.length)]] = random() < .84 ? 1 : 3;
    return board;
}

export function slideTiles(current, direction) {
    const next = [...current];
    const vertical = direction === "up" || direction === "down";
    const reverse = direction === "right" || direction === "down";
    let score = 0;
    const movements = [];
    for (let lane = 0; lane < FUSION_SIZE; lane += 1) {
        const positions = Array.from({ length: FUSION_SIZE }, (_, index) =>
            vertical ? index * FUSION_SIZE + lane : lane * FUSION_SIZE + index);
        if (reverse) positions.reverse();
        const tiles = positions.filter(position => current[position]);
        const merged = [];
        for (let index = 0; index < tiles.length; index += 1) {
            const source = tiles[index];
            const tile = current[source];
            const target = positions[merged.length];
            movements.push({ source, target, tile });
            if (tile === current[tiles[index + 1]]) {
                movements.push({ source: tiles[index + 1], target, tile, merge: true });
                merged.push(tile * 3);
                score += tile * 3;
                index += 1;
            } else {
                merged.push(tile);
            }
        }
        positions.forEach((position, index) => { next[position] = merged[index] ?? 0; });
    }
    return { board: next, score, movements, changed: next.some((tile, index) => tile !== current[index]) };
}

export function canSlide(board) {
    return ["up", "down", "left", "right"].some(direction => slideTiles(board, direction).changed);
}

export function shuffled(items, random = Math.random) {
    const result = [...items];
    for (let index = result.length - 1; index > 0; index -= 1) {
        const target = Math.floor(random() * (index + 1));
        [result[index], result[target]] = [result[target], result[index]];
    }
    return result;
}
