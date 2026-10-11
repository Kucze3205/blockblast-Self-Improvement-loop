"""
Plansza jako liczba 64-bitowa: bit y*8+x dla pola (x, y). Tylko czysty Python.

Kotwica to bit 1 << (ay*8+ax). Dla poz o szerokości pw i wysokości ph dozwolone są
tylko ax <= 8-pw i ay <= 8-ph (maska valid), więc żadna komórka nie wychodzi poza
planszę ani nie zawija się do sąsiedniego wiersza.
"""
from pieces import PIECE_POOL

FULL = (1 << 64) - 1
COL0 = 0x0101010101010101
NOT_COL0 = FULL & ~COL0
NOT_COL7 = FULL & ~(COL0 << 7)
BORDER = 0xFF | (0xFF << 56) | COL0 | (COL0 << 7)


class Pose:
    __slots__ = ("cells", "base", "valid")

    def __init__(self, shape):
        ph, pw = len(shape), len(shape[0])
        self.cells = tuple(dy * 8 + dx for dy, row in enumerate(shape) for dx, cell in enumerate(row) if cell)
        self.base = sum(1 << o for o in self.cells)
        valid = 0
        for ay in range(8 - ph + 1):
            for ax in range(8 - pw + 1):
                valid |= 1 << (ay * 8 + ax)
        self.valid = valid


POSES = [Pose(piece.shape) for piece in PIECE_POOL]


def fit_mask(occ, pose):
    """Kotwice (bity 1 << ay*8+ax), w których poza mieści się na wolnych polach."""
    free = FULL & ~occ
    m = pose.valid
    for off in pose.cells:
        m &= free >> off
        if not m:
            return 0
    return m


def line_clear(occ):
    """Czyści pełne wiersze i kolumny; zwraca (nowa plansza, liczba linii)."""
    rows = occ
    for c in range(1, 8):
        rows &= occ >> c
    rows &= COL0
    cols = occ
    for r in range(1, 8):
        cols &= occ >> (8 * r)
    cols &= 0xFF
    if not (rows or cols):
        return occ, 0
    clear = rows * 0xFF | cols * COL0
    return occ & ~clear, rows.bit_count() + cols.bit_count()
