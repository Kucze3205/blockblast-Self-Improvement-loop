"""
Ryzyko następnej tacki: P(tacka nie da się ułożyć na danej planszy).

Część dokładna: tacka bez żadnego pasującego klocka to (suma prawdopodobieństw
martwych poz)^3. Część próbkowana: tacki, w których coś się mieści, ale całej tacki
nie da się ułożyć. Próbki są stałe (wspólne dla wszystkich kandydatów), więc
porównania między ruchami są sparowane.
"""
import random

from pieces import PIECE_POOL, PIECE_TYPES
from tray_search import completable, fits, shape_key

POSE_KEYS = [shape_key(p.shape) for p in PIECE_POOL]
POSE_PROB = [1.0 / (len(PIECE_TYPES) * len(PIECE_TYPES[p.type_index])) for p in PIECE_POOL]
SAMPLE_SEED = 14


def sample_trays(count, seed=SAMPLE_SEED):
    rng = random.Random(seed)
    return [tuple(rng.choice(rng.choice(PIECE_TYPES)) for _ in range(3)) for _ in range(count)]


def dead_mass(board):
    return sum(p for p, key in zip(POSE_PROB, POSE_KEYS) if not fits(board, key))


def death_probability(board, trays):
    fit = [fits(board, key) for key in POSE_KEYS]
    stuck = sum(1 for tray in trays
                if any(fit[p] for p in tray)
                and not completable(board, [POSE_KEYS[p] for p in tray]))
    return dead_mass(board) ** 3 + stuck / len(trays)
