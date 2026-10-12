"""
Przeszukiwanie tacki na bitboardzie: pole 8x8 jako int, bit y*8 + x.

Klocek identyfikuje się kształtem, nie indeksem pozy: most (bridge.py) podaje
klocki z index=-1, więc tylko shape jest wiarygodny.
"""

ROW_MASKS = [0xFF << (8 * r) for r in range(8)]
COL_MASKS = [sum(1 << (8 * r + c) for r in range(8)) for c in range(8)]
LINE_MASKS = ROW_MASKS + COL_MASKS
_PLACEMENTS = {}


def shape_key(shape):
    return tuple(tuple(int(cell) for cell in row) for row in shape)


def placements(key):
    """(x, y, maska) dla każdego położenia klocka o tym kształcie na pustej planszy."""
    if key not in _PLACEMENTS:
        h, w = len(key), len(key[0])
        base = sum(1 << (8 * r + c) for r, row in enumerate(key) for c, cell in enumerate(row) if cell)
        _PLACEMENTS[key] = [(x, y, base << (8 * y + x))
                            for y in range(8 - h + 1) for x in range(8 - w + 1)]
    return _PLACEMENTS[key]


def mask_at(key, x, y):
    return sum(1 << (8 * (y + r) + x + c) for r, row in enumerate(key) for c, cell in enumerate(row) if cell)


def legal(board, key):
    return [(x, y, m) for x, y, m in placements(key) if not board & m]


def fits(board, key):
    return any(not board & m for _, _, m in placements(key))


def clear(board):
    for m in [m for m in LINE_MASKS if board & m == m]:
        board &= ~m
    return board


def popcount(board):
    return bin(board).count("1")


def completable(board, keys):
    """Czy wszystkie klocki da się kolejno położyć na planszy w pewnej kolejności, z czyszczeniem."""
    return _finishable(board, tuple(sorted(keys)), set())


def _finishable(board, left, failed):
    if not left:
        return True
    if (board, left) in failed:
        return False
    for i, key in enumerate(left):
        if i and left[i - 1] == key:
            continue
        tail = left[:i] + left[i + 1:]
        if not tail:
            if fits(board, key):
                return True
            continue
        for _, _, m in legal(board, key):
            if _finishable(clear(board | m), tail, failed):
                return True
    failed.add((board, left))
    return False


def tray_finals(board, pieces, width=None):
    """Plansze po całej tacce z pierwszym ruchem do każdej z nich, od najmniej zajętej.

    pieces: lista (indeks w game.pieces, kształt). Pośrednie stany są ograniczone do
    `width` najmniej zajętych osobno dla każdej reszty tacki; None oznacza pełny przegląd.
    """
    left = tuple(sorted(pieces, key=lambda item: item[1]))
    frontier = {(board, tuple(k for _, k in left)): (None, left)}
    finals = {}
    while frontier:
        nxt = {}
        for (b, _), (first, entries) in frontier.items():
            for j, (idx, key) in enumerate(entries):
                if j and entries[j - 1][1] == key:
                    continue
                tail = entries[:j] + entries[j + 1:]
                for x, y, m in legal(b, key):
                    nb = clear(b | m)
                    move = first or (idx, x, y)
                    if tail:
                        nxt.setdefault((nb, tuple(k for _, k in tail)), (move, tail))
                    else:
                        finals.setdefault(nb, move)
        frontier = nxt
        if width is not None:
            frontier = _beam(frontier, width)
    return sorted(finals.items(), key=lambda item: _rank(item[0]))


def _rank(board):
    # Remisy po zajętości rozstrzyga hash planszy, nie kolejność wyliczenia (lewy górny róg).
    return popcount(board), (board * 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF


def _beam(frontier, width):
    groups = {}
    for state, value in frontier.items():
        groups.setdefault(state[1], []).append((state, value))
    kept = {}
    for members in groups.values():
        members.sort(key=lambda item: _rank(item[0][0]))
        kept.update(members[:width])
    return kept


def from_grid(grid):
    return sum(1 << (8 * r + c) for r in range(8) for c in range(8) if grid[r][c])
