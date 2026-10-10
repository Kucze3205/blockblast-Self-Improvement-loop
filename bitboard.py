from pieces import PIECE_POOL

W = 8
H = 8
FULL = (1 << (W * H)) - 1

ROW_MASK = [0xFF << (W * r) for r in range(H)]
COL_MASK = [sum(1 << (W * r + c) for r in range(H)) for c in range(W)]


def to_mask(grid):
    mask = 0
    for r, row in enumerate(grid):
        for c, cell in enumerate(row):
            if cell:
                mask |= 1 << (W * r + c)
    return mask


def _anchor_mask(h, w):
    mask = 0
    for y in range(H - h + 1):
        for x in range(W - w + 1):
            mask |= 1 << (W * y + x)
    return mask


class Pose:
    __slots__ = ("index", "type_index", "offsets", "pmask", "anchors")

    def __init__(self, piece):
        shape = piece.shape
        self.index = piece.index
        self.type_index = piece.type_index
        self.offsets = [W * dy + dx for dy, row in enumerate(shape) for dx, cell in enumerate(row) if cell]
        self.pmask = sum(1 << k for k in self.offsets)
        self.anchors = _anchor_mask(len(shape), len(shape[0]))


POSES = [Pose(piece) for piece in PIECE_POOL]


def fit(pose, free):
    mask = pose.anchors
    for k in pose.offsets:
        mask &= free >> k
        if not mask:
            break
    return mask


def bits(mask):
    while mask:
        low = mask & -mask
        yield low.bit_length() - 1
        mask ^= low


def place(occ, pose, anchor):
    return occ | (pose.pmask << anchor)


def clear_full(occ):
    clear = 0
    lines = 0
    for mask in ROW_MASK:
        if (occ & mask) == mask:
            clear |= mask
            lines += 1
    for mask in COL_MASK:
        if (occ & mask) == mask:
            clear |= mask
            lines += 1
    return occ & ~clear, lines
