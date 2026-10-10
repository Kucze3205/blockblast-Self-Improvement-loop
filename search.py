"""Przeszukiwanie tacki na bitboardzie: wiązka po klockach z liniową oceną planszy.

Bit (8*y + x) to pole (y, x). Plansza po postawieniu jest czyszczona tak samo
jak w Board.clear_lines: pełne wiersze i kolumny naraz.
"""
from pieces import PIECE_POOL

FULL = (1 << 64) - 1
ROW = [0xFF << (8 * r) for r in range(8)]
COL = [sum(1 << (8 * r + c) for r in range(8)) for c in range(8)]
NOT_COL0 = FULL & ~COL[0]
NOT_COL7 = FULL & ~COL[7]
NOT_COL67 = FULL & ~COL[6] & ~COL[7]
ROWS_0_6 = FULL & ~ROW[7]


def _row_transitions(v):
    cells = [1] + [(v >> x) & 1 for x in range(8)] + [1]
    return sum(cells[i] != cells[i + 1] for i in range(9))


ROW_TRANS = [_row_transitions(v) for v in range(256)]
POP8 = [v.bit_count() for v in range(256)]

PLACEMENTS = []  # PLACEMENTS[pose] = [(x, y, mask)] dla wszystkich położeń w planszy
for _piece in PIECE_POOL:
    _h, _w = len(_piece.shape), len(_piece.shape[0])
    _cells = [(dy, dx) for dy, row in enumerate(_piece.shape) for dx, v in enumerate(row) if v]
    _opts = []
    for _y in range(8 - _h + 1):
        for _x in range(8 - _w + 1):
            _mask = 0
            for _dy, _dx in _cells:
                _mask |= 1 << ((_y + _dy) * 8 + _x + _dx)
            _opts.append((_x, _y, _mask))
    PLACEMENTS.append(_opts)


def occupancy(grid):
    occ = 0
    for r in range(8):
        row = grid[r]
        for c in range(8):
            if row[c]:
                occ |= 1 << (8 * r + c)
    return occ


def clear(occ):
    rows = [r for r in range(8) if (occ & ROW[r]) == ROW[r]]
    cols = [c for c in range(8) if (occ & COL[c]) == COL[c]]
    if not rows and not cols:
        return occ, 0
    gone = 0
    for r in rows:
        gone |= ROW[r]
    for c in cols:
        gone |= COL[c]
    return occ & ~gone, len(rows) + len(cols)


def features(occ):
    """Cechy planszy (po czyszczeniu), każda znormalizowana do ok. [0, 1]."""
    cover = occ
    for _ in range(7):
        cover |= (cover << 8) & FULL
    col_cover = [(cover & COL[c]).bit_count() for c in range(8)]
    col_fill = [(occ & COL[c]).bit_count() for c in range(8)]
    rows8 = [(occ >> (8 * r)) & 0xFF for r in range(8)]

    holes = (cover & ~occ & FULL).bit_count()
    agg = sum(col_cover)
    bump = sum(abs(col_cover[i] - col_cover[i + 1]) for i in range(7))
    row_tr = sum(ROW_TRANS[v] for v in rows8)
    col_tr = (((occ ^ (occ >> 8)) & ROWS_0_6).bit_count()
              + ((~occ) & ROW[0] & FULL).bit_count()
              + ((~occ) & ROW[7] & FULL).bit_count())
    near_rows = sum(1 for v in rows8 if POP8[v] >= 7)
    near_cols = sum(1 for n in col_fill if n >= 7)

    e = ~occ & FULL
    up = ((occ << 8) & FULL) | ROW[0]
    down = (occ >> 8) | ROW[7]
    left = ((occ << 1) & NOT_COL0) | COL[0]
    right = ((occ >> 1) & NOT_COL7) | COL[7]
    isolated = (e & up & down & left & right).bit_count()
    sq2 = (e & (e >> 1) & (e >> 8) & (e >> 9) & NOT_COL7).bit_count()
    t3 = e & (e >> 1) & (e >> 2) & NOT_COL67
    sq3 = (t3 & (t3 >> 8) & (t3 >> 16)).bit_count()

    return [
        holes / 16,
        agg / 64,
        bump / 16,
        max(col_cover) / 8,
        row_tr / 32,
        col_tr / 32,
        near_rows / 8,
        near_cols / 8,
        isolated / 8,
        sq2 / 16,
        sq3 / 8,
        occ.bit_count() / 64,
    ]


FEATURE_COUNT = 12


def best_move(occ, pieces, value, width):
    """Pierwszy ruch najlepszej ścieżki; ścieżka może nie mieścić całej tacki."""
    n = len(pieces)
    beam = [(0.0, occ, 0, None)]
    for _ in range(n):
        children = {}
        for _, board, used, first in beam:
            for k in range(n):
                if (used >> k) & 1:
                    continue
                slot, pose = pieces[k]
                nused = used | (1 << k)
                for x, y, mask in PLACEMENTS[pose]:
                    if board & mask:
                        continue
                    nboard, _ = clear(board | mask)
                    key = (nboard, nused)
                    if key in children:
                        continue
                    move = first if first is not None else (slot, x, y)
                    children[key] = (value(nboard), nboard, nused, move)
        if not children:
            break
        ranked = sorted(children.values(), key=lambda s: s[0], reverse=True)
        beam = ranked[:width]
    return beam[0][3]
