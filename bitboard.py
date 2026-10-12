"""Plansza 8x8 jako liczba całkowita: bit y*8+x to zajęte pole (x, y).

Kotwica klocka to pozycja jego lewego górnego rogu, tak jak w Game.available_actions.
"""
from pieces import PIECE_POOL, PIECE_TYPES

SIZE = 8
FULL = (1 << (SIZE * SIZE)) - 1
ROW_MASKS = [0xFF << (SIZE * r) for r in range(SIZE)]
COL_MASKS = [sum(1 << (SIZE * r + c) for r in range(SIZE)) for c in range(SIZE)]


def _cells(shape):
    return [(dy, dx) for dy, row in enumerate(shape) for dx, cell in enumerate(row) if cell]


def _anchors_for_offset(dy, dx):
    return sum(1 << (y * SIZE + x) for y in range(SIZE - dy) for x in range(SIZE - dx))


POSE_CELLS = [_cells(piece.shape) for piece in PIECE_POOL]
POSE_PATTERN = [sum(1 << (dy * SIZE + dx) for dy, dx in cells) for cells in POSE_CELLS]
# Generator losuje typ jednostajnie, a potem pozę jednostajnie w obrębie typu.
POSE_PROB = [1 / (len(PIECE_TYPES) * len(PIECE_TYPES[piece.type_index])) for piece in PIECE_POOL]

_OFFSETS = sorted({off for cells in POSE_CELLS for off in cells})
_OFFSET_ID = {off: i for i, off in enumerate(_OFFSETS)}
_OFFSET_SHIFT = [dy * SIZE + dx for dy, dx in _OFFSETS]
_OFFSET_VALID = [_anchors_for_offset(dy, dx) for dy, dx in _OFFSETS]
_POSE_OFFSET_IDS = [[_OFFSET_ID[off] for off in cells] for cells in POSE_CELLS]


def occupancy(grid):
    return sum(1 << (r * SIZE + c) for r, row in enumerate(grid) for c, cell in enumerate(row) if cell)


def fit_masks(occupied):
    """Dla każdej poz maska kotwic, na których cały klocek mieści się na wolnych polach."""
    empty = ~occupied & FULL
    shifted = [(empty >> shift) & valid for shift, valid in zip(_OFFSET_SHIFT, _OFFSET_VALID)]
    masks = []
    for ids in _POSE_OFFSET_IDS:
        mask = shifted[ids[0]]
        for i in ids[1:]:
            mask &= shifted[i]
        masks.append(mask)
    return masks


def fit_stats(masks):
    """Szansa, że losowy klocek mieści się gdziekolwiek, oraz oczekiwana liczba jego kotwic."""
    fit = places = 0.0
    for mask, prob in zip(masks, POSE_PROB):
        if mask:
            fit += prob
            places += prob * mask.bit_count()
    return fit, places


def place(occupied, pose, x, y):
    """Plansza po postawieniu pozy z kotwicą (x, y) i wyczyszczeniu pełnych linii oraz liczba tych linii. Ruch musi być legalny."""
    occ = occupied | (POSE_PATTERN[pose] << (y * SIZE + x))
    rows = [r for r in range(SIZE) if (occ & ROW_MASKS[r]) == ROW_MASKS[r]]
    cols = [c for c in range(SIZE) if (occ & COL_MASKS[c]) == COL_MASKS[c]]
    for r in rows:
        occ &= ~ROW_MASKS[r]
    for c in cols:
        occ &= ~COL_MASKS[c]
    return occ, len(rows) + len(cols)
