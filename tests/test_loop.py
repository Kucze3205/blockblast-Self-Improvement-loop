"""Testy czystej logiki klocków pętli: przyczyna maszynowa, rekord węzła i historia prób."""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from datetime import timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("loop", os.path.join(ROOT, ".github", "loop", "loop.py"))
loop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loop)

class PrzyczynaTest(unittest.TestCase):
    def cause(self, payload, exit_code="0"):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            fh.write(payload if isinstance(payload, str) else json.dumps(payload))
        try:
            return loop.machine_cause(fh.name, exit_code)
        finally:
            os.unlink(fh.name)

    def test_auth_401_mimo_subtype_success(self):
        c, limited, _ = self.cause({"subtype": "success", "is_error": True, "api_error_status": 401, "terminal_reason": "api_error"})
        self.assertEqual(c, "api_error_status=401 terminal_reason=api_error")
        self.assertFalse(limited)

    def test_limit_subskrypcji(self):
        _, limited, _ = self.cause({"is_error": True, "result": "You've hit your session limit"})
        self.assertTrue(limited)

    def test_czekanie_na_limit_w_sekundach(self):
        t = loop.now()
        reset = int((t + timedelta(minutes=30)).timestamp())
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump({"is_error": True, "result": "You've hit your session limit", "resetsAt": reset}, fh)
        try:
            self.assertAlmostEqual(loop.limit_s(fh.name, "1", t), 1800, delta=2)
            self.assertEqual(loop.limit_s(fh.name + ".brak", "1", t), 0)   # brak pliku wykonania to nie limit
        finally:
            os.unlink(fh.name)

    def test_termin_resetu_w_sekundach_i_milisekundach(self):
        _, _, r1 = self.cause('{"resetsAt": 1790000000}')
        _, _, r2 = self.cause('{"resets_at": 1790000000000}')
        self.assertEqual(r1, r2)

    def test_termin_resetu_z_tekstu_cli(self):
        ref = loop.parse_time("2026-09-26T06:24:22Z")
        self.assertEqual(loop.text_reset("You've hit your session limit · resets 7:20am (UTC)", ref),
                         loop.parse_time("2026-09-26T07:20:00Z"))
        self.assertEqual(loop.text_reset("resets 5am (UTC)", ref), loop.parse_time("2026-09-27T05:00:00Z"))
        self.assertEqual(loop.text_reset("resets 3pm (Europe/Warsaw)", ref), loop.parse_time("2026-09-26T13:00:00Z"))
        self.assertEqual(loop.text_reset("resets Oct 2, 5am (UTC)", ref), loop.parse_time("2026-10-02T05:00:00Z"))
        self.assertIsNone(loop.text_reset("brak terminu", ref))

    def test_limit_z_terminem_w_tekscie(self):
        _, limited, reset = self.cause({"is_error": True, "result": "You've hit your session limit · resets 11:59pm (UTC)"})
        self.assertTrue(limited)
        self.assertEqual((reset.hour, reset.minute), (23, 59))

    def test_zwykly_blad_zadania(self):
        c, limited, reset = self.cause({"is_error": False, "result": "ok"}, exit_code="124")
        self.assertEqual((c, limited, reset), ("exit=124", False, None))

    def test_brak_pliku(self):
        c, limited, _ = loop.machine_cause("/nie/ma/takiego.json", "1")
        self.assertIn("brak-pliku-wykonania", c)
        self.assertFalse(limited)

T0 = loop.parse_time("2026-10-05T10:00:00Z")


class Drzewo(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()

    def rec(self, node):
        return loop.read_json(loop.record_path(self.base, 1, node))

    def wynik(self, payload):
        p = os.path.join(self.base, "wynik.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return p

    def oceniony(self, node, sha, s_sym=None, s_emu=None, gist="g", tree=1):
        parent = loop.parent_of(node)
        loop.write_json(loop.record_path(self.base, tree, node), {
            "rodzic": parent or "korzen", "rodzic_sha": "x", "kolejnosc": int(node.split(".")[1]) * 10 + int(node.split(".")[0]),
            "sha": sha, "stan": "oceniony", "gist": gist, "notatki": [gist],
            "oceny": {"s_sym": {"h1": 0.1, "h2": s_sym}, "s_emu": s_emu}})


class RekordTest(Drzewo):
    def test_rodzic(self):
        self.assertEqual(loop.parent_of("2.3"), "2.2")
        self.assertIsNone(loop.parent_of("2.1"))

    def test_nowy_wezel_od_korzenia(self):
        rec, cont = loop.start(self.base, 1, "1.1", 3, "K", T0)
        self.assertFalse(cont)
        self.assertEqual((rec["rodzic"], rec["rodzic_sha"], rec["kolejnosc"], rec["stan"]), ("korzen", "K", 3, "sesja"))

    def test_nowy_wezel_od_ocenionego_rodzica(self):
        self.oceniony("1.1", "A")
        rec, _ = loop.start(self.base, 1, "1.2", 5, "K", T0)
        self.assertEqual((rec["rodzic"], rec["rodzic_sha"]), ("1.1", "A"))

    def test_rodzic_nieoceniony_blokuje(self):
        loop.start(self.base, 1, "1.1", 1, "K", T0)
        with self.assertRaises(SystemExit):
            loop.start(self.base, 1, "1.2", 2, "K", T0)

    def test_skonczony_wezel_nie_rusza_drugi_raz(self):
        self.oceniony("1.1", "A")
        with self.assertRaises(SystemExit):
            loop.start(self.base, 1, "1.1", 1, "K", T0)

    def test_koniec_do_oceny_z_kosztem_i_notatkami(self):
        loop.start(self.base, 1, "1.1", 1, "K", T0)
        a = loop.finish(self.base, 1, "1.1", self.wynik({"subtype": "success", "num_turns": 40, "total_cost_usd": 1.5}),
                        "0", "B", ["Sedno\n\nCo dalej: nic", "starsza"], T0, T0 + timedelta(minutes=90))
        r = self.rec("1.1")
        self.assertEqual(a, "ocena")
        self.assertEqual((r["stan"], r["sha"], r["gist"]), ("ocena w toku", "B", "Sedno"))
        self.assertEqual(r["koszt"], {"tury": 40, "usd": 1.5, "minuty": 90.0})
        self.assertEqual(r["sesje"][0]["przyczyna"], "ok")

    @mock.patch.object(loop, "now", lambda: T0)   # "resets 1pm" liczy się od zegara; bez tego test zależy od dnia uruchomienia
    def test_limit_parkuje_a_wznowienie_liczy_oczekiwanie(self):
        loop.start(self.base, 1, "1.1", 1, "K", T0)
        a = loop.finish(self.base, 1, "1.1", self.wynik({"is_error": True, "result": "You've hit your session limit · resets 1pm (UTC)"}),
                        "1", "B", [], T0, T0 + timedelta(minutes=30))
        r = self.rec("1.1")
        self.assertEqual((a, r["stan"], r["wznow_po"]), ("park", "zaparkowany", "2026-10-05T13:00:00Z"))
        self.assertEqual(loop.czekaj(r, T0 + timedelta(hours=2)), 3600)
        rec, cont = loop.start(self.base, 1, "1.1", 1, "K", T0 + timedelta(hours=3))
        self.assertTrue(cont)
        self.assertEqual((rec["stan"], rec["oczekiwanie_min"]), ("sesja", 150.0))
        self.assertNotIn("wznow_po", rec)
        self.assertEqual(loop.czekaj(rec, T0), 0)

    def test_limit_bez_terminu_czeka_godzine(self):
        loop.start(self.base, 1, "1.1", 1, "K", T0)
        loop.finish(self.base, 1, "1.1", self.wynik({"is_error": True, "result": "You've hit your weekly limit"}), "1", "K", [], T0, T0)
        self.assertEqual(self.rec("1.1")["wznow_po"], "2026-10-05T11:00:00Z")

    def test_budzet_tur_daje_jedna_kontynuacje(self):
        loop.start(self.base, 1, "1.1", 1, "K", T0)
        tury = self.wynik({"subtype": "error_max_turns", "num_turns": 150})
        self.assertEqual(loop.finish(self.base, 1, "1.1", tury, "1", "B", [], T0, T0), "kontynuuj")
        loop.start(self.base, 1, "1.1", 1, "K", T0)
        self.assertEqual(loop.finish(self.base, 1, "1.1", tury, "1", "C", [], T0, T0), "ocena")
        self.assertEqual(self.rec("1.1")["koszt"]["tury"], 300)

    def test_bez_zmian_dziedziczy_oceny_rodzica(self):
        self.oceniony("1.1", "A", s_sym=0.5)
        loop.start(self.base, 1, "1.2", 2, "K", T0)
        self.assertEqual(loop.finish(self.base, 1, "1.2", self.wynik({"subtype": "success"}), "0", "A", [], T0, T0), "dziedzicz")
        r = self.rec("1.2")
        self.assertEqual((r["stan"], r["oceny"]["s_sym"]["h2"]), ("oceniony", 0.5))

    def test_korzen_bez_zmian_idzie_do_oceny(self):
        loop.start(self.base, 1, "1.1", 1, "K", T0)
        self.assertEqual(loop.finish(self.base, 1, "1.1", self.wynik({"subtype": "success"}), "0", "K", [], T0, T0), "ocena")

    def test_notatki_z_logu(self):
        self.assertEqual(loop.split_notes("Nowa\n\nciało\n\x1e\nStara\n\x1e\n"), ["Nowa\n\nciało", "Stara"])


class HistoriaTest(Drzewo):
    def test_indeks_rekordy_patche_i_poprzednie_drzewa(self):
        self.oceniony("1.1", "P", s_sym=0.4, tree=1)
        self.oceniony("2.1", "Q", s_emu=0.7, tree=1)
        self.oceniony("1.1", "A", s_sym=0.5, gist="a|b", tree=2)
        self.oceniony("1.2", "A2", s_sym=0.6, tree=2)
        self.oceniony("2.1", "B", s_sym=0.2, tree=2)
        self.oceniony("2.2", "B2", s_emu=0.3, tree=2)
        loop.write_json(loop.record_path(self.base, 2, "3.1"), {"stan": "ocena w toku", "kolejnosc": 99})
        out = os.path.join(self.base, ".historia")
        loop.historia(self.base, 2, "1.3", out, lambda sha: "patch " + sha)
        with open(os.path.join(out, "INDEKS.md"), encoding="utf-8") as fh:
            idx = fh.read()
        self.assertIn("| 1.1 | korzen | 0.500 | — | — | a/b |", idx)
        self.assertIn("| 2.2 | 2.1 | — | 0.300 | — | g |", idx)
        self.assertNotIn("3.1", idx)
        self.assertIn("| 1 | 1.700 | 2 | `1/INDEKS.md` |", idx)
        with open(os.path.join(out, "2", "2.patch"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "patch B2")
        self.assertFalse(os.path.exists(os.path.join(out, "2", "1.patch")))
        self.assertTrue(os.path.exists(os.path.join(out, "1", "INDEKS.md")))
        self.assertEqual(loop.read_json(os.path.join(out, "1", "2.1.json"))["sha"], "Q")

    def test_indeks_pokazuje_czas_oceny_i_za_wolna(self):
        self.oceniony("1.1", "A", s_sym=0.5)
        self.oceniony("2.1", "B", s_sym=0.6)
        for node, czas, wolna in (("1.1", 3.84, False), ("2.1", 57.8, True)):
            rec = self.rec(node)
            rec["oceny"].update(czas_sym_min=czas, sym={"h2": {"za_wolna": wolna}})
            loop.write_json(loop.record_path(self.base, 1, node), rec)
        out = os.path.join(self.base, ".historia")
        loop.historia(self.base, 1, "1.2", out, lambda sha: "")
        with open(os.path.join(out, "INDEKS.md"), encoding="utf-8") as fh:
            idx = fh.read()
        self.assertIn("| 1.1 | korzen | 0.500 | — | 3.8 | g |", idx)
        self.assertIn("| 2.1 | korzen | 0.600 | — | 57.8 za wolna | g |", idx)

    def test_najlepszy_wezel_ze_wszystkich_drzew_jako_patch(self):
        self.oceniony("1.1", "P", s_sym=0.9, tree=1)
        self.oceniony("2.1", "Q", s_sym=0.4, tree=1)
        self.oceniony("1.1", "A", s_sym=0.5, tree=2)
        out = os.path.join(self.base, ".historia")
        loop.historia(self.base, 2, "2.2", out, lambda sha: "patch " + sha)
        with open(os.path.join(out, "najlepszy.patch"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "patch P")
        with open(os.path.join(out, "INDEKS.md"), encoding="utf-8") as fh:
            self.assertIn("(1/1.1, s_v 0.900)", fh.read())

    def test_najlepszy_we_wlasnym_lancuchu_nie_dostaje_patcha(self):
        self.oceniony("1.1", "P", s_sym=0.9, tree=2)
        self.oceniony("2.1", "Q", s_sym=0.4, tree=2)
        out = os.path.join(self.base, ".historia")
        loop.historia(self.base, 2, "1.2", out, lambda sha: "patch " + sha)
        self.assertFalse(os.path.exists(os.path.join(out, "najlepszy.patch")))

    def test_rekord_dla_agenta_bez_listy_przezyc(self):
        self.oceniony("1.1", "A", s_sym=0.5)
        rec = self.rec("1.1")
        rec["oceny"]["sym"] = {"h2": {"przezycie": [1, 2, 3], "przegrane": 2, "punkty_srednie": 9.5}}
        loop.write_json(loop.record_path(self.base, 1, "1.1"), rec)
        out = os.path.join(self.base, ".historia")
        loop.historia(self.base, 1, "1.2", out, lambda sha: "")
        got = loop.read_json(os.path.join(out, "1", "1.1.json"))
        self.assertEqual(got["oceny"]["sym"], {"h2": {"przegrane": 2, "punkty_srednie": 9.5}})
        self.assertEqual(got["oceny"]["s_sym"], rec["oceny"]["s_sym"])
        self.assertIn("przezycie", loop.read_json(loop.record_path(self.base, 1, "1.1"))["oceny"]["sym"]["h2"])


if __name__ == "__main__":
    unittest.main()


class FiltrStrumieniaTest(unittest.TestCase):
    """CLAUDE_CODE_RETRY_WATCHDOG ponawia także 429 z limitu subskrypcji: sesja nie kończy się wynikiem, tylko wisi do `timeout`."""

    def odpal(self, zdarzenia):
        sf_spec = importlib.util.spec_from_file_location("stream_filter", os.path.join(ROOT, ".github", "loop", "stream_filter.py"))
        sf = importlib.util.module_from_spec(sf_spec)
        sf_spec.loader.exec_module(sf)
        ubito = []
        sf.zakoncz_sesje = lambda: ubito.append(True)
        stdin = sys.stdin
        sys.stdin = io.StringIO("".join(json.dumps(z) + "\n" for z in zdarzenia))
        try:
            with tempfile.TemporaryDirectory() as out:
                with contextlib.redirect_stdout(io.StringIO()):
                    sf.main(out)
                plik = os.path.join(out, "claude-execution-output.json")
                return ubito, plik if os.path.exists(plik) else None, (open(plik, encoding="utf-8").read() if os.path.exists(plik) else None)
        finally:
            sys.stdin = stdin

    def test_odrzucony_limit_konczy_sesje_z_terminem_resetu(self):
        t = loop.now()
        reset = int((t + timedelta(hours=30)).timestamp())
        info = {"status": "rejected", "resetsAt": reset, "rateLimitType": "seven_day", "isUsingOverage": False}
        ubito, plik, tresc = self.odpal([{"type": "rate_limit_event", "rate_limit_info": info}])
        self.assertEqual(ubito, [True])
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            fh.write(tresc)
        try:
            self.assertAlmostEqual(loop.limit_s(fh.name, "143", t), 30 * 3600, delta=2)
        finally:
            os.unlink(fh.name)

    def test_ostrzezenie_o_limicie_nie_przerywa_sesji(self):
        info = {"status": "allowed_warning", "resetsAt": 1791313200, "rateLimitType": "seven_day"}
        ubito, plik, _ = self.odpal([{"type": "rate_limit_event", "rate_limit_info": info}])
        self.assertEqual(ubito, [])
        self.assertIsNone(plik)
