"""
Przeszukiwanie tacki na bitboardzie: pole 8x8 jako int, bit y*8 + x.

Klocek identyfikuje się kształtem, nie indeksem pozy: most (bridge.py) podaje
klocki z index=-1, więc tylko shape jest wiarygodny.
"""

ROW_MASKS = [0xFF << (8 * r) for r in range(8)]
COL_MASKS = [sum(1 << (8 * r + c) for r in range(8)) for c in range(8)]
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


def clear(board):
    full = [m for m in ROW_MASKS + COL_MASKS if board & m == m]
    for m in full:
        board &= ~m
    return board


def completable(board, keys):
    """Czy wszystkie klocki da się kolejno położyć na planszy w pewnej kolejności, z czyszczeniem."""
    rest = tuple(sorted(keys))
    seen = set()
    stack = [(board, rest)]
    while stack:
        state = stack.pop()
        if state in seen:
            continue
        seen.add(state)
        b, left = state
        for i, key in enumerate(left):
            if i and left[i - 1] == key:
                continue
            tail = left[:i] + left[i + 1:]
            moves = legal(b, key)
            if not tail:
                if moves:
                    return True
                continue
            for _, _, m in moves:
                stack.append((clear(b | m), tail))
    return not keys


def from_grid(grid):
    return sum(1 << (8 * r + c) for r in range(8) for c in range(8) if grid[r][c])
