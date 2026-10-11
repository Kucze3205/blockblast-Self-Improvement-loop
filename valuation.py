"""Wartość planszy: suma tablic n-krotek (pełne wiersze, pełne kolumny, okna 3x3).

Plansza to jedna liczba: bit 8*y + x dla komórki (x, y). Wartość jest w skali
przeżycia / CAP, czyli oczekiwana liczba dalszych postawień podzielona przez limit.
"""

import functools

ROW_FULL = 0xFF
COL0 = 0x0101010101010101
GATHER = 0x0102040810204080
WINDOW_ORIGINS = tuple((x0, y0) for y0 in range(6) for x0 in range(6))
LINE_ENTRIES = 256
WINDOW_ENTRIES = 512
LINE_TUPLES = 16
TUPLE_COUNT = LINE_TUPLES + len(WINDOW_ORIGINS)
WINDOW_BASE = LINE_TUPLES * LINE_ENTRIES
TABLE_SIZE = WINDOW_BASE + len(WINDOW_ORIGINS) * WINDOW_ENTRIES
FORMAT = "ntuple-v2"


def occupancy(grid):
    occ = 0
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            if cell:
                occ |= 1 << (8 * y + x)
    return occ


def piece_mask(shape, x, y):
    mask = 0
    for dy, row in enumerate(shape):
        for dx, cell in enumerate(row):
            if cell:
                mask |= 1 << (8 * (y + dy) + x + dx)
    return mask


def clear_full(occ):
    clear = 0
    for r in range(8):
        if ((occ >> (8 * r)) & ROW_FULL) == ROW_FULL:
            clear |= ROW_FULL << (8 * r)
    for c in range(8):
        col = COL0 << c
        if (occ & col) == col:
            clear |= col
    return occ & ~clear


def positions(occ):
    rows = [(occ >> (8 * r)) & ROW_FULL for r in range(8)]
    out = [r * LINE_ENTRIES + rows[r] for r in range(8)]
    for c in range(8):
        cols = ((((occ >> c) & COL0) * GATHER) >> 56) & ROW_FULL
        out.append((8 + c) * LINE_ENTRIES + cols)
    for i, (x0, y0) in enumerate(WINDOW_ORIGINS):
        idx = (
            ((rows[y0] >> x0) & 7)
            | (((rows[y0 + 1] >> x0) & 7) << 3)
            | (((rows[y0 + 2] >> x0) & 7) << 6)
        )
        out.append(WINDOW_BASE + i * WINDOW_ENTRIES + idx)
    return out


def value(table, occ):
    return sum(map(table.__getitem__, positions(occ)))


def learn(table, occ, target, alpha):
    pos = positions(occ)
    err = target - sum(map(table.__getitem__, pos))
    step = alpha * err / TUPLE_COUNT
    for p in pos:
        table[p] += step


def dump_table(table):
    return {
        "format": FORMAT,
        "tuple_count": TUPLE_COUNT,
        "table_size": TABLE_SIZE,
        "w": [round(v, 6) for v in table],
    }


def load_table(data):
    if data.get("format") != FORMAT or data.get("tuple_count") != TUPLE_COUNT:
        raise ValueError("wagi nie pasują do architektury n-krotek")
    table = [float(v) for v in data["w"]]
    if len(table) != TABLE_SIZE:
        raise ValueError("zła długość tablicy wag")
    return table


def shape_key(shape):
    return tuple(tuple(row) for row in shape)


@functools.lru_cache(maxsize=None)
def placements(key):
    mask = 0
    for dy, row in enumerate(key):
        for dx, cell in enumerate(row):
            if cell:
                mask |= 1 << (8 * dy + dx)
    h, w = len(key), len(key[0])
    shifts = tuple(8 * y + x for y in range(8 - h + 1) for x in range(8 - w + 1))
    return mask, shifts


def completable(occ, keys):
    """Czy wszystkie klocki z `keys` da się położyć kolejno, po każdym czyszczeniu linii."""
    if not keys:
        return True
    for k, key in enumerate(keys):
        mask, shifts = placements(key)
        rest = keys[:k] + keys[k + 1:]
        for s in shifts:
            pm = mask << s
            if occ & pm:
                continue
            if completable(clear_full(occ | pm), rest):
                return True
    return False
