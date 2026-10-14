#!/usr/bin/env python3
"""Klocki pętli bez agenta: sonda poświadczenia, przyczyna maszynowa, rekord węzła i historia prób.

Zero agenta. Uruchamiany z checkoutu gałęzi domyślnej, nigdy z gałęzi łańcucha —
agent nie może zmienić kodu, który go pilnuje.

Podpolecenia: probe, limit, czekaj, start, historia, koniec. Kontrakt rekordu: docs/loop-config.md.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

TREES = "trees"
ROOT = "korzen"
FALLBACK_PARK = timedelta(minutes=60)   # limit bez czytelnego terminu resetu: okno sesyjne ma 5 h


def now():
    return datetime.now(timezone.utc)


def parse_time(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def probe():
    """Sonda poświadczenia: 200 żyje, 401 martwy, 403 odwołany. Nie zjada limitu."""
    req = urllib.request.Request("https://api.anthropic.com/v1/models", headers={
        "Authorization": "Bearer " + os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", ""),
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "oauth-2025-04-20",
    })
    try:
        return urllib.request.urlopen(req, timeout=20).status
    except urllib.error.HTTPError as e:
        return e.code
    except OSError:
        return 0    # przejściowa awaria sieci to nie martwe poświadczenie


# ---------------------------------------------------------------- przyczyna

def machine_cause(exec_path, exit_code):
    """Przyczyna dosłownie z pliku wykonania, bez interpretacji. Nigdy po `subtype`."""
    if not os.path.exists(exec_path):
        return "brak-pliku-wykonania exit=%s" % exit_code, False, None
    with open(exec_path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    try:
        d = json.loads(raw)
        d = d[-1] if isinstance(d, list) and d else d
    except ValueError:
        d = {}
    parts = []
    if d.get("api_error_status"):
        parts.append("api_error_status=%s" % d["api_error_status"])
    if d.get("terminal_reason"):
        parts.append("terminal_reason=%s" % d["terminal_reason"])
    if d.get("is_error") and not parts:
        parts.append("is_error=true")
    if exit_code not in ("0", "", None):
        parts.append("exit=%s" % exit_code)
    limited = bool(re.search(r"hit your .{0,40}limit|rate_limit", raw, re.I))
    m = re.search(r'"resets?_?[aA]t"\s*:\s*(\d{10,13})', raw)
    reset = None
    if m:
        ts = int(m.group(1))
        reset = datetime.fromtimestamp(ts / 1000 if ts > 10**11 else ts, timezone.utc)
    return " ".join(parts), limited, reset or text_reset(raw)


RESET_TEXT = re.compile(r"resets\s+(?:([A-Z][a-z]{2})\s+(\d{1,2}),?\s+(?:at\s+)?)?(\d{1,2})(?::(\d{2}))?\s*([ap]m)\s*(?:\(([^)]+)\))?", re.I)


def text_reset(raw, ref=None):
    """'resets 7:20am (UTC)' / 'resets Oct 2, 5am (Europe/Warsaw)': termin z tekstu CLI, gdy brak `resetsAt`."""
    m = RESET_TEXT.search(raw)
    if not m:
        return None
    mon, day, h, mi, ap, tz = m.groups()
    try:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(tz) if tz else timezone.utc
    except Exception:
        zone = timezone.utc
    ref = (ref or now()).astimezone(zone)
    h = int(h) % 12 + (12 if ap.lower() == "pm" else 0)
    t = ref.replace(hour=h, minute=int(mi or 0), second=0, microsecond=0)
    if mon:
        t = t.replace(month=datetime.strptime(mon[:3].title(), "%b").month, day=int(day))
        if t < ref - timedelta(days=1):
            t = t.replace(year=t.year + 1)
    elif t <= ref:
        t += timedelta(days=1)
    return t.astimezone(timezone.utc)


def limit_s(exec_path, exit_code, t):
    """Sekundy do końca limitu subskrypcji po sesji; 0, gdy sesja nie padła na limicie."""
    _, limited, reset = machine_cause(exec_path, exit_code)
    if not limited:
        return 0
    return max(60, int(((reset if reset and reset > t else t + FALLBACK_PARK) - t).total_seconds()))


# ---------------------------------------------------------------- rekord węzła

def parent_of(node):
    """`2.3` -> `2.2`; `2.1` -> None (rodzicem jest korzeń)."""
    chain, depth = node.split(".")
    return "%s.%d" % (chain, int(depth) - 1) if int(depth) > 1 else None


def record_path(base, tree, node):
    return os.path.join(base, TREES, str(tree), node + ".json")


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path, d):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
        fh.write("\n")


def load_tree(base, tree):
    d = os.path.join(base, TREES, str(tree))
    if not os.path.isdir(d):
        return {}
    return {f[:-5]: read_json(os.path.join(d, f)) for f in os.listdir(d) if f.endswith(".json")}


def czekaj(rec, t):
    """Sekundy do `wznow_po` węzła zaparkowanego na limicie; 0, gdy nie ma na co czekać."""
    if not rec or rec.get("stan") != "zaparkowany":
        return 0
    return max(0, int((parse_time(rec["wznow_po"]) - t).total_seconds()))


def start(base, tree, node, order, root_sha, t):
    """Otwiera sesję węzła: nowy rekord albo kontynuacja (park, tury, padnięty runner). Zwraca (rekord, kontynuacja)."""
    path = record_path(base, tree, node)
    rec = read_json(path) if os.path.exists(path) else None
    if rec and rec["stan"] in ("ocena w toku", "oceniony"):
        raise SystemExit("węzeł %s/%s ma już sesję za sobą (%s)" % (tree, node, rec["stan"]))
    if rec is None:
        parent = parent_of(node)
        if parent:
            prec = read_json(record_path(base, tree, parent))
            if prec["stan"] != "oceniony":
                raise SystemExit("rodzic %s nieoceniony (%s)" % (parent, prec["stan"]))
            parent_sha = prec["sha"]
        else:
            parent_sha = root_sha
        rec = {"rodzic": parent or ROOT, "rodzic_sha": parent_sha, "kolejnosc": int(order),
               "sha": parent_sha, "stan": "sesja", "gist": "", "notatki": [],
               "koszt": {"tury": 0, "usd": 0.0, "minuty": 0.0}, "oczekiwanie_min": 0.0,
               "kontynuacje_tur": 0, "sesje": []}
        cont = False
    else:
        if rec.get("zaparkowano"):
            rec["oczekiwanie_min"] = round(rec["oczekiwanie_min"] + (t - parse_time(rec["zaparkowano"])).total_seconds() / 60, 1)
        rec.pop("zaparkowano", None)
        rec.pop("wznow_po", None)
        cont = True
    rec["stan"] = "sesja"
    write_json(path, rec)
    return rec, cont


def finish(base, tree, node, exec_path, exit_code, sha, notes, started, t):
    """Zamyka sesję: koszt, notatki, SHA i następny krok: park | kontynuuj | dziedzicz | ocena."""
    path = record_path(base, tree, node)
    rec = read_json(path)
    cause, limited, reset = machine_cause(exec_path, exit_code)
    try:
        result = read_json(exec_path)
    except (OSError, ValueError):
        result = {}
    turns = result.get("num_turns") or 0
    k = rec["koszt"]
    k["tury"] += turns
    k["usd"] = round(k["usd"] + (result.get("total_cost_usd") or 0), 4)
    k["minuty"] = round(k["minuty"] + (t - started).total_seconds() / 60, 1)
    rec["sesje"].append({"start": iso(started), "koniec": iso(t), "tury": turns, "przyczyna": cause or "ok"})
    rec["sha"] = sha
    rec["notatki"] = notes
    rec["gist"] = notes[0].splitlines()[0] if notes else ""
    if limited:
        rec["stan"] = "zaparkowany"
        rec["zaparkowano"] = iso(t)
        rec["wznow_po"] = iso(reset if reset and reset > t else t + FALLBACK_PARK)
        action = "park"
    elif result.get("subtype") == "error_max_turns" and rec["kontynuacje_tur"] < 1:
        rec["kontynuacje_tur"] += 1
        action = "kontynuuj"
    elif sha == rec["rodzic_sha"] and rec["rodzic"] != ROOT:
        # bez zmian w kodzie: oceny rodzica, bez ponownej oceny
        rec["stan"] = "oceniony"
        rec["oceny"] = read_json(record_path(base, tree, rec["rodzic"])).get("oceny")
        action = "dziedzicz"
    else:
        rec["stan"] = "ocena w toku"
        action = "ocena"
    write_json(path, rec)
    return action


def split_notes(raw):
    """`git log --format=%B%x1e`: komunikaty commitów węzła, najnowszy pierwszy."""
    return [n.strip() for n in raw.split("\x1e") if n.strip()]


# ---------------------------------------------------------------- historia prób

def latest(d):
    return list(d.values())[-1] if d else None


def s_v(rec):
    o = rec.get("oceny") or {}
    if o.get("s_emu") is not None:
        return 1 + o["s_emu"]
    return latest(o.get("s_sym") or {})


def fmt(x):
    return "—" if x is None else "%.3f" % x


def czas_oceny(o):
    """Czas oceny symulatorem; `za wolna` = ocena przekroczyła limit i nie dostaje serii (#48)."""
    czas = o.get("czas_sym_min")
    wolna = (latest(o.get("sym") or {}) or {}).get("za_wolna")
    return ("—" if czas is None else "%.1f" % czas) + (" za wolna" if wolna else "")


def table(recs):
    lines = ["| węzeł | rodzic | s_sym | s_emu | ocena [min] | gist |", "|---|---|---|---|---|---|"]
    for name, r in sorted(recs.items(), key=lambda kv: kv[1]["kolejnosc"]):
        o = r.get("oceny") or {}
        lines.append("| %s | %s | %s | %s | %s | %s |" % (name, r["rodzic"], fmt(latest(o.get("s_sym") or {})),
                                                          fmt(o.get("s_emu")), czas_oceny(o), r["gist"].replace("|", "/")))
    return lines


def evaluated(base, tree):
    return {n: r for n, r in load_tree(base, tree).items() if r.get("stan") == "oceniony"}


def widok(rec):
    """Rekord dla agenta: bez `przezycie` (lista wyników po rozdaniach, 1200 liczb na ocenę, ok. 40% rozmiaru rekordów; zostaje `przegrane`, `punkty_srednie`, `s_sym`) (#50)."""
    sym = {h: {k: v for k, v in s.items() if k != "przezycie"} for h, s in ((rec.get("oceny") or {}).get("sym") or {}).items()}
    return {**rec, "oceny": {**rec["oceny"], "sym": sym}} if sym else rec


def historia(base, tree, node, out, diff):
    """Rozkłada `.historia/`: indeks, rekordy ocenionych węzłów, patche innych łańcuchów i najlepszego węzła (diff(sha) -> tekst)."""
    tree = int(tree)
    cur = evaluated(base, tree)
    lines = ["# Indeks prób", "", "## Drzewo %d (bieżące)" % tree, ""] + table(cur)
    for name, r in cur.items():
        write_json(os.path.join(out, str(tree), name + ".json"), widok(r))
    own = node.split(".")[0]
    leaves = {}
    for name, r in cur.items():
        chain, depth = name.split(".")
        if chain != own and int(depth) > leaves.get(chain, (0, None))[0]:
            leaves[chain] = (int(depth), r["sha"])
    for chain, (_, sha) in leaves.items():
        with open(os.path.join(out, str(tree), chain + ".patch"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(diff(sha))
    if leaves:
        lines += ["", "Kod innych łańcuchów względem korzenia: `%d/<łańcuch>.patch`." % tree]
    older = sorted(int(d) for d in os.listdir(os.path.join(base, TREES))
                   if d.isdigit() and int(d) < tree) if os.path.isdir(os.path.join(base, TREES)) else []
    if older:
        lines += ["", "## Poprzednie drzewa", "", "| drzewo | najlepsze s_v | węzłów | indeks |", "|---|---|---|---|"]
    for t in older:
        recs = evaluated(base, t)
        for name, r in recs.items():
            write_json(os.path.join(out, str(t), name + ".json"), widok(r))
        with open(os.path.join(out, str(t), "INDEKS.md"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(["# Drzewo %d" % t, ""] + table(recs)) + "\n")
        best = max((v for v in map(s_v, recs.values()) if v is not None), default=None)
        lines.append("| %d | %s | %d | `%d/INDEKS.md` |" % (t, fmt(best), len(recs), t))
    best = max(((s_v(r), -t, -r["kolejnosc"], t, n, r["sha"]) for t, recs in [(tree, cur)] + [(t, evaluated(base, t)) for t in older]
                for n, r in recs.items() if s_v(r) is not None), default=None)
    if best and not (best[3] == tree and best[4].split(".")[0] == own):
        _, _, _, t, n, sha = best
        with open(os.path.join(out, "najlepszy.patch"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(diff(sha))
        lines += ["", "Kod najlepszego węzła ze wszystkich drzew (%s/%s, s_v %s) względem korzenia: `najlepszy.patch`." % (t, n, fmt(best[0]))]
    lines += ["", "Pełne rekordy (wyniki per partia, plansze przegranych, notatki): `<drzewo>/<węzeł>.json`."]
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "INDEKS.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def git_diff(repo, root_sha):
    def diff(sha):
        return subprocess.run(["git", "-C", repo, "diff", root_sha, sha, "--", ".", ":(exclude)*.pth"],
                              capture_output=True, text=True, check=True).stdout
    return diff


# ---------------------------------------------------------------- main

def main(argv):
    cmd, args = argv[1], argv[2:]
    base = os.getcwd()
    if cmd == "probe":
        code = probe()
        print("sonda: HTTP %s" % code)
        return 1 if code in (401, 403) else 0
    if cmd == "limit":
        exec_path, exit_code = args
        print(limit_s(exec_path, exit_code, now()))
        return 0
    if cmd == "czekaj":
        tree, node = args
        path = record_path(base, tree, node)
        print(czekaj(read_json(path) if os.path.exists(path) else None, now()))
        return 0
    if cmd == "start":
        tree, node, order, root_sha = args
        rec, cont = start(base, tree, node, order, root_sha, now())
        print("RODZIC_SHA=%s\nKONTYNUACJA=%d" % (rec["rodzic_sha"], cont))
        return 0
    if cmd == "historia":
        tree, node, out, root_sha = args
        shutil.rmtree(out, ignore_errors=True)
        historia(base, tree, node, out, git_diff(base, root_sha))
        return 0
    if cmd == "koniec":
        tree, node, exec_path, exit_code, sha, notes_path, started = args
        with open(notes_path, encoding="utf-8", errors="replace") as fh:
            notes = split_notes(fh.read())
        started = datetime.fromtimestamp(int(started), timezone.utc)
        print(finish(base, tree, node, exec_path, exit_code, sha, notes, started, now()))
        return 0
    raise SystemExit("nieznane polecenie: " + cmd)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
