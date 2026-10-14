"""Wybór ruchu po całej tacce na bitboardach z oceną końca tacki."""
import random

from pieces import PIECE_POOL, PIECE_TYPES

N = 8
TAU = 0.2
LINE_W = 3.0
CONTACT_W = 0.5
RISK_W = 400.0
COV_W = 4.0
BEAM = 40
FINAL = 16
SAMPLES = 24

ROW_MASKS = [0xFF << (N * r) for r in range(N)]
COL_MASKS = [sum(1 << (N * r + c) for r in range(N)) for c in range(N)]

POSE_PROB = [0.0] * len(PIECE_POOL)
for _poses in PIECE_TYPES:
    for _p in _poses:
        POSE_PROB[_p] = 1.0 / (len(PIECE_TYPES) * len(_poses))


def _placements(piece):
    h, w = len(piece.shape), len(piece.shape[0])
    cells = [(dy, dx) for dy, row in enumerate(piece.shape) for dx, cell in enumerate(row) if cell]
    entries = []
    for y in range(N - h + 1):
        for x in range(N - w + 1):
            absolute = {(y + dy, x + dx) for dy, dx in cells}
            mask = 0
            for r, c in absolute:
                mask |= 1 << (N * r + c)
            nb = 0
            outside = 0
            for r, c in absolute:
                for rr, cc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                    if not (0 <= rr < N and 0 <= cc < N):
                        outside += 1
                    elif (rr, cc) not in absolute:
                        nb |= 1 << (N * rr + cc)
            rows = tuple(sorted({r for r, _ in absolute}))
            cols = tuple(sorted({c for _, c in absolute}))
            entries.append((mask, x, y, nb, outside, rows, cols))
    return entries


PLACEMENTS = [_placements(piece) for piece in PIECE_POOL]


def to_bits(grid):
    bits = 0
    for r in range(N):
        for c in range(N):
            if grid[r][c]:
                bits |= 1 << (N * r + c)
    return bits


def _place(bits, entry):
    board = bits | entry[0]
    rows, cols = entry[5], entry[6]
    full_rows = [r for r in rows if (board & ROW_MASKS[r]) == ROW_MASKS[r]]
    full_cols = [c for c in cols if (board & COL_MASKS[c]) == COL_MASKS[c]]
    clear = 0
    for r in full_rows:
        clear |= ROW_MASKS[r]
    for c in full_cols:
        clear |= COL_MASKS[c]
    return board & ~clear, len(full_rows) + len(full_cols)


def _cheap(state):
    bits, _, _, contacts, lines = state
    return (N * N - bin(bits).count("1")) + LINE_W * lines + CONTACT_W * contacts


def _search(bits, slots, pieces):
    frontier = [(bits, slots, None, 0, 0)]
    terminals = []
    while frontier:
        children = []
        for board, rest, first, contacts, lines in frontier:
            for slot in rest:
                left = tuple(s for s in rest if s != slot)
                for entry in PLACEMENTS[pieces[slot].index]:
                    if board & entry[0]:
                        continue
                    placed, cleared = _place(board, entry)
                    child = (
                        placed,
                        left,
                        first if first is not None else (slot, entry[1], entry[2]),
                        contacts + bin(entry[3] & board).count("1") + entry[4],
                        lines + cleared,
                    )
                    (children if left else terminals).append(child)
        frontier = sorted(children, key=_cheap, reverse=True)[:BEAM]
    return terminals


def _draw_tray(rng):
    tray = []
    for _ in range(3):
        poses = rng.choice(PIECE_TYPES)
        tray.append(PIECE_POOL[rng.choice(poses)])
    return tray


def _completable(board, tray, rest):
    if not rest:
        return True
    for k, slot in enumerate(rest):
        left = rest[:k] + rest[k + 1:]
        for entry in PLACEMENTS[tray[slot].index]:
            if board & entry[0]:
                continue
            if _completable(_place(board, entry)[0], tray, left):
                return True
    return False


def _cover_probs(bits):
    cover = [0.0] * (N * N)
    for p, entries in enumerate(PLACEMENTS):
        reach = 0
        for entry in entries:
            if not bits & entry[0]:
                reach |= entry[0]
        while reach:
            low = reach & -reach
            cover[low.bit_length() - 1] += POSE_PROB[p]
            reach ^= low
    return cover


def _value(state, risk):
    bits, _, _, contacts, lines = state
    cover = _cover_probs(bits)
    dead = sum(1 for c in range(N * N) if ((bits >> c) & 1) == 0 and cover[c] < TAU)
    empties = N * N - bin(bits).count("1")
    return (empties + LINE_W * lines + CONTACT_W * contacts
            - RISK_W * risk - COV_W * dead)


class SurvivalPolicy:
    name = "survival"

    def reset(self, game_seed):
        self.rng = random.Random(f"tray:{game_seed}")

    def act(self, game, actions):
        slots = tuple(i for i, piece in enumerate(game.pieces) if piece is not None)
        terminals = _search(to_bits(game.board.grid), slots, game.pieces)
        if not terminals:
            return actions[0]
        trays = [_draw_tray(self.rng) for _ in range(SAMPLES)]
        terminals.sort(key=_cheap, reverse=True)
        best_first, best_value = None, None
        for state in terminals[:FINAL]:
            fails = sum(1 for tray in trays if not _completable(state[0], tray, (0, 1, 2)))
            value = _value(state, fails / SAMPLES)
            if best_value is None or value > best_value:
                best_first, best_value = state[2], value
        return best_first
