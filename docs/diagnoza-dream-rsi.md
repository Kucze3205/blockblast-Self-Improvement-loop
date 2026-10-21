# Diagnoza: dlaczego pętla dream-rsi nie osiągnęła celu

Stan na 2026-10-21, po zatrzymaniu pętli (37 drzew, 270 węzłów, 1226 commitów, 10-04 → 10-20).
Wszystkie liczby wyliczono z `trees/*.json`, `trees/*/*.json`, `.github/policy/history/`, `git log`
oraz z własnego eksperymentu na symulatorze (200 rozdań z własną solą, kod `korzen-baza`).

## TL;DR

1. **Bramka była praktycznie nieosiągalna.** Seria na emulatorze startowała dopiero przy 0 przegranych na 1200
   rozdań. Najlepszy agent przegrywa ok. 1–2% rozdań. P(0/1200) przy p = 1,5% wynosi ok. 1e-8, a przy
   najlepszym zmierzonym p = 1% ok. 6e-6. Na 50% szans potrzeba p ≈ 0,06%, czyli 17–26× mniej przegranych.
   **Żaden z 270 węzłów nie dostał `s_emu`**, więc prawdziwego celu ani razu nie zmierzono.
2. **Sygnał optymalizacji wysycił się i utonął w szumie.** `s_sym` ≈ 0,99 od drzewa 8. Rozrzut tego samego kodu
   między drzewami (12–26 przegranych, sd 3,8 przy sd Poissona 4,4) jest równy całej zmienności „poprawek”.
   Po drzewie 9 (0,9959) nic nie było lepsze od szumu, a „najlepszy węzeł” to efekt selekcji minimum
   z zaszumionego rozkładu.
3. **Wewnętrzna pętla była otwarta.** Skill `implementer` zabraniał agentowi mierzyć własną pracę, a limit czasu
   był dla niego nieczytelny. Każda sesja to jeden strzał na ślepo: mediana 20 z 300 minut budżetu, a zwrotny
   sygnał to jedna liczba po ok. 30 min (sesja + 40 shardów). W 221/270 notatek są słowa „niezmierzony”,
   „szum”, „limit nieczytelny” albo „za wolna”.
4. **Brak elitaryzmu.** Drzewa 1–36 startowały od „Stanu początkowego”, a nie od najlepszego kodu. Spora część
   węzłów (ok. 25–30%, w drzewach 24–37 16 z 28) tylko odtwarzała bazę 9/2.6 albo ponownie łatała most.
5. **Meta-pętla optymalizowała koszt, nie postęp.** `V = max s_v − β·T` przy wysyconym `s_v` premiuje
   zatrzymanie. Polityka nauczyła się `CEILING = 0.98 → return []`, a 0,98 było już poniżej poziomu korzeni.
   Drzewa 19–37 to po 2 węzły i koniec. Replay offline nie widzi węzłów spoza nagrania, więc drzewa
   z polityki „stop” nie niosą żadnej informacji o głębszych łańcuchach. 176 z 210 sesji meta zostawiło
   kod bez zmian (84%).
6. **Koszt był wysoki, bo każda warstwa jest droga, a sygnał prawie zerowy.** Szczegóły są w sekcji
   „Koszt” niżej. Po drzewie 9 wydano ok. 2/3 kosztu sesji bez żadnego mierzalnego zysku.

Werdykt: zawiodła nie sama idea „drzewa prób + meta-optymalizacji polityki przeszukiwania”, tylko jej
zastosowanie do problemu bez użytecznego sygnału. Przy tym celu i tej metryce żaden algorytm
przeszukiwania nie miał z czego się uczyć. Do tego typu zadania (wąska, dobrze zdefiniowana optymalizacja
algorytmiczna z tanim symulatorem) warstwa meta-RSI to w obecnej formie nadmiarowa maszyneria. Szczegóły
i propozycje są niżej.

---

## 1. Przebieg w liczbach

| Okres | Drzew | Węzłów | Mediana sesji | Mediana USD/węzeł | Suma USD | Najlepszy `s_sym` |
|---|---|---|---|---|---|---|
| T1–4 | 4 | 75 | 2,6 min / 16 tur | 0,23 | 20 | 0,987 |
| T5–7 | 3 | 54 | 14 min / 45 tur | 2,88 | 194 | 0,985 |
| T8–18 | 11 | 103 | 18 min / 54 tury | 3,57 | 401 | **0,9959 (9/2.6)** |
| T19–37 | 19 | 38 | 20 min / 63 tury | 3,84 | 164 | 0,9955 |

- Realny postęp trwał do drzewa 9 (0,885 → 0,9959). Później żadne drzewo nie pobiło 9/2.6.
- Od T19 każde drzewo to 1 runda, 2 korzenie i `pusta paczka`.
- W T37 oba węzły nie zmieniły kodu (sha = korzeń) i dostały 0,9918 (23 przegrane). Sama baza ląduje więc
  w tym samym przedziale, co wszystkie „poprawki” z T10–36.

## 2. Bramka celu a jakość agenta

**Mechanika:** `ocena.yml` puszcza serię na emulatorze tylko przy 0 przegranych w 1200 rozdaniach po 500 ruchów.
Bez serii `s_v = s_sym < 1`. Prawdziwy cel (`1 + s_emu`, 80 partii × 125 tys.) leży za tym progiem.

**Statystyka:** P(pass) = (1 − p)^1200.

| p (przegrane/rozdanie) | P(0/1200) |
|---|---|
| 1,5% (typowo) | ~1e-8 |
| 1,0% (najlepszy pomiar, 12/1200) | ~6e-6 |
| 0,058% | 50% |
| 0,0088% | 90% |

**Czy to w ogóle możliwe?** Eksperyment (200 własnych rozdań, generator z `main`):

- Agent bazowy przegrał 5/200 (2,5%), `s_sym` ≈ 0,9905, czyli zgodnie z rekordami.
- Gracz jasnowidzący (zna 2 następne tacki, przeszukuje wyczerpująco) przeżył wszystkie 5 przegranych rozdań
  od pustej planszy. Rozdania nie są więc nie do wygrania.
- W drzewie 9 dziesięć węzłów przegrało łącznie 135 różnych rozdań, ale **żadnego rozdania nie przegrały
  wszystkie**. Przegrane to błędy algorytmu i pech, a nie stały zbiór wymuszonych przegranych.
- Na planszy przed fatalną tacką dokładne P(fatalnej tacki) przy wybranym ruchu wynosiło 9e-5, 1,5e-3 i 7e-4,
  a najlepsza z próbkowanych alternatyw dawała 0, 8,7e-4 i 1,1e-5. Dokładna minimalizacja ryzyka mogłaby więc
  obniżyć hazard o 1–2 rzędy wielkości w części stanów.

Wniosek: cel nie jest teoretycznie niemożliwy, ale wymaga hazardu ~3,5e-6 na tackę wobec obecnego ~1e-4,
czyli ok. 30× lepszej kontroli ryzyka. Rodzina „beam + heurystyka + próbki ryzyka”, w której przeszukiwanie
spędziło ~75% węzłów, nie jest drogą do tego poziomu. Pętla nie miała też jak tego zauważyć, bo `s_sym` tego
nie mierzy (pkt 3).

Uwaga poboczna: generator symulatora jest i.i.d. i nie patrzy na planszę. Notatki badawcze sugerują, że
prawdziwa gra gwarantuje grywalność tacki (R14, niezweryfikowane). Symulator może więc być **surowszy**
niż aplikacja, a bramka w symulatorze trudniejsza niż cel w aplikacji.

## 3. Metryka: wysycona, zaszumiona, nieporównywalna między drzewami

- `s_sym` to średnia przeżycia/cap. Przy ~1,5% przegranych to ~0,99 i cała informacja siedzi w 12–25 zdarzeniach
  na 1200 rozdań. Różnica 12 vs 25 przegranych to ok. 0,993 vs 0,987, czyli mniej więcej 2 sd szumu.
- Rozdania zależą od drzewa (`sól:drzewo`), więc porównania między drzewami są niesparowane. W T23–37
  (prawie ten sam kod) przegranych było 19,7 ± 3,8 przy zakresie 12–26. Kod bez zmian dostawał od 12 do 24
  przegranych.
- `najlepszy.patch` w `.historia/` wybierano jako max po drzewach, co jest klasyczną klątwą zwycięzcy.
  Agenci kopiowali „najlepszy” kod, który był po prostu najszczęśliwszym losowaniem (24/1.1, sama baza, 12 przegranych).
- Agenci sami to widzieli (30/2.1: „szum rzędu ±0,003, nic nie dowodzi poprawy”), ale nie mieli narzędzia,
  żeby to rozstrzygnąć.
- Limit czasu shardu (600 s) przy ~8 min/shard zostawiał mało zapasu, więc szersze przeszukiwanie od razu
  wpadało w `za wolna`. To przesuwało przeszukiwanie w stronę tanich poprawek heurystyki zamiast mocniejszego
  przeszukiwania, które było potrzebne (pkt 2).

## 4. Wewnętrzna pętla (sesja agenta)

- **Zakaz pomiaru** (`implementer/SKILL.md`: „Nie mierz wyniku…”) przy nieczytelnym `config.json` (notatki:
  „limit nieczytelny”, „.github to /dev/null”) robił z każdej sesji pojedynczą propozycję bez sprzężenia
  zwrotnego. W praktyce to losowe przeszukiwanie z priorytetem modelu językowego, a jedna ocena kosztuje
  ~30 min ściany i ~5 runner-godzin.
- Sesje kończyły się szybko (mediana 20 z 300 min, 63 ze 150 tur), bo nie było nic do iterowania. Duży budżet
  sesji był niewykorzystany, a koszt przeniósł się na ewaluację i oczekiwanie.
- Klastry pomysłów (ok.): ryzyko tacki ~60 węzłów, lookahead/CRN ~45, cechy liścia ~35, szerokość beamu ~30.
  Strukturalnie nowe podejścia (TD/sieci wartości, regresja, rollouty) to ~10% węzłów, wszystkie słabsze.
  Te same idee wracały wielokrotnie, np. „trudne trójki ważone multizbiorem” w ~8 drzewach, beam 120 w 6.
- ~12 węzłów w drzewach 26–35 naprawiało most (indeks puli, KeyError, TypeError), czyli pracę spoza
  zadania. Kilka węzłów z T10–18 to wyjątki lub wynik 0.

## 5. Brak akumulacji (elitaryzmu)

Do drzewa 36 każdy łańcuch startował od `korzen` = „Stan początkowy” (`c333f75` przestawił korzeń na
`korzen-baza` dopiero 10-16). Każde drzewo zaczynało od odtworzenia bazy z `najlepszy.patch`, co zjadało
pierwszą rundę, a przy polityce „2 korzenie i stop” zjadało **całe drzewo**. Od T19 drzewa były w praktyce
„dwa razy skopiuj bazę i zmierz ją na nowych rozdaniach”.

## 6. Zewnętrzna pętla (polityka drzewa i faza offline)

- **Cel źle postawiony:** przy β = 0,01/h runda za ~0,5 h kosztuje 0,005, a zapas do 1,0 to ~0,005–0,01, do tego
  zaszumiony. Racjonalna polityka pod tym `V` to „zatrzymaj się, gdy tylko masz ~0,98”. Dokładnie to się
  stało: `CEILING = 0.98` (faza 11), a od T19 drzewa kończą się po pierwszej rundzie.
- **`V` nie nagradza celu:** wartość `1 + s_emu` nigdy nie pojawiła się w danych. Meta-optymalizacja nie miała
  więc żadnego sygnału, że głębsze przeszukiwanie prowadzi do celu.
- **Stronniczość replayu (off-policy):** węzeł spoza nagrania kończy łańcuch bez kosztu. Na drzewach nagranych
  polityką „stop” każda polityka otwierająca te same 2 korzenie ma identyczne `V`, a jedyna droga do lepszego
  `V` to otwierać mniej. Udział takich drzew rósł z każdą fazą (19 z 37). To samowzmacniający się punkt stały.
- **Brak presji selekcyjnej:** polityka zmieniła się tylko w 8 fazach (2, 4, 6, 7, 8, 11, 12, 21). W fazie 21
  zysk wyniósł +0,0002. W fazach 22–37 wszystkie 6 kandydatów miało `V_drzewa` identyczne z bieżącą wersją,
  a 176/210 sesji meta zostawiło plik bez zmian.
- **Za mało danych:** 37 drzew po kilka rund to za mało, żeby uczyć politykę przeszukiwania, zwłaszcza gdy
  wartości węzłów różnią się o szum.

## 7. Koszt — skąd się wziął

| Pozycja | Wielkość |
|---|---|
| Sesje węzłów | 270 sesji, 12 661 tur, 93 h, ~779 USD ekwiwalentu (subskrypcja) |
| Oczekiwanie na limit subskrypcji | ~136 h (sam węzeł 37/2.1: 102 h) |
| Ewaluacja w symulatorze | 47,7 h ściany × 40 shardów ≈ **1900 runner-godzin** GitHub Actions |
| Faza offline | 210 sesji meta, ~40 h ściany (≈ 1/3 czasu żywych drzew), 84% bez zmian |
| Infrastruktura | ~5–6 pierwszych dni na ewaluator, most, emulator, kalibrację i auto-naprawy (~50 cykli utrzymania, ~25 PR-ów); potem dzień przeróbki (#48, reset/przeliczenie T1–4) |
| Wynik po T9 | ~2/3 kosztu sesji (T10–37, ~560 USD) i ~3/4 runner-godzin bez mierzalnej poprawy |

Mechanizm kosztu: każdy węzeł płaci pełną, ciężką ewaluację (1200 × 500 ruchów na 40 jobach), żeby kupić
jeden pomiar o rozdzielczości mniejszej niż szum. Do tego dochodzą trzy warstwy (sesja → ocena → meta) i
limit subskrypcji, który przy równoległych sesjach zamienia się w godziny czekania. Koszt na bit informacji
był bardzo wysoki, a liczba bitów prawie zerowa.

## 8. Czy dream-rsi nadaje się do tego zadania?

**Gdzie ta architektura ma sens:** szeroka, otwarta przestrzeń rozwiązań, w której różne kierunki dają
różne, mierzalne zyski. Metryka musi być tania, gładka i mało zaszumiona względem typowej poprawki, a horyzont
musi być na tyle długi, żeby meta-polityka zebrała dziesiątki do setek porównywalnych drzew.

**Tutaj żaden z tych warunków nie był spełniony:**

- Problem jest wąski i dobrze opisany: przetrwanie w grze z **znanym** i.i.d. generatorem. Klasyczne narzędzia,
  czyli expectimax lub dokładna minimalizacja P(fatalnej tacki) na bitboardach z dokładnym liczeniem
  multizbiorów tacek, są bezpośrednią drogą. Przeszukiwanie w przestrzeni „sesji LLM” jest tu dużo droższe
  od zwykłej pracy inżynierskiej z szybkim, lokalnym pomiarem.
- Metryka była binarna w praktyce (bramka 0/1200) albo wysycona (`s_sym`).
- Meta-warstwa dołożyła koszt i sama zbiegła do degeneracji, bo uczyła się na szumie.

Werdykt: **w obecnej formie algorytm nie nadaje się do tego zadania**. Problemem nie jest „drzewo prób”
jako takie, tylko (a) cel i metryka, (b) otwarta pętla wewnątrz sesji, (c) meta-optymalizacja odpalona,
zanim baza miała sygnał. Po naprawie (a) i (b) większość pracy zrobiłaby pojedyncza, długa sesja albo
prosty hill-climbing z elitaryzmem. Meta-warstwa (c) jest wtedy zbędna albo do odłożenia.

## 9. Co zmienić, jeśli architektura ma zostać

Kolejność według wpływu:

1. **Metryka i bramka**
   - Mierzyć hazard: przegrane na tackę lub log-tempo przegranych z przedziałem ufności, zamiast
     średniego przeżycia.
   - **Sparowane** porównanie kandydata z rodzicem na tych samych rozdaniach: stały zbiór bench + świeży holdout.
   - Bank „trudnych stanów”: plansze sprzed przegranych z rekordów. To importance sampling, który daje dużo
     więcej sygnału na rozdanie niż 500 ruchów od pustej planszy.
   - Bramkę 0/1200 zastąpić testem sekwencyjnym (SPRT) „p < próg” albo bramką na oszacowanie p.
     Emulator uruchamiać, gdy górna granica p daje rozsądną szansę na serię.
2. **Zamknąć wewnętrzną pętlę.** Agent dostaje szybki lokalny pomiar (np. 200 sparowanych rozdań + bank
   trudnych stanów w kilka minut) i czytelny limit czasu. Ocena zewnętrzna zostaje na holdoucie, żeby nie
   przeuczyć. Jedna sesja może wtedy iterować dziesiątki razy w budżecie, który i tak jest niewykorzystany.
3. **Elitaryzm:** korzeń = najlepszy kod potwierdzony sparowanym testem, a nie max po zaszumionych drzewach.
   `najlepszy.patch` liczyć z istotnością, a nie z maksimum.
4. **Tańsza ewaluacja:** screening na małej próbie, pełna ocena tylko dla kandydatów istotnie lepszych.
   Wczesne przerwanie, gdy przegranych już jest więcej niż u rodzica. Więcej zapasu na limit shardu.
5. **Meta-warstwa** dopiero, gdy wewnętrzna pętla pokazuje postęp. Przy tym:
   - `V` z wartością dojścia do celu (np. nagroda za przejście bramki).
   - β względem realnych kosztów.
   - Kara lub nieznana wartość zamiast darmowego „poza nagraniem” w replayu (albo ocena tylko na drzewach
     nagranych tą samą lub bardziej eksploracyjną polityką).
   - Minimum eksploracji (np. zawsze ≥ 1 kontynuacja), żeby dane o głębokich łańcuchach nie wymierały.
6. **Kierunek merytoryczny dla agenta** (z eksperymentu): dokładna minimalizacja P(fatalnej tacki) i
   lookahead przy znanym rozkładzie generatora zamiast kolejnych wag heurystyki liścia. Do tego budżet czasu
   na ruch, który pozwala na mocniejsze przeszukiwanie (szybszy kod lub większy limit).
7. **Kalibracja symulatora do aplikacji:** sprawdzić hipotezę, że prawdziwy generator gwarantuje grywalność
   (R14). Jeśli tak, bramka w symulatorze jest surowsza niż cel i może blokować coś, co w aplikacji już działa.

## 10. Rekomendacja praktyczna

Zamiast restartu dream-rsi:

1. Zbudować sparowany bench hazardu (stałe rozdania + bank trudnych stanów, wynik z CI) jako lokalne
   narzędzie w repo.
2. Jedna lub kilka długich sesji (albo ręczna praca) nad dokładną minimalizacją ryzyka, z pomiarem na benchu
   po każdej zmianie.
3. Bramkę emulatora przestawić na test „p < próg” i po pierwszym kandydacie z p ≲ 0,1% puścić krótką serię na
   emulatorze. Ta seria sprawdzi też, czy aplikacja jest łagodniejsza od symulatora.
4. Dopiero gdy to zadziała i pojawi się realna przestrzeń wielu konkurencyjnych kierunków, wrócić do drzewa
   prób. Meta-optymalizację polityki włączyć ostatnią.
