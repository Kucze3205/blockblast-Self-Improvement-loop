"""Polityka drzewa: którą paczkę węzłów otworzyć w następnej rundzie.

Deterministyczna: bez losowania, bez czasu, bez niczego poza `question`.
`solve(question)` zwraca listę akcji: `None` otwiera nowy łańcuch od korzenia,
nazwa liścia (`"2.3"`) kontynuuje jego łańcuch. Pusta lista kończy drzewo.

Widok `question`: `max_parallelism` (W), `max_rounds` (K), `round` (ukończone rundy),
`baseline_score`, `observed()` (ocenione węzły: `wezel`, `lancuch`, `glebokosc`, `rodzic`,
`s_v`, `delta` względem rodzica) i `legal_actions()`. Maszyneria odrzuca akcje niedozwolone
i obcina paczkę do W, więc polityka nie musi pilnować kontraktu.
"""
MISSES = 2        # tyle kolejnych węzłów bez pobicia własnego rekordu łańcucha zamyka go
SHALLOW = 3       # łańcuchy płytsze niż to dostają szansę na odbicie
EPS = 0.002       # minimalna poprawa rekordu łańcucha, by liczyła się jako trafienie
GAP = 0.03        # łańcuch, którego rekord jest o tyle gorszy od najlepszego w drzewie, jest porzucany
GAP_PER_ROUND = 0.01   # tyle luzu więcej na każdą pozostałą rundę


def _stalled(nodes):
    """Czy ostatnie MISSES węzłów nie pobiło wcześniejszego rekordu łańcucha."""
    if len(nodes) < SHALLOW or len(nodes) <= MISSES:
        return False
    best = max(o["s_v"] for o in nodes[:-MISSES])
    return all(o["s_v"] < best + EPS for o in nodes[-MISSES:])


def solve(question):
    obs = question.observed()
    legal = set(a for a in question.legal_actions() if a is not None)
    can_open = None in question.legal_actions()
    width = question.max_parallelism
    if not obs:
        return [None] * width if can_open else []
    chains = {}
    for o in obs:
        chains.setdefault(o["lancuch"], []).append(o)
    global_best = max(o["s_v"] for o in obs)
    remaining = max(0, question.max_rounds - question.round - 1)
    gap = GAP + GAP_PER_ROUND * remaining
    packet = []
    for nodes in chains.values():
        tip = nodes[-1]["wezel"]
        if tip not in legal:
            continue
        if len(nodes) >= SHALLOW:
            if _stalled(nodes):
                continue
            if max(o["s_v"] for o in nodes) < global_best - gap:
                continue
        packet.append(tip)
    # wolne miejsca w paczce: nowe łańcuchy tylko na początku drzewa
    if can_open and question.round <= 1:
        packet += [None] * (width - len(packet))
    return packet[:width]
