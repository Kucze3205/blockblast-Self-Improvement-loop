# Konfiguracja pętli — sekrety, zmienne, uprawnienia

Kontrakt nazw między workflowami a sesjami. Workflow, który odwołuje się do nazwy
spoza tej listy, jest błędem — nie okazją do dopisania nowej nazwy bez decyzji.

Sekcje o pozostałych workflowach powstaną razem z nimi.

---

## Sekrety

| Nazwa | Przeznaczenie |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Uwierzytelnia sesje Claude Code subskrypcją właściciela. Powstaje z `claude setup-token`, ważny rok. |
| `ASSETS_READ_TOKEN` | Odczyt wydania z APK z prywatnego repo zasobów (`gh release download`). Wygasa ok. 2026-10-21. |
| `DEALS_SALT` | Sól rozdań oceny symulatorem (`ocena.py`): rozdania drzewa to `random.Random("<sól>:<drzewo>")`. Widzi ją tylko krok `sym` w `ocena.yml`; proces zabiera ją ze środowiska, zanim zaimportuje kod węzła. Brak soli to błąd, nie wartość domyślna (repo jest publiczne). Ustawienie: `gh secret set DEALS_SALT --body "$(python -c 'import secrets;print(secrets.token_hex(16))')"`. Zmiana soli zmienia hash i unieważnia `s_sym` wszystkich węzłów. |

Do samowyzwalania pętli **nie ma sekretu** — wystarcza wbudowany `GITHUB_TOKEN`
w parze z `workflow_dispatch`. Żadnego PAT-a, żadnego klucza GitHub App.

Wygaśnięcie obu tokenów to notatka dla właściciela — pętla dat nie czyta.

### `ANTHROPIC_API_KEY` — zakaz

Ta nazwa **nie może istnieć** ani jako sekret, ani jako zmienna, ani w `env:`
żadnego joba. Ma udokumentowane pierwszeństwo nad tokenem subskrypcji i cicho
przekieruje rachunek na płatne API. Cisza jest tu najgorsza — nic się nie zepsuje,
tylko przyjdzie faktura.

---

## Ewaluator (`ocena.yml`, `seria.yml`, `.github/evaluator/`)

Ocena węzła: `gh workflow run ocena.yml -f wezel=<sha> -f drzewo=<t> -f id=<nazwa>`.
Przebieg: 40 shardów symulatora (1200 rozdań, cap 500, limit shardu 10 min; 40 to limit jobów naraz, w shardzie gry idą na wszystkich rdzeniach jobu, wynik gry zależy tylko od jej rozdania) → przy 0 przegranych seria 80 partii po 125 tys. punktów (razem 10 mln; dwie tury po 40 jobów, partia mieści się w jobie) na
emulatorze (`seria.yml`; serie paczki idą równolegle, nadmiar partii czeka w kolejce jobów GitHuba, bez `concurrency`, bo ta anuluje oczekujące uruchomienia) → artefakt `ocena-<id>` z `ocena.json`.
Pierwszy krok pętli, `AUTOPILOT`, sprawdza `ocena.yml`; `seria.yml` wywołana z niego już go nie sprawdza.

| Co | Zasada |
|---|---|
| `s_sym` | przeżycie/cap średnio po rozdaniach, punkty tylko rozstrzygają remis (waga `tie` ≪ 1/cap), nie więcej niż 1 |
| `s_v` | `1 + s_emu` przy pełnej serii, inaczej `s_sym`; liczy `ocena.s_v()`, nie jest zapisywane |
| próg serii | 0 przegranych w symulatorze i ocena nie „za wolna" (shard przekroczył `limit_shardu_s`) |
| partia serii | `pomiar.json` z mostu: `koniec` = `cel` \| `przegrana` \| `przerwanie` \| `awaria`; ważne tylko dwie pierwsze |
| powtórka | brakujące numery partii (`partie`); ważne partie z wcześniejszych przebiegów `ocena.yml` bierze z `oceny.emu` rekordu węzła (`ocena.py zlicz --poprzednia`); do pełnej serii ważnych status to `w_toku` |
| bramka celu | `ocena.py bramka ocena.json`: 10 ważnych partii, wszystkie `cel`; kod 0 = cel osiągnięty ; `ocena.yml` zakłada wtedy `trees/cel.json` — znacznik końca pętli, który ma sprawdzać harmonogram drzewa |
| hash | `sym` (symulator, generator, punktacja, `ocena.py`, parametry, rozdania drzewa) i `most` (most, `seria.yml`, liczba partii i cel); naprawa mostu nie przelicza `s_sym` |
| tylko do odczytu | pliki z `tylko_do_odczytu` w `config.json`: ewaluator nakłada je z gałęzi domyślnej na kopię węzła |
| rekord węzła | `ocena.yml` dopisuje do `oceny` (`s_sym` per hash, `sym` z przeżyciem per rozdanie, `emu` z wynikami partii i unieważnionymi, `hash_most`; `czas_sym_min` raz, z pierwszej oceny; `s_emu` i `czas_serii_min` dopiero przy pełnej serii) i ustawia `stan`: `oceniony` albo `ocena w toku`; `oczekiwanie_min` zostaje po stronie wywołującego |
| polityka węzła | `policies.build(weights)`; wagi z katalogu `weights/` węzła (`.gitignore` przepuszcza tam `*.pth`) |

---

## Faza 0 i utrzymanie ewaluatora (`faza0.yml`, `utrzymanie.yml`, `.github/evaluator/kalibracja.py`)

Symulator ma zgadzać się z oryginałem, a most z ekranem. Miary liczy `kalibracja.py` z `moves.jsonl` mostu
(stan, tacka, ruch, licznik apki przed ruchem), tolerancje w `config.json` (`kalibracja`):

| Miara | Zasada |
|---|---|
| tempo punktów | te same ruchy zagrane w symulatorze dają sumę punktów w ±15% od przyrostu licznika apki; odczyty licznika spoza `0..max_delta` odrzucane, ruch i tak zagrany (combo) |
| rozkład klocków | tylko odczyt mostu: nieznany kształt w tacce (nowa runda = trzy pełne sloty) ≤ 2%. χ² tacek vs generator symulatora jest w raporcie informacyjnie: gra losuje klocki zależnie od rundy, więc stały generator nie przejdzie go na żadnej świeżej serii (p≈0) |
| brak danych | za mało par (`min_pary`) albo klocków (`min_klockow`) to **nie zgoda**: wyzwalacz i bramka traktują to jak rozjazd (zepsuty OCR nie może przejść niezauważony); wyjątek: miary krótkiego odcinka w bramce |

**Faza 0** (`gh workflow run faza0.yml`, ręcznie raz): `seria.yml` z polityką gałęzi domyślnej (bazowy agent), potem
`kalibracja.py rozjazd`. Bez rozjazdu zakłada `trees/faza0.json` (pierwsze drzewo czeka na ten plik). Z rozjazdem albo
unieważnioną partią otwiera utrzymanie (`powod=faza0`); po przyjętej naprawie faza 0 startuje od nowa i dopiero świeża seria
bez rozjazdu ją zamyka. Logi serii zostają jako zestaw kontrolny `faza0`. `drzewo.yml` nie robi nic, dopóki `trees/faza0.json` nie istnieje.

**Wyzwalacze** (mechaniczne, `kalibracja.py wyzwalacz`, po każdej serii w `ocena.yml` i `faza0.yml`):

| Zdarzenie | Skutek |
|---|---|
| partia unieważniona, ale z dowodem awarii infrastruktury (brak `pomiar.json`, `adb`, `device`, `emulator`, `INSTALL`) | ponowienie tych partii bez agenta, do `ponowienia` (3) prób; potem utrzymanie `most` |
| partia unieważniona bez takiego dowodu (np. gra nie na pierwszym planie, limit czasu) | utrzymanie `most` |
| miara rozjazdu poza tolerancją (przy czystej serii) | logi serii wchodzą do zestawu kontrolnego, utrzymanie `rozjazd` |

Serie nie zostawiające żadnej partii liczą się jak awaria infrastruktury. Sondy kontrolnej symulatora „co k-ty raz” nie ma.

**Zestaw kontrolny:** `.github/evaluator/kalibracja/zestaw/*.jsonl.gz` (pierwsze 300 ruchów każdej partii, zwarty zapis):
logi fazy 0 i serii, które wykazały rozjazd. Czyste serie nie wchodzą do zestawu (rósłby bez końca bez nowej informacji).

**`utrzymanie.yml`** (`-f powod=<faza0|most|rozjazd> -f id=<seria> -f run=<przebieg z artefaktami>`):

| Krok | Co |
|---|---|
| warunek | gdy istnieje `trees/utrzymanie.json` (naprawa trwa albo czeka na właściciela), wyzwalacz nic nie robi |
| wstrzymanie | `trees/utrzymanie.json` `{"stan":"naprawa"}`: `ocena.yml` czeka ze swoją serią (do ok. 5,5 h, potem węzeł zostaje `ocena w toku`); symulator i węzły działają dalej |
| katalog agenta | kod projektu i ewaluatora bez `.github/{workflows,loop,policy}`, dokumentów, rekordów, `.claude` i historii gita; własne repo bez remote'a; `.zadanie/` (zadanie, dane serii, `sprawdz.sh`); APK w `assets/` |
| iteracja | sesja agenta (skill `utrzymanie`, Sonnet, `--max-turns 120`, 60 min; limit subskrypcji = czekanie do resetu (do 2 h, najwyżej dwa razy), iteracja się nie liczy; dalszy limit = status `limit`: naprawa kończy się bez oceny, znacznik zostaje, a zgłoszenie podaje termin resetu i polecenie ponowienia) → sprawdzenie; do `iteracje` (3) iteracji w jednym jobie, emulator uruchomiony raz |
| sprawdzenie | testy `tests.test_engine` i `tests.test_bridge` z kodem naprawy; `tools/bridge.sh` z `MOVES=150`; `kalibracja.py bramka`: zestaw kontrolny w tolerancji (twardo, brak danych = porażka) i odcinek: koniec `przegrana` albo `przerwanie` z powodem `limit ruchów` (awaria lub inne przerwanie = porażka), miary odcinka tylko gdy ma dość danych (krótka przegrana ich zwykle nie ma) |
| ścieżki | agent zmienia tylko pliki z `kalibracja.py sciezki` (`tylko_do_odczytu` + `utrzymanie.dodatkowe`: testy silnika i mostu); każda inna zmiana unieważnia iterację, a łatka ich nie zawiera. Bramka i `config.json` są poza zasięgiem: działają z kopii `ZAUFANE` |
| poświadczenie | `CLAUDE_CODE_OAUTH_TOKEN` ma tylko proces claude; kod naprawy uruchamiany przez sprawdzenie (most) go nie widzi |
| przyjęcie | łatka na gałąź `evaluator/<n>`; po przejściu bramki szybkie przesunięcie gałęzi domyślnej (bez PR), usunięcie znacznika i (dla `faza0`) nowa faza 0 |
| po 3 nieudanych | znacznik `{"stan":"wstrzymane"}`, issue dla właściciela (miary, iteracje, gałąź), tylko serie na emulatorze stoją |
| hash | po przyjęciu zmienia się właściwa część hasha (pliki `sym` albo `most`), bo hash liczy się z plików gałęzi domyślnej; podsumowanie przebiegu pokazuje przed/po. Zmiana `sym` przelicza `s_sym` leniwie |

Po `wstrzymane` właściciel naprawia ewaluator ręcznie na gałęzi domyślnej, usuwa `trees/utrzymanie.json` i ocenia ponownie
węzły ze stanem `ocena w toku` (`ocena.yml` z tym samym węzłem; ważne partie zostają w rekordzie).

---

## Zmienne repo

| Nazwa | Wartość | Przeznaczenie |
|---|---|---|
| `AUTOPILOT` | `on` \| cokolwiek innego | Przełącznik właściciela. Pierwszy krok **każdego** workflow pętli. |

Warunek jest jawnie fail-safe: pętla rusza **wyłącznie** przy dosłownym `on`.
Brak zmiennej, literówka, pusta wartość — wszystko to znaczy „stój".

```yaml
if: vars.AUTOPILOT == 'on'
```

**Czego `AUTOPILOT` nie potrafi:** pętla nie może go przestawić sama. Klucz
`permissions` nie zna zakresu pozwalającego zapisać zmienną repo. To
przełącznik człowieka, nie bezpiecznik. Stan awaryjny, który pętla ustawia sobie
sama, musi leżeć w pliku w repo albo w przypiętym issue.

---

## Uprawnienia

Domyślne uprawnienia workflow w repo są na minimum i mają takie zostać:

| Ustawienie | Wartość |
|---|---|
| `default_workflow_permissions` | `read` |
| `can_approve_pull_request_reviews` | `false` |

Druga pozycja to w UI checkbox **„Allow GitHub Actions to create and approve pull
requests"**. Nazwa mówi o zatwierdzaniu, ale jedna opcja gasi **dwie** rzeczy:
`GITHUB_TOKEN` nie może PR-a zatwierdzić **ani go otworzyć**. Pętla nie otwiera
PR-ów, więc checkbox zostaje wyłączony na stałe.

Skoro domyślne to `read`, **każdy workflow musi jawnie zadeklarować `permissions:`**
— tylko to, czego potrzebuje. `actions: write` pozwala wywołać `workflow_dispatch`
na samej pętli.

Osobno, niezależnie od `permissions:`: tryb automation Claude Code **nie nadaje
żadnych uprawnień narzędziowych**. Każdy job musi podać `--permission-mode` i pełną
listę `--allowedTools`.

---

## Ustawienia wyklikiwane ręcznie

Settings → Actions → General. Nie ma dla nich REST API, więc nie ma jak ich
sprawdzić z poziomu sesji — stan poniżej jest deklaracją właściciela, nie pomiarem.

| Ustawienie | Wymagane |
|---|---|
| Send write tokens to workflows from pull requests | **wyłączone** (repo jest publiczne) |
| Require approval for all external contributors | **włączone** (przebiegi z forków) |

Sekrety repo — w tym `CLAUDE_CODE_OAUTH_TOKEN` — i tak **nie są** przekazywane do
przebiegów z forkowych PR-ów.

---

## Gałąź pętli

**Gałąź pętli to gałąź domyślna repozytorium. Dziś `main`.** Nie są to dwa
pojęcia, które trzeba trzymać w zgodzie — to jedno pojęcie. Wymuszają to dwa
udokumentowane ograniczenia GitHuba, z których żadne nie ma obejścia:

| Ograniczenie | Skutek |
|---|---|
| *„Workflow runs cannot restore caches created for child branches or sibling branches"* — run czyta cache z własnej gałęzi **albo z domyślnej** | Cache nie przechodzi między gałęziami siostrzanymi; wspólne rzeczy (np. obraz emulatora) muszą leżeć w cache'u gałęzi domyślnej |
| Workflow na zdarzeniu `issues` odpala się **wyłącznie z pliku na gałęzi domyślnej**; `workflow_dispatch` jest na liście widoczny dopiero stamtąd | Workflowy muszą leżeć na gałęzi domyślnej |

Klucze cache muszą być nowe przy każdym zapisie (`<nazwa>-${{ github.run_id }}`)
i odczytywane przez `restore-keys`, bo wpis o danym kluczu jest niemutowalny.

### Nazwa nie jest wpisywana na sztywno

Workflow ustala gałąź pętli przez `github.event.repository.default_branch`,
nigdy przez literał `main`.

Powód jest jeden i wystarczający: **pętla nie może edytować `.github/workflows/`**
(akcja twardo tego zabrania). Nazwa wpisana na sztywno byłaby jedyną rzeczą, której
pętla nie umie naprawić, umieszczoną w jedynym miejscu, którego nie umie tknąć.

---

## Drzewo na żywo — `drzewo.yml`, `.github/policy/`, `.github/loop/drzewo.py`

```bash
gh variable set AUTOPILOT --body on
gh workflow run drzewo.yml        # start: bieżące otwarte drzewo albo następne po zamkniętym
```

Harmonogram jest zdarzeniowy: krótki job `krok` (grupa `polityka`, kroki idą po kolei) czyta `trees/`,
a dalej robi jedno z trzech: czeka (ostatnia paczka ma nieocenione węzły), otwiera następną paczkę
(commit `trees/<t>.json`, potem `wezel.yml` dla każdego jej węzła) albo zamyka drzewo. Wywołuje go
koniec oceny każdego węzła (`ocena.yml`, a dla węzła bez zmian `wezel.yml`). Krok bez zmian w drzewie
niczego nie robi, więc powtórzone wywołania są nieszkodliwe. Drzewa startują od tagu `korzen`.

| Plik | Co to |
|---|---|
| `.github/policy/config.json` | Konfiguracja właściciela, jedyne miejsce: `W` (paczka ≤ W węzłów naraz), `K` (rund na drzewo, wspólne dla drzewa na żywo i odtwarzania), `beta` (na godzinę), `M` (wersji w fazie offline). Zmiana `beta` zmienia definicję V; korekta `W`/`K` to commit właściciela, od następnego drzewa. |
| `.github/policy/policy.py` | Polityka: `solve(question)` zwraca paczkę. Pisze ją wyłącznie job wdrożenia, nigdy sesja LLM. Polityka startowa: pełne `W` łańcuchów od korzenia, potem kontynuacja każdego, aż `K` rund albo 2 kolejne węzły bez poprawy względem rodzica. |
| `trees/<t>.json` | Stan drzewa: `polityka` (skrót treści, przypięty na całe drzewo; zmiana w trakcie to błąd), `paczki` (nazwy węzłów w kolejności rund; kolejność utworzenia = pozycja po spłaszczeniu, od 1), `koniec` (`null` albo `powod`, `T_h`, `V`). |
| `trees/baseline.json` | Opcjonalny `{"s_v": x}` zapisywany ręcznie: punkt odniesienia dla węzłów od korzenia. Faza 0 go nie pisze (`s_sym` zależy od rozdań drzewa, a przed kalibracją niczego nie znaczy). Bez pliku baseline to 0. |

**Widok polityki (`question`).** `max_parallelism` (W), `max_rounds` (K), `round` (ukończone rundy),
`baseline_score`, `observed()` (ocenione węzły: `wezel`, `lancuch`, `glebokosc`, `rodzic`, `s_v`,
`delta` względem rodzica), `legal_actions()` (`None` = nowy łańcuch od korzenia; czubki łańcuchów).
Akcja `None` otwiera łańcuch od korzenia, nazwa czubka kontynuuje jego łańcuch. Maszyneria odrzuca
akcje niedozwolone, liść bierze najwyżej raz i obcina paczkę do `W`. Pusta paczka kończy drzewo.
Odtwarzanie nagranego drzewa używa tych samych `Pytanie`, `paczka`, `nazwij`, `czas_h` i `wartosc`
z `drzewo.py`; różni się tylko tym, że ujawnia zapisane rekordy zamiast uruchamiać węzły.

**Czas.** Koszt węzła w godzinach = `koszt.minuty` (sesja) + `oceny.czas_sym_min` + `oceny.czas_serii_min`;
`oczekiwanie_min` poza kosztem. Węzeł dziedziczony (kod bez zmian względem rodzica, nie korzenia) płaci
tylko za sesję. Paczka kosztuje najdłuższy z jej węzłów, `T` to suma po paczkach, `V = max s_v − beta·T`.
Seria jest jedna na paczkę z natury: partie idą równolegle, a paczka płaci za najdłuższy węzeł.

**Zamknięcie.** Powód: `pusta paczka`, `K` albo `cel` (obecność `trees/cel.json`). Po `pusta paczka`
i `K` krok dispatchuje `offline.yml -f drzewo=<t>`; ten workflow musi używać grupy `polityka`
(następne drzewo czeka, aż skończy) i na końcu wywołać `drzewo.yml` bez argumentu, co otwiera
następne drzewo. Po `cel` pętla się kończy: offline się nie odpala, nowe drzewo nie powstaje,
węzły w toku dokańczają się same.

---

## Faza offline — `offline.yml`, `offline.sh`, `offline.py`, `.github/policy/meta.md`

```bash
gh workflow run offline.yml -f drzewo=<t>   # ręcznie; zwykle dispatchuje ją krok harmonogramu po zamknięciu drzewa
```

Po zamkniętym drzewie powstaje M wersji polityki (`config.json`), każdą pisze osobna, świeża sesja.
Runner liczy `V` każdej wersji, wybiera najlepszą razem z bieżącą i wdraża ją. Grupa `polityka`
trzyma następne drzewo, aż faza skończy; na końcu `drzewo.yml` bez argumentu otwiera je.
`AUTOPILOT` sprawdza tylko start jobu: przestawienie na `off` w trakcie nie przerywa fazy,
ale po niej drzewo już się nie otworzy.

| Co | Zasada |
|---|---|
| odtworzenie | `offline.odtworz`: ta sama `solve`, `Pytanie`, `paczka`, `nazwij`, `czas_h`, `wartosc` co na żywo; `question` ujawnia zapisane węzły (`oceniony`) zamiast uruchamiać sesje |
| nowy łańcuch | najwcześniej utworzony (`kolejnosc`) korzeń nagrania, jeszcze nieużyty; bez korzeni runda się nie liczy |
| węzeł spoza nagrania | łańcuch kończy się (znika z `legal_actions()`), bez kary w `T`; runda bez żadnego ujawnienia nie liczy się do `K` |
| `V` wersji | średnia z `V` po wszystkich zamkniętych drzewach (`trees/<n>.json` z `koniec`), `V = max s_v − beta·T` jak na żywo |
| dopuszczenie | odtworzenie w osobnym procesie, bez środowiska, limit 600 s, dwa przebiegi muszą dać to samo; wyjątek, brak `solve`, nie-lista, zwłoka albo losowość to `blad` i wersja nie wygrywa |
| wybór | argmax `V`; remis zostawia wcześniejszą, więc bieżącą (`V` zwycięzcy ≥ `V` bieżącej) |
| wdrożenie | `.github/policy/policy.py` tylko gdy wygrała inna niż bieżąca; zawsze archiwum fazy `.github/policy/history/faza-<t>/r####/` (`policy.py`, `wynik.json`) |
| awaria | bez commita zostaje poprzednia polityka, a pętla idzie dalej (`drzewo.yml` jest wołany zawsze, o ile sonda poświadczenia przeszła) |

**Sesja meta** (`offline.sh`, model `claude-haiku-5-5`, `--effort max`, sufit 50 min i 80 tur na wersję, jedno
czekanie na reset limitu subskrypcji do 4 h). Prompt to `.github/policy/meta.md` skopiowany jako `ZADANIE.md`. Dysk
sesji to katalog `meta/` w `$RUNNER_TEMP`: `policy.py` (najlepsza dotąd wersja, jedyny plik, który się liczy),
`history/biezaca/r####/` (wersje tej fazy z `V`, `V_drzewa` i śladami odtworzenia), `history/faza-*/`
(wersje wcześniejszych faz, bez śladów), `drzewa/<t>/manifest.json` (struktura, `s_v`, `kolejnosc`, `koszt_h`;
bez kodu i bez notatek), `baseline.json`, `konfiguracja.json` (`W`, `K`, `beta`). Narzędzia: czytanie i edycja
w katalogu sesji; `Bash`, internet i subagenci wyłączone. W środowisku sesji nie ma tokenu GitHuba (krok
sesji dostaje tylko `CLAUDE_CODE_OAUTH_TOKEN`, a Claude Code zdejmuje go z procesów potomnych). Granica to
katalog roboczy, nie osobny użytkownik: sesje meta nie mają Basha, więc nic nie wykonują poza
odczytem i edycją plików.

**Podsumowanie jobu** (`$GITHUB_STEP_SUMMARY`): wersje z `V`, `V` per drzewo, skrótem i błędem; zmiana polityki tak/nie;
zgodność odtworzenia z żywym drzewem (tam, gdzie drzewo szło tą samą polityką: `koniec.V` kontra `V` bieżącej
wersji); **postęp** drzewa (po rundzie: najlepszy `s_v`, `T`, `V`); **czasy węzłów** (sesja, oczekiwanie,
liczba sesji z podziałem na kontynuacje po turach i po limicie, tury, symulator, seria). To z niej właściciel
koryguje `W` i `K` w `config.json`. Katalog `offline/` (wersje i ślady) i transkrypty sesji są w artefakcie
`offline-<t>-<run>-<próba>`.

---

## Węzeł — `wezel.yml`

```bash
gh workflow run wezel.yml -f drzewo=<t> -f wezel=<łańcuch>.<głębokość> -f kolejnosc=<n>
```

Jedna sesja agenta odkrywczego i jej rekord. Rodzicem `2.3` jest `2.2`, rodzicem `2.1`
korzeń. Dispatch nowego węzła wymaga ocenionego rodzica. Ten sam dispatch dla węzła
z rekordem w stanie `sesja` albo `zaparkowany` jest kontynuacją (`kolejnosc` ignorowana).

| Nazwa | Co to |
|---|---|
| tag `korzen` | Commit bez rodzica: kod projektu, `CONTEXT.md`, `tools/`, reguły gry. Bez `.claude/`, `.github/`, `bench/` i dokumentów pętli. Każdy łańcuch startuje stąd. |
| gałąź `trees/<t>/<łańcuch>` | Kod łańcucha. Pisze ją wyłącznie job węzła (push bez force po sesji); czubek to zawsze liść. |
| `trees/<t>/<węzeł>.json` na gałęzi pętli | Rekord węzła (niżej). Pisze go `zapisz.sh` z ponowieniami. |
| artefakt `transkrypt-<t>-<węzeł>-<run>-<próba>` | `stream.ndjson` sesji; z niego liczy się udział historii w oknie kontekstu. |

**Budżet:** job sesji 330 min, sesja 300 min (`timeout`), `--max-turns 150`. Po każdym narzędziu
hook dopisuje agentowi „Zostało X min sesji.”.

**Co widzi agent:** checkout `work/` z jednym refem (gałąź łańcucha), bez remote'a i bez
poświadczeń (`CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`, token GitHuba tylko w krokach maszynerii);
`.historia/` (indeks, rekordy ocenionych węzłów, patche innych łańcuchów, kod najlepszego węzła ze wszystkich drzew, poprzednie drzewa bez
kodu); skill `implementer` i subagent `researcher` skopiowane do `~/.claude`. Checkout gałęzi
pętli jest usuwany przed sesją i wraca po niej.

**Po sesji** (`loop.py koniec`):

| Następny krok | Kiedy | Co robi job |
|---|---|---|
| `park` | limit subskrypcji | `stan: zaparkowany`, `wznow_po` = reset z komunikatu albo +60 min; dispatch samego siebie, job `czekaj` śpi do `wznow_po` (dłużej niż ~5,75 h → dispatch kolejnego czekania) |
| `kontynuuj` | `error_max_turns`, pierwszy raz | dispatch samego siebie; drugi raz → `ocena` |
| `dziedzicz` | SHA = rodzic (nie korzeń) | `stan: oceniony`, `oceny` skopiowane od rodzica, bez oceny |
| `ocena` | w pozostałych przypadkach | `stan: ocena w toku`; `gh workflow run ocena.yml -f wezel=<sha> -f drzewo=<t> -f id=<t>-<węzeł>` |

### Rekord węzła

| Pole | Pisze | Znaczenie |
|---|---|---|
| `rodzic`, `rodzic_sha` | węzeł | nazwa rodzica (`korzen` dla głębokości 1) i jego SHA |
| `kolejnosc` | węzeł (z dispatchu) | kolejność utworzenia w drzewie, dla replayu |
| `sha` | węzeł | czubek gałęzi łańcucha po sesji |
| `stan` | węzeł, ocena | `sesja` → `zaparkowany` ↔ `sesja` → `ocena w toku` → `oceniony` (ostatnie przejście robi ocena) |
| `gist`, `notatki` | węzeł | komunikaty commitów węzła, najnowszy pierwszy; gist = pierwsza linia najnowszego |
| `koszt` | węzeł | `tury`, `usd`, `minuty` (czas jobów sesji od startu do zapisu, suma po kontynuacjach) |
| `oczekiwanie_min` | węzeł, ocena | czas zaparkowania na limicie; ocena dopisuje ponowienia i naprawy |
| `kontynuacje_tur`, `sesje` | węzeł | licznik kontynuacji po turach; lista sesji (start, koniec, tury, przyczyna) |
| `zaparkowano`, `wznow_po` | węzeł | tylko w stanie `zaparkowany` |
| `oceny` | ocena | `s_sym` (słownik: hash ewaluatora → wynik), `s_emu`, wyniki per partia, czas serii |

Statusu „nieudany” nie ma: każdy węzeł idzie do oceny.

---

## Sonda poświadczenia

```bash
curl -s -o /dev/null -w '%{http_code}' https://api.anthropic.com/v1/models   -H "Authorization: Bearer $CLAUDE_CODE_OAUTH_TOKEN"   -H "anthropic-version: 2023-06-01" -H "anthropic-beta: oauth-2025-04-20"
# 200 żyje · 401 martwy · 403 odwołany
```

Brak odpowiedzi sieci to nie martwe poświadczenie.
