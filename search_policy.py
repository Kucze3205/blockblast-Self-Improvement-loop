import random

from pieces import PIECE_POOL, PIECE_TYPES

FULL = (1 << 64) - 1
COLS = [sum(1 << (8 * y + x) for y in range(8)) for x in range(8)]
ROWS = [0xFF << (8 * y) for y in range(8)]
LINES = ROWS + COLS
NOT_COL0 = FULL & ~COLS[0]
NOT_COL7 = FULL & ~COLS[7]

W_LINE = 4.2
W_OCC = 1.4
W_POCKET = 0.75
W_TRANS = 1.5
W_DEAD_PIECE = 12.3
BEAM = 40
FINAL = 12
HARD_TYPES = (4, 6, 7, 10, 9)  # typy z pieces.CANONICAL_TYPES: beam5, rect23, square3, corner5, L
SAMPLES = 16
HARD_PENALTY = 500.0
TRAY_BUDGET = 150


def _anchors(shape):
    cells = [(dy, dx) for dy, row in enumerate(shape) for dx, cell in enumerate(row) if cell]
    out = []
    for y in range(8 - len(shape) + 1):
        for x in range(8 - len(shape[0]) + 1):
            mask = 0
            for dy, dx in cells:
                mask |= 1 << (8 * (y + dy) + x + dx)
            out.append((x, y, mask))
    return out


ANCHORS = [_anchors(piece.shape) for piece in PIECE_POOL]


def to_bits(grid):
    bits = 0
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            if cell:
                bits |= 1 << (8 * y + x)
    return bits


def place(board, mask):
    board |= mask
    cleared = [line for line in LINES if (board & line) == line]
    clear_mask = 0
    for line in cleared:
        clear_mask |= line
    return board & ~clear_mask, len(cleared)


def _blocked_neighbours(board):
    up = ((board << 8) & FULL) | ROWS[0]
    down = (board >> 8) | ROWS[7]
    left = ((board << 1) & NOT_COL0) | COLS[0]
    right = ((board >> 1) & NOT_COL7) | COLS[7]
    return up, down, left, right


def transitions(board):
    up, down, left, right = _blocked_neighbours(board)
    return (
        (board ^ left).bit_count()
        + ((board ^ right) & COLS[7]).bit_count()
        + (board ^ up).bit_count()
        + ((board ^ down) & ROWS[7]).bit_count()
    )


def pockets(board):
    up, down, left, right = _blocked_neighbours(board)
    three = (up & down & left) | (up & down & right) | (up & left & right) | (down & left & right)
    return ((FULL & ~board) & three).bit_count()


def shape_cost(board):
    return W_OCC * board.bit_count() + W_POCKET * pockets(board) + W_TRANS * transitions(board)


def _alive(board, p):
    for _, _, mask in ANCHORS[p]:
        if not (board & mask):
            return True
    return False


def _fits_all(board, pieces, budget):
    if not pieces:
        return True
    for p in set(pieces):
        rest = list(pieces)
        rest.remove(p)
        for _, _, mask in ANCHORS[p]:
            if board & mask:
                continue
            budget[0] -= 1
            if budget[0] < 0:
                return False
            new_board, _ = place(board, mask)
            if _fits_all(new_board, rest, budget):
                return True
    return False


def _sample_hard_tray(rng):
    return [rng.choice(PIECE_TYPES[rng.choice(HARD_TYPES)]) for _ in range(3)]


def _hard_penalty(board, trays):
    bad = sum(1 for tray in trays if not _fits_all(board, tray, [TRAY_BUDGET]))
    return HARD_PENALTY * bad / len(trays)


def _expand(score, board, remaining, first):
    children = []
    for slot, p in remaining:
        rest = tuple(item for item in remaining if item[0] != slot)
        for x, y, mask in ANCHORS[p]:
            if board & mask:
                continue
            new_board, lines = place(board, mask)
            child = score + W_LINE * lines - shape_cost(new_board)
            child -= W_DEAD_PIECE * sum(1 for _, q in rest if not _alive(new_board, q))
            move = first if first is not None else (slot, x, y)
            children.append((child, new_board, rest, move))
    return children


class SearchPolicy:
    name = "search"

    def reset(self, game_seed):
        self.rng = random.Random(game_seed)

    def act(self, game, actions):
        board = to_bits(game.board.grid)
        remaining = tuple((slot, piece.index) for slot, piece in enumerate(game.pieces) if piece is not None)
        level = _expand(0.0, board, remaining, None)
        fallback = max(level, key=lambda c: c[0])[3]
        for _ in range(1, len(remaining)):
            level.sort(key=lambda c: c[0], reverse=True)
            level = [child for node in level[:BEAM] for child in _expand(*node)]
            if not level:
                return fallback
        level.sort(key=lambda c: c[0], reverse=True)
        trays = [_sample_hard_tray(self.rng) for _ in range(SAMPLES)]
        return max(level[:FINAL], key=lambda c: c[0] - _hard_penalty(c[1], trays))[3]
