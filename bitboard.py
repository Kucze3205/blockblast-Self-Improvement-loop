"""
Bitboard 8x8: bit y*8+x dla komórki (x, y), zgodnie z Board.grid[y][x].
"""
from board import Board
from pieces import PIECE_POOL

W = Board.WIDTH
H = Board.HEIGHT
FULL = (1 << (W * H)) - 1

ROW_MASKS = [((1 << W) - 1) << (y * W) for y in range(H)]
COL_MASKS = [sum(1 << (y * W + x) for y in range(H)) for x in range(W)]
BORDER = sum(1 << (y * W + x) for y in range(H) for x in range(W)
             if x in (0, W - 1) or y in (0, H - 1))
NOT_COL0 = FULL & ~COL_MASKS[0]
NOT_COL7 = FULL & ~COL_MASKS[W - 1]


def board_to_bits(grid):
    bits = 0
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            if cell:
                bits |= 1 << (y * W + x)
    return bits


def shape_cells(shape):
    return [(dx, dy) for dy, row in enumerate(shape) for dx, cell in enumerate(row) if cell]


def pose_placements(pose_index):
    """Wszystkie (x, y, maska) dla poz `pose_index`, które mieszczą się na planszy."""
    cells = shape_cells(PIECE_POOL[pose_index].shape)
    h = len(PIECE_POOL[pose_index].shape)
    w = len(PIECE_POOL[pose_index].shape[0])
    out = []
    for y in range(H - h + 1):
        for x in range(W - w + 1):
            mask = 0
            for dx, dy in cells:
                mask |= 1 << ((y + dy) * W + (x + dx))
            out.append((x, y, mask))
    return out


PLACEMENTS = [pose_placements(i) for i in range(len(PIECE_POOL))]


def fitting_masks(board_bits, pose_index):
    return [mask for _, _, mask in PLACEMENTS[pose_index] if not board_bits & mask]


def place_and_clear(board_bits, mask):
    """Stawia klocek (maska) i czyści pełne wiersze i kolumny. Zwraca (bitboard, liczba linii)."""
    board_bits |= mask
    clear = 0
    lines = 0
    for row in ROW_MASKS:
        if board_bits & row == row:
            clear |= row
            lines += 1
    for col in COL_MASKS:
        if board_bits & col == col:
            clear |= col
            lines += 1
    return board_bits & ~clear, lines
