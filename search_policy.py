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
W_RISK = 100.0
BEAM = 12
FINAL = 24


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


def _pose_probabilities():
    probs = [0.0] * len(PIECE_POOL)
    for poses in PIECE_TYPES:
        for p in poses:
            probs[p] = 1.0 / (len(PIECE_TYPES) * len(poses))
    return probs


ANCHORS = [_anchors(piece.shape) for piece in PIECE_POOL]
POSE_PROB = _pose_probabilities()


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


def dead_probability(board):
    total = 0.0
    for p in range(len(PIECE_POOL)):
        if not _alive(board, p):
            total += POSE_PROB[p]
    return total


def tray_risk(board):
    return 1.0 - (1.0 - dead_probability(board)) ** 3


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
        pass

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
        return max(level[:FINAL], key=lambda c: c[0] - W_RISK * tray_risk(c[1]))[3]
