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
NEAR = 0.01       # łańcuch z rekordem w tej odległości od najlepszego nie jest zamykany za zastój
STOP_DEPTH = 4    # od tej głębokości sprawdzamy, czy drzewo jeszcze się opłaca
STOP_GAIN = 0.005 # minimalny wzrost rekordu drzewa w dwóch ostatnich warstwach, by kontynuować
CLIMB = 0.05      # ostatni skok łańcucha co najmniej tyle: łańcuch rośnie, nie porzucamy go ani nie kończymy drzewa


def _stalled(nodes):
    """Czy ostatnie MISSES węzłów nie pobiło wcześniejszego rekordu łańcucha."""
    if len(nodes) < SHALLOW or len(nodes) <= MISSES:
        return False
    best = max(o["s_v"] for o in nodes[:-MISSES])
    return all(o["s_v"] < best + EPS for o in nodes[-MISSES:])


def _gain_dried_up(obs):
    """Czy dwie ostatnie warstwy głębokości nie podniosły rekordu drzewa o STOP_GAIN.

    Każda runda kosztuje czas (beta * godziny), a w głębi drzewa zyski są małe,
    więc brak postępu przez dwie rundy oznacza, że dalsze otwieranie się nie zwróci."""
    depth = max(o["glebokosc"] for o in obs)
    if depth < STOP_DEPTH:
        return False
    old = [o["s_v"] for o in obs if o["glebokosc"] < depth - 1]
    new = [o["s_v"] for o in obs if o["glebokosc"] >= depth - 1]
    if not old or not new:
        return False
    return max(new) - max(old) < STOP_GAIN


def _climbing(nodes):
    """Czy ostatni węzeł (nie korzeń) był dużym skokiem, czyli łańcuch wciąż szybko rośnie."""
    tip = nodes[-1]
    return tip["glebokosc"] >= 2 and (tip.get("delta") or 0.0) >= CLIMB


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
    # brak postępu w drzewie zatrzymuje je, chyba że jakiś żywy łańcuch wciąż gwałtownie rośnie
    if _gain_dried_up(obs) and not any(
            _climbing(nodes) for nodes in chains.values() if nodes[-1]["wezel"] in legal):
        return []
    global_best = max(o["s_v"] for o in obs)
    remaining = max(0, question.max_rounds - question.round - 1)
    gap = GAP + GAP_PER_ROUND * remaining
    packet = []
    for nodes in chains.values():
        tip = nodes[-1]["wezel"]
        if tip not in legal:
            continue
        if len(nodes) >= SHALLOW:
            record = max(o["s_v"] for o in nodes)
            # łańcuch blisko najlepszego wyniku daje darmowe losowania przy szczycie
            # (paczka kosztuje tyle co najdłuższy węzeł), więc zatrzymany nie jest zamykany
            if _stalled(nodes) and record < global_best - NEAR:
                continue
            # łańcuch po dużym skoku nie jest jeszcze skreślony: głębsze próby mogą go odbić
            if record < global_best - gap and not _climbing(nodes):
                continue
        packet.append(tip)
    # wolne miejsca w paczce: nowe łańcuchy tylko na początku drzewa
    if can_open and question.round <= 1:
        packet += [None] * (width - len(packet))
    return packet[:width]
