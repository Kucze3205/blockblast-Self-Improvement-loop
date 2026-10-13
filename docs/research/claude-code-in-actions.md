# Claude Code w GitHub Actions: sesje nieinteraktywne, skille z repo, rate limit

Data badania: 2026-09-20. Wersja akcji: `anthropics/claude-code-action@v1` (stan `main`).

Każde twierdzenie jest oznaczone:

- **[D]** — potwierdzone oficjalną dokumentacją (link w sekcji Źródła),
- **[K]** — potwierdzone czytaniem kodu źródłowego akcji (`anthropics/claude-code-action`, gałąź `main`),
- **[Z]** — zgadywane / wnioskowane, wymaga weryfikacji empirycznej.

---

## 1. Werdykt w jednym akapicie

Nieinteraktywna sesja Claude Code w GitHub Actions uwierzytelniona subskrypcją przez
`CLAUDE_CODE_OAUTH_TOKEN` jest **w pełni wykonalna i oficjalnie wspierana** **[D]**. Skille
z `.claude/skills/` ładują się automatycznie po `actions/checkout`, a konkretny skill wymusza
się podając `/nazwa-skilla` jako `prompt` **[D]**. Model i poziom reasoning effort ustawia się
per uruchomienie przez `claude_args` / `settings` / zmienne środowiskowe **[D]**.

**Częste założenie jest nieprawdziwe:** że „sesja czeka i wznawia się po
odnowieniu okna, zamiast paść". Mechanizm `autoContinueAtUsageLimit`, który to robi,
**nie działa w trybie `-p`/nieinteraktywnym — dokumentacja wprost wyklucza „background
sessions i `-p` runs"** **[D]**. Po wyczerpaniu limitu subskrypcji sesja w Actions **pada**,
a akcja rzuca wyjątkiem i job kończy się błędem **[K]**. Czekanie i wznawianie trzeba
zaimplementować **warstwę wyżej — w workflow**, nie w sesji. Sekcja 7 podaje gotowy
mechanizm.

Drugie, częściowo nieprawdziwe założenie: „Limity są per rodzina modeli — wyczerpany
Opus nie blokuje Sonneta". To prawda tylko dla limitów `Opus limit` / `Sonnet limit`.
Limit sesyjny (5 h) i tygodniowy (7 dni) są **wspólne dla wszystkich modeli** i przełączenie
modelu ich nie omija **[D]**.

---

## 2. Uwierzytelnianie subskrypcją

### 2.1 Generowanie tokenu

```bash
claude setup-token
```

**[D]** Komenda otwiera ten sam przepływ autoryzacji w przeglądarce co `/login`. Token
**drukuje się na terminalu po zatwierdzeniu i nie jest nigdzie zapisywany** — trzeba go
skopiować ręcznie. Właściwości:

- ważność: **jeden rok** **[D]**,
- wymaga planu **Pro, Max, Team lub Enterprise** **[D]**,
- **umie wyłącznie wysyłać zapytania do modelu** — nie ustanowi sesji Remote Control ani nie
  pobierze konektorów claude.ai. Lokalnie skonfigurowane serwery MCP działają **[D]**,
- jest **związany z subskrypcją osoby, która uruchomiła `claude setup-token`** — dlatego dokumentacja
  odradza go jako sekret współdzielony w organizacji i w tym scenariuszu poleca klucz API **[D]**,
- **tryb `--bare` go nie czyta** — nie używać `--bare` w tym workflow **[D]**.

Alternatywnie `/install-github-app` uruchomione lokalnie w repo zainstaluje aplikację GitHub,
zapisze sekret `CLAUDE_CODE_OAUTH_TOKEN` i otworzy PR z plikami workflow **[D]**.

### 2.2 Zapis sekretu i przekazanie do akcji

Sekret repo: `CLAUDE_CODE_OAUTH_TOKEN`. W workflow:

```yaml
- uses: anthropics/claude-code-action@v1
  with:
    claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
```

**[K]** `action.yml` mapuje to na zmienną środowiskową procesu Claude Code:
`CLAUDE_CODE_OAUTH_TOKEN: ${{ inputs.claude_code_oauth_token || env.CLAUDE_CODE_OAUTH_TOKEN }}`
— czyli **zadziała też ustawienie samej zmiennej `env` na poziomie joba**, bez podawania inputu.

### 2.3 Pierwszeństwo poświadczeń — pułapka

**[D]** Kolejność wyboru poświadczeń: `ANTHROPIC_AUTH_TOKEN` → `ANTHROPIC_API_KEY` →
`apiKeyHelper` → `CLAUDE_CODE_OAUTH_TOKEN` → profile → login `/login`.
Jeśli w środowisku joba będzie ustawiony `ANTHROPIC_API_KEY`, **wygra on nad tokenem
subskrypcji** i rachunek pójdzie na API. W trybie `-p` klucz jest używany zawsze, gdy jest
obecny, bez pytania. **Nie ustawiać `ANTHROPIC_API_KEY` w tym workflow.**

### 2.4 Uprawnienia po stronie GitHuba

**[D]** Akcja korzysta z trzech uprawnień aplikacji GitHub: `Contents` (rw), `Issues` (rw),
`Pull requests` (rw). Instalując oficjalną aplikację Claude akceptuje się cały jej zestaw
(m.in. `Actions` rw, `Workflows` rw) — GitHub nie pozwala przyjąć podzbioru. Dla organizacji
wymagających minimum: własna aplikacja GitHub z trzema uprawnieniami.

Uprawnienia joba, minimalne dla naszego scenariusza **[D]**:

```yaml
permissions:
  contents: write        # commit i push
  issues: write          # tworzenie i komentowanie issues
  pull-requests: write   # otwieranie PR
  id-token: write        # wymagane przez domyślne uwierzytelnianie akcji jako GitHub App
  actions: read          # odczyt wyników CI (opcjonalne)
```

---

## 3. Tryb interaktywny vs automation — który nas obowiązuje

**[D]** Akcja wykrywa tryb z konfiguracji:

| Warunek | Tryb | Zachowanie |
| --- | --- | --- |
| brak inputu `prompt` | **interactive (tag)** | czeka na frazę `@claude` w issue/PR; postęp w komentarzu |
| jest input `prompt` | **automation (agent)** | odpala się na dowolnym zdarzeniu GitHuba, wynik w logu joba |

Pętla wyzwalana issue z etykietą (issue → sesja) to **tryb automation**.

**[K] To istotna różnica dla uprawnień.** W trybie tag akcja sama dokłada
`--permission-mode acceptEdits` i listę narzędzi bazowych (`src/modes/tag/index.ts`, l. 186).
W trybie agent (`src/modes/agent/index.ts`) **nie dokłada ani trybu uprawnień, ani żadnych
`--allowedTools`** — przekazuje tylko konfigurację MCP i surowe `claude_args` użytkownika.
Czyli w trybie automation **wszystko trzeba nadać samemu**.

### 3.1 Kto może wyzwolić przebieg

**[D]** Akcja sprawdza wyzwalającego aktora zanim Claude wystartuje i **job pada**, jeśli
którykolwiek test odpadnie:

- **prawo zapisu** — przy zdarzeniach issue/PR wyzwalający musi mieć write do repo.
  Zdarzenia bez autora (np. `schedule`) ten test pomijają.
- **człowiek, nie bot** — bot jest odrzucany, chyba że wpiszemy go w `allowed_bots`.
  **Dotyczy to też `schedule`**: GitHub przypisuje przebieg cron użytkownikowi, który ostatnio
  zmienił harmonogram; jeśli to bot, trzeba go wymienić w `allowed_bots`.

**Konsekwencja dla takiej pętli [Z]:** jeśli issues tworzy orchestrator działający jako
`github-actions[bot]` lub aplikacja GitHub, sesja wyzwolona przez takie issue **zostanie
odrzucona**, dopóki nie doda się tego bota do `allowed_bots`. To trzeba przetestować
empirycznie przed uzbrojeniem pętli.

---

## 4. Skille żyjące w repo

### 4.1 Ładowanie

**[D]** Skille projektowe leżą w `.claude/skills/<nazwa>/SKILL.md` i ładują się w sesjach
w tym repozytorium. Warunek w Actions: **`actions/checkout` musi stać przed krokiem
`anthropics/claude-code-action`**, żeby pliki skilla były na runnerze.

**[K]** Akcja uruchamia Claude Code z `settingSources: ["user", "project", "local"]`
(`base-action/src/parse-sdk-options.ts`), czyli **czyta `.claude/settings.json` z repo**.
Nie używa trybu `--bare`, więc autodiscovery skilli, hooków, subagentów i `CLAUDE.md` działa.
Jeśli chcemy to zawęzić: `--setting-sources user,project` w `claude_args` jest respektowane.

**[D] Uwaga bezpieczeństwa i pułapka przy PR-ach:** gdy akcja działa na pull requeście,
przed startem **przywraca z gałęzi bazowej PR** ustaloną listę ścieżek konfiguracyjnych:
`.claude/`, `.mcp.json`, `.claude.json`, `.gitmodules`, `.ripgreprc`, `CLAUDE.md`,
`CLAUDE.local.md`, `.husky/`. Wersje z PR-a lądują w `.claude-pr/` tylko do wglądu.
**Zmiana skilla w PR nie zadziała w sesji uruchomionej na tym PR** — skill musi być już
na gałęzi bazowej.

### 4.2 Wymuszenie konkretnego skilla na starcie

**[D]** Input `prompt` przyjmuje wywołanie skilla zamiast zwykłego tekstu:

```yaml
prompt: "/wayfinder 12"
```

- skill z repo (`.claude/skills/wayfinder/`) → `/wayfinder`,
- skill z pluginu → `/nazwa-pluginu:nazwa-skilla`, plus inputy `plugin_marketplaces` i `plugins`.

Argumenty przechodzą przez `$ARGUMENTS` albo nazwane pola z frontmattera `arguments:` **[D]**.
W `-p` skille wywoływane przez użytkownika działają: Claude Code rozwija `/nazwa-skilla`
w stringu promptu przed uruchomieniem **[D]**.

### 4.3 `allowed-tools` w skillu a `--allowedTools` w workflow

**[D]** Frontmatter `allowed-tools:` w `SKILL.md` przyznaje uprawnienia do wymienionych
narzędzi na czas tury, w której skill został wywołany. Dokumentacja Actions mówi wprost:
przy zwykłym prompcie tekstowym Claude nie ma dostępu do powłoki ani API GitHuba, dopóki
się ich nie nada; **przy wywołaniu skilla Claude może używać narzędzi z jego `allowed-tools`**.

**[D] Ale jest wyjątek, który łatwo przeoczyć:** serwery MCP akcji (np. ten od komentarzy
inline) **startują tylko wtedy, gdy `--allowedTools` w `claude_args` je wymienia**. Frontmatter
skilla tego nie załatwia. Dokumentacja podaje to przy przykładzie code-review. **[K]** Potwierdza
to `src/mcp/install-mcp-server.ts`: w trybie agent serwery `github_comment`, `github_ci`,
`github_inline_comment`, `github` są dokładane **tylko gdy w `allowedTools` pojawi się
odpowiedni prefiks `mcp__github*`**.

Wniosek praktyczny: **`--allowedTools` w `claude_args` traktować jako źródło prawdy**,
a frontmatter skilla jako dodatek.

---

## 5. Model i reasoning effort per uruchomienie

### 5.1 Model

**[D]** `claude_args: --model <alias|pełna-nazwa>`. Bez tego używany jest domyślny model
Claude Code. Aliasy: `default`, `best`, `fable`, `opus`, `sonnet`, `haiku`, `opusplan`.
Alias `default` to model zależny od typu konta (Opus 5 dla Max/Enterprise/API, Sonnet 5 dla Pro).

Sonnet 5 jako koń roboczy i Opus 5 rzadko → `--model sonnet` domyślnie,
`--model opus` dla zadań wymagających.

### 5.2 Effort level

**[D]** Poziomy: `low`, `medium`, `high` (domyślny), `xhigh`, `max`, `ultracode`.
Trzy drogi ustawienia per uruchomienie:

| Droga | Zapis | Status |
| --- | --- | --- |
| flaga CLI | `claude_args: --effort medium` | **[Z]** przechodzi przez pass-through `extraArgs`, ale akcja tego nie dokumentuje |
| zmienna środowiskowa | `env: CLAUDE_CODE_EFFORT_LEVEL: medium` | **[D]** dla CLI; **[K]** akcja przekazuje całe `process.env` do Claude Code |
| plik ustawień | `settings: '{"effortLevel": "medium"}'` | **[D]** input `settings` + klucz `effortLevel` |

**Rekomendacja:** `CLAUDE_CODE_EFFORT_LEVEL` w bloku `env:` joba — najmniej założeń,
udokumentowana z obu stron. **[K]** `parse-sdk-options.ts` buduje env sesji jako
`{ ...process.env }`, więc każda zmienna joba dociera do Claude Code (usuwane są tylko
`ACTIONS_ID_TOKEN_REQUEST_*` i `ALL_INPUTS`).

### 5.3 Łańcuch zapasowy modeli

**[D]** `--fallback-model sonnet,haiku` — automatyczne przełączenie, gdy model główny jest
przeciążony lub niedostępny. **To nie jest mechanizm na limit subskrypcji** (patrz sekcja 7),
tylko na 529/wycofane modele.

---

## 6. Uprawnienia do narzędzi w trybie nieinteraktywnym

### 6.1 Jak w ogóle działa tryb uprawnień bez człowieka

**[D]** W `-p` **wbudowany startowy tryb uprawnień to Manual (`default`) na każdym planie**.
Manual pozwala bez pytania tylko na odczyt. Wszystko inne pyta — a pytać nie ma kogo.

**[K]** Komentarz w kodzie akcji mówi to wprost:
> `Headless SDK has no prompt handler, so anything that falls through to "ask" is denied.`

Czyli **domyślnie w trybie automation Claude nie zapisze pliku, nie odpali `git commit`
i nie wyszuka w sieci**. Trzeba jawnie ustawić tryb i listę narzędzi.

### 6.2 Wybór trybu

| Tryb | Co przechodzi bez pytania | Ocena dla naszej pętli |
| --- | --- | --- |
| `default` (Manual) | tylko odczyty | za mało |
| `acceptEdits` | odczyty, edycje plików, `mkdir`/`touch`/`mv`/`cp` | **rekomendowany**; reszta przez `--allowedTools` |
| `dontAsk` | odczyty + wyłącznie reguły `allow`; reszta **odmawiana** | dobre dla bardzo zamkniętych jobów |
| `auto` | wszystko, z klasyfikatorem w tle | mniej przewidywalne; wymaga wspieranego modelu |
| `bypassPermissions` | wszystko | tylko w izolacji; patrz niżej |

**[D]** `acceptEdits` auto-zatwierdza zapisy plików **wewnątrz katalogu roboczego**
(`$GITHUB_WORKSPACE`) i odmawia poza nim — dokładnie tego chce akcja w trybie tag,
z jawnym uzasadnieniem w kodzie **[K]**: listowanie `Edit`/`Write` w `allowedTools` dałoby
prawo zapisu do całego runnera (np. `~/.bashrc`), a `acceptEdits` ogranicza to do workspace'u.
**Powielamy ten wzorzec w trybie automation.**

**[D] O `bypassPermissions`:** `--dangerously-skip-permissions` działa i jest
udokumentowanym wzorcem dla „fully unattended inside a container". Na Linuksie **Claude Code
odmawia startu w tym trybie jako root/sudo**; runner GitHuba działa jako `runner`, więc
formalnie przejdzie **[Z]**. Nawet wtedy kilka rzeczy nadal pyta (a w `-p` jest odmawianych):
jawne reguły `ask`, `AskUserQuestion`, `rm`/`rmdir` na ścieżkach krytycznych.
**Nie rekomendowane** dla repo, które ma być publiczne i przyjmować treści z zewnątrz —
`bypassPermissions` nie daje żadnej ochrony przed prompt injection.

### 6.3 Konkretna lista narzędzi dla naszego scenariusza

Składnia reguł: `Bash(git commit *)` — spacja przed `*` jest znacząca; bez niej
`Bash(git diff*)` złapałoby też `git diff-index` **[D]**.

```
Edit, Write, Read, Glob, Grep,
Bash(git status *), Bash(git add *), Bash(git commit *), Bash(git push *),
Bash(git checkout *), Bash(git switch *), Bash(git diff *), Bash(git log *),
Bash(gh issue create *), Bash(gh issue comment *), Bash(gh issue close *),
Bash(gh issue view *), Bash(gh issue list *),
Bash(gh pr create *), Bash(gh pr view *), Bash(gh pr comment *),
Bash(python *), Bash(pytest *), Bash(pip install *),
WebSearch, WebFetch
```

Uwagi:

- **`WebSearch` nie przyjmuje specyfikatora** — goła nazwa `WebSearch` w `allow`/`deny` to
  jedyna forma **[D]**. Bez niej Claude pyta o zgodę, czyli w `-p` dostaje odmowę **[D]**.
  Limit: **200 wywołań WebSearch na sesję**, liczone łącznie z subagentami **[D]**.
  WebSearch działa na ścieżce Claude API (a więc i przy uwierzytelnieniu subskrypcją) **[D]**;
  Bedrock go nie wystawia.
- **`WebFetch(domain:...)`** dla domen kontrolowanych; `WebFetch(domain:*)` dla wszystkiego.
  Goła reguła `WebFetch` i `WebFetch(domain:*)` różnią się zachowaniem przy sandboxie **[D]**.
- **`Edit`/`Write` na liście vs `acceptEdits`**: jeśli ustawisz `--permission-mode acceptEdits`,
  **nie musisz** (i lepiej nie) wpisywać `Edit`/`Write` do `--allowedTools` — `acceptEdits`
  ogranicza zapisy do workspace'u, a wpis w allowlist ich nie ogranicza **[K]**.
- **`gh` wymaga tokenu w środowisku.** **[K]** Akcja **nie** wstrzykuje `GH_TOKEN` do sesji
  Claude'a. Trzeba ustawić `GH_TOKEN` w bloku `env:` joba (dziedziczy się do procesu Claude Code)
  albo przez `settings: {"env": {...}}` **[D]**.
- Alternatywa dla `gh`: narzędzia MCP `mcp__github__*` (oficjalny serwer GitHub MCP w dockerze),
  dokładane przez akcję, gdy `--allowedTools` zawiera prefiks `mcp__github__` **[K]**.
  `gh` przez Bash jest prostszy i nie wymaga dockera.

### 6.4 Otwieranie PR i commitowanie

**[D]** W konfiguracji domyślnej (tryb tag) **Claude nie tworzy PR-ów automatycznie** — commituje
na gałąź i podaje link do strony tworzenia PR. W trybie automation z nadanym
`Bash(gh pr create *)` i `GH_TOKEN` **[Z]** Claude utworzy PR sam; to najprostsza droga i tak
działa oficjalny przykład code-review, który przez MCP komentuje PR-y.

**[K]** W trybie agent akcja konfiguruje uwierzytelnianie git (`configureGitAuth`) tokenem
aplikacji, więc `git push` z sesji działa bez dodatkowej konfiguracji zdalnej.

**[D] Pułapka CI:** GitHub nie wyzwala workflowów na commitach zrobionych domyślnym
`GITHUB_TOKEN`. Jeśli przekażesz `github_token: ${{ secrets.GITHUB_TOKEN }}` do akcji, pushe
Claude'a **nie odpalą żadnego CI**. Dla samopodtrzymującej się pętli to zabójcze — **nie
przekazuj `github_token`**, pozwól akcji uwierzytelnić się jako GitHub App.

**[D]** Claude **nie może modyfikować plików workflow** (ograniczenie bezpieczeństwa akcji)
ani robić rebase/merge/force-push. Zmiany w `.github/workflows/` musi robić człowiek
albo osobny mechanizm.

---

## 7. Rate limit: co się dzieje i jak przeżyć

### 7.1 Komunikaty

**[D]** Po wyczerpaniu okna subskrypcji pojawia się jeden z:

```
You've hit your session limit · resets 3:45pm
You've hit your weekly limit · resets Mon 12:00am
You've hit your Opus limit · resets 3:45pm
You've hit your Sonnet limit · resets 3:45pm
```

**[D]** Claude Code blokuje dalsze zapytania do czasu resetu. Limit sesyjny (5 h) i tygodniowy
(7 dni) są **wspólne dla wszystkich modeli** — przełączenie modelu ich nie omija.
Limity `Opus`/`Sonnet` dotyczą wyłącznie danej rodziny, więc przejście na model spoza rodziny
przywraca pracę. Zużycie liczy się **równolegle** do okna sesyjnego i tygodniowego, więc
jeden zryw (np. duże rozgałęzienie workflowów) potrafi wyczerpać tydzień przed resetem sesji.

### 7.2 `autoContinueAtUsageLimit` — nie działa w Actions

**[D]** Mechanizm istnieje i robi dokładnie to, czego pętla potrzebuje: czeka w otwartej sesji
i sam podejmuje przerwane zadanie po resecie (domyślnie włączony, wymaga v2.1.234+).
**Ale dokumentacja wprost wymienia, gdzie Claude Code tego czekania w ogóle nie oferuje:**

> Claude Code doesn't offer the wait at all in these cases:
> - **Background sessions and `-p` runs**: the menu row isn't available.

Sesja w GitHub Actions to uruchomienie `-p` (Agent SDK). **Czekanie nie zadziała.**
Dodatkowo, nawet w trybie interaktywnym Claude Code **nie startuje czekania sam**, gdy reset
jest **dalej niż 24 h** — a limit tygodniowy potrafi resetować się za kilka dni **[D]**.

### 7.3 `CLAUDE_CODE_RETRY_WATCHDOG` — pomaga, ale nie na to

**[D]** `CLAUDE_CODE_RETRY_WATCHDOG=1` jest przeznaczony dokładnie dla „unattended sessions
such as CI jobs": każe w nieskończoność ponawiać błędy pojemnościowe `429` i `529` zamiast
poddać się po `CLAUDE_CODE_MAX_RETRIES`. Podnosi też domyślną liczbę ponowień dla innych
błędów przejściowych do 300 (ok. trzy godziny backoffu) i zdejmuje limit 15 z
`CLAUDE_CODE_MAX_RETRIES`.

**Czego nie robi:** dokumentacja mówi, że Claude Code **pada natychmiast**, gdy `429` raportuje
spend limit albo wyczerpane usage credits. Lista automatycznych ponowień obejmuje
„temporary 429 throttles", a dla kont claude.ai doprecyzowuje: „429 throttles **that don't
carry your plan's quota headers**". Odczytuję to tak, że **429 niosący nagłówki kwot planu,
czyli prawdziwy limit subskrypcji, nie jest ponawiany** **[Z — wnioskowanie z dwóch akapitów
dokumentacji, nie z jednego zdania wprost]**.

**Wniosek:** watchdog warto włączyć (chroni przed przeciążeniami serwera w długim jobie),
ale **nie jest odpowiedzią na limit subskrypcji**.

### 7.4 Co realnie robi akcja po trafieniu w limit

**[K]** `base-action/src/run-claude-sdk.ts`:

- iteruje po wiadomościach z `query()` i zbiera je,
- gdy wiadomość `result` ma `is_error: true` lub `subtype != "success"`, ustawia
  `conclusion: "failure"` i **rzuca** `Claude execution failed: ...`,
- **żadnej logiki świadomej limitu użycia nie ma.** `base-action/src/retry.ts` to zwykły
  backoff (3 próby, 5→20 s) i **nie jest używany do ponawiania samej sesji**.

Czyli: **limit → błąd wyniku → wyjątek → job czerwony**. Potwierdza to werdykt z sekcji 1.

**[K]** Dwie rzeczy, które akcja zostawia i które można wykorzystać:

- output kroku **`session_id`** — „can be used with `--resume` to continue this conversation",
- plik **`$RUNNER_TEMP/claude-execution-output.json`** (stała `EXECUTION_FILENAME`) z pełnym
  zrzutem wszystkich wiadomości SDK; jego ścieżkę akcja wystawia też jako output `execution_file`.
  **Uwaga:** bez `show_full_output: true` log joba pokazuje tylko okrojone podsumowanie
  (`subtype`, `is_error`, `num_turns`, koszt) — **treść błędu jest w pliku, nie w logu** **[K]**.
  Parsowanie pliku w osobnym kroku jest bezpieczniejsze niż `show_full_output: true`,
  które wysypuje całą sesję do publicznego logu.

### 7.5 Odczyt czasu resetu

Trzy drogi, w kolejności malejącej pewności:

1. **Parsowanie tekstu błędu** z `claude-execution-output.json` wzorcami
   `You've hit your (session|weekly|Opus|Sonnet) limit` i `resets (.+)`. Format komunikatu
   jest udokumentowany **[D]**, ale to czas lokalny w formacie ludzkim (`3:45pm`,
   `Mon 12:00am`) — na runnerze GitHuba strefa to UTC **[Z]**. Obecność tego tekstu
   w pliku wykonania **wymaga weryfikacji empirycznej** **[Z]**.
2. **Pole `rate_limits.five_hour.resets_at` / `rate_limits.seven_day.resets_at`** — to
   **uniksowe sekundy epoki**, czyli forma nadająca się do maszyny **[D]**. Problem:
   dokumentacja opisuje je jako dane podawane na stdin skryptowi **status line**, a status
   line to element interfejsu. **Czy uruchamia się w `-p` — niepotwierdzone [Z].**
   Gdyby działał, to najczystsze źródło czasu resetu (hook statusline zapisujący JSON do pliku).
3. **Backoff stały** — jeśli 1 i 2 zawiodą: okno sesyjne to 5 h, więc reset jest najwyżej
   5 h w przód. Ponawianie co 60 min z limitem prób jest zawsze bezpieczne **[Z]**.

**Rekomendacja:** zbudować na (1) z fallbackiem na (3). Nie opierać pętli na (2), dopóki
nie zostanie sprawdzone.

### 7.6 Wzorzec „poczekaj i wznów" — dwa poziomy

**Poziom A — czekanie w tym samym jobie (limit sesyjny).**
Reset limitu sesyjnego jest ≤ 5 h, a job GitHub-hosted może żyć 6 h **[D]**. Jeśli
`reset − teraz + margines` mieści się w pozostałym budżecie joba, można po prostu `sleep`
i odpalić **drugi krok** akcji z `--resume ${{ steps.claude.outputs.session_id }}`.
Transkrypt sesji leży na tym samym runnerze, więc `--resume` ma czego szukać **[Z — logiczne,
ale nietestowane]**. To rozwiązanie najbliższe temu, czego pętla potrzebuje: **sesja realnie
podejmuje przerwane zadanie**.

Koszt: minuty Actions lecą podczas `sleep`. Dla repo publicznego minuty są darmowe, więc
przy publicznym repo jest to akceptowalne **[D]**.

**Poziom B — przełożenie na później (limit tygodniowy, reset > budżet joba).**
Job nie ma szans doczekać. Wtedy: zapisz stan (gałąź z commitami Claude'a już istnieje),
odnotuj żądanie wznowienia i pozwól osobnemu workflowowi cron podnieść je, gdy nadejdzie czas.
Sesji nie da się wznowić przez `--resume` (transkrypt ginie z runnerem), więc **wznowienie
poziomu B musi być nową sesją, która czyta stan z repo/issue**. To wymusza projektową zasadę:

> **Każda sesja ma checkpointować postęp do repo (commit) i do issue (komentarz), bo tylko
> to przeżyje utratę runnera.**

**Poziom C — przełączenie rodziny modeli.**
Dla limitów `Opus limit` / `Sonnet limit` (ale **nie** dla sesyjnego/tygodniowego) ponowienie
z `--model` spoza rodziny wznowi pracę od razu **[D]**. Warto wstawić jako pierwszą próbę,
zanim zacznie się czekać.

---

## 8. Limity czasu i długości sesji

**[D]** GitHub:

- job na runnerze GitHub-hosted: **do 6 godzin**; po przekroczeniu jest przerywany,
- cały workflow run: do 35 dni,
- pojedynczy run można ponowić maksymalnie 50 razy,
- w publicznym repo cron przestaje odpalać po **60 dniach bez aktywności** w repo **[D]** —
  dla pętli samopodtrzymującej się to nieistotne, dopóki pętla żyje, ale jest to warunek
  „obudzenia" po dłuższej przerwie.

Ustaw `timeout-minutes` jawnie na poziomie joba — inaczej zabraknie miejsca na krok
obsługujący limit po padzie sesji.

**[D]** Claude Code:

- `--max-turns N` w `claude_args` — **tylko w trybie print**; po osiągnięciu limitu
  **kończy się błędem**. **[K]** Akcja dodatkowo sama rzuca wyjątkiem, jeśli wynik zgłosi
  sukces przy `num_turns > maxTurns`. Czyli **`--max-turns` to twardy hamulec, nie miękkie
  zakończenie** — job zrobi się czerwony. Jeśli pętla ma odróżniać „limit tur" od „limit
  subskrypcji", trzeba to rozpoznawać po `subtype` w pliku wykonania **[Z]**.
- `API_TIMEOUT_MS` (domyślnie 600000) — timeout pojedynczego zapytania,
- `CLAUDE_CODE_MAX_RETRIES` (domyślnie 10, cap 15; watchdog zdejmuje cap).

**[D] `--max-turns` jest też oficjalną radą na koszty** obok `timeout-minutes` i `concurrency`.

---

## 9. Gotowy szkic workflow

Plik: `.github/workflows/agent-session.yml`. Zakłada sekret `CLAUDE_CODE_OAUTH_TOKEN`,
zmienną repo `AUTOPILOT` i skill `.claude/skills/<rola>/SKILL.md` wybierany etykietą issue.

```yaml
name: Agent session

on:
  issues:
    types: [labeled]
  workflow_dispatch:
    inputs:
      issue:
        description: "Numer issue do podjęcia"
        required: true
      skill:
        description: "Nazwa skilla roli, np. wayfinder"
        required: true
      attempt:
        description: "Numer próby (obsługa rate limitu)"
        default: "1"

concurrency:
  group: agent-${{ github.event.issue.number || inputs.issue }}
  cancel-in-progress: false

jobs:
  session:
    # Strażnik autopilota — pierwszy krok, zgodnie z mapą.
    if: vars.AUTOPILOT == 'on' && startsWith(github.event.label.name || 'role:', 'role:')
    runs-on: ubuntu-latest
    # 6 h to twardy limit GitHuba; zostawiamy margines na kroki po sesji.
    timeout-minutes: 330

    permissions:
      contents: write
      issues: write
      pull-requests: write
      id-token: write
      actions: read

    env:
      # gh CLI w Bashu Claude'a - akcja NIE wstrzykuje tego sama
      GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      # unattended CI: ponawiaj 429/529 pojemnościowe w nieskonczonosc
      CLAUDE_CODE_RETRY_WATCHDOG: "1"
      # reasoning effort per uruchomienie - droga najmniej zalozeniowa
      CLAUDE_CODE_EFFORT_LEVEL: medium

    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0          # pelna historia; skille z .claude/skills/ trafiaja na runnera

      # ---------- próba 1: model z rodziny Sonnet ----------
      - name: Claude session
        id: claude
        continue-on-error: true
        uses: anthropics/claude-code-action@v1
        with:
          claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          prompt: "/${{ github.event.label.name && 'wayfinder' || inputs.skill }} ${{ github.event.issue.number || inputs.issue }}"
          claude_args: |
            --model sonnet
            --permission-mode acceptEdits
            --max-turns 150
            --allowedTools "Read,Glob,Grep,WebSearch,WebFetch,Bash(git status *),Bash(git add *),Bash(git commit *),Bash(git push *),Bash(git checkout *),Bash(git switch *),Bash(git diff *),Bash(git log *),Bash(git worktree *),Bash(gh issue view *),Bash(gh issue list *),Bash(gh issue create *),Bash(gh issue edit *),Bash(gh issue comment *),Bash(gh issue close *),Bash(gh pr create *),Bash(gh pr view *),Bash(gh pr comment *),Bash(python *),Bash(pytest *),Bash(pip install *)"

      # ---------- rozpoznanie przyczyny pada ----------
      - name: Classify failure
        id: why
        if: always() && steps.claude.outcome == 'failure'
        shell: bash
        run: |
          F="$RUNNER_TEMP/claude-execution-output.json"
          echo "kind=unknown" >> "$GITHUB_OUTPUT"
          [ -f "$F" ] || exit 0

          # Komunikaty sa udokumentowane w code.claude.com/docs/en/errors
          if   grep -qi "hit your Opus limit"    "$F"; then K=family
          elif grep -qi "hit your Sonnet limit"  "$F"; then K=family
          elif grep -qi "hit your session limit" "$F"; then K=session
          elif grep -qi "hit your weekly limit"  "$F"; then K=weekly
          else K=other
          fi
          echo "kind=$K" >> "$GITHUB_OUTPUT"

          # "resets 3:45pm" / "resets Mon 12:00am" -> sekundy do resetu (UTC runnera)
          RESET_TXT=$(grep -oiE "resets [A-Za-z0-9: ]+" "$F" | head -1 | sed 's/^[Rr]esets //')
          if [ -n "$RESET_TXT" ] && date -d "$RESET_TXT" +%s >/dev/null 2>&1; then
            WAIT=$(( $(date -d "$RESET_TXT" +%s) - $(date +%s) + 120 ))
          else
            WAIT=3600                      # fallback: okno sesyjne to 5 h, godzina jest zawsze bezpieczna
          fi
          [ "$WAIT" -lt 0 ] && WAIT=120
          echo "wait=$WAIT" >> "$GITHUB_OUTPUT"
          echo "Limit=$K, czekanie ${WAIT}s"

      # ---------- C: limit rodziny modeli -> natychmiast inna rodzina ----------
      - name: Retry on another model family
        id: retry_family
        if: steps.why.outputs.kind == 'family'
        continue-on-error: true
        uses: anthropics/claude-code-action@v1
        with:
          claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          prompt: "Kontynuuj przerwane zadanie z issue #${{ github.event.issue.number || inputs.issue }} od miejsca, w ktorym sie zatrzymalo."
          claude_args: |
            --model haiku
            --permission-mode acceptEdits
            --max-turns 80
            --resume ${{ steps.claude.outputs.session_id }}

      # ---------- A: limit sesyjny, reset mieści się w budżecie joba -> czekaj i wznów ----------
      - name: Wait for reset
        if: steps.why.outputs.kind == 'session' && steps.why.outputs.wait < 18000
        run: sleep ${{ steps.why.outputs.wait }}

      - name: Resume after reset
        id: resume
        if: steps.why.outputs.kind == 'session' && steps.why.outputs.wait < 18000
        continue-on-error: true
        uses: anthropics/claude-code-action@v1
        with:
          claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          prompt: "Kontynuuj przerwane zadanie z issue #${{ github.event.issue.number || inputs.issue }} od miejsca, w ktorym sie zatrzymalo."
          claude_args: |
            --model sonnet
            --permission-mode acceptEdits
            --max-turns 150
            --resume ${{ steps.claude.outputs.session_id }}

      # ---------- B: limit tygodniowy / reset poza budżetem -> przełóż na później ----------
      - name: Park for later
        if: steps.why.outputs.kind == 'weekly' || (steps.why.outputs.kind == 'session' && steps.why.outputs.wait >= 18000)
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          AT=$(( $(date +%s) + ${{ steps.why.outputs.wait }} ))
          gh issue edit ${{ github.event.issue.number || inputs.issue }} --add-label "blocked:rate-limit"
          gh issue comment ${{ github.event.issue.number || inputs.issue }} --body \
            "Sesja zatrzymana na limicie subskrypcji (${{ steps.why.outputs.kind }}). Wznowienie nie wczesniej niz $(date -u -d @$AT --iso-8601=seconds). Proba: ${{ inputs.attempt || 1 }}."

      # ---------- werdykt joba ----------
      - name: Conclude
        if: always()
        run: |
          if [ "${{ steps.claude.outcome }}" = "success" ] \
          || [ "${{ steps.resume.outcome }}" = "success" ] \
          || [ "${{ steps.retry_family.outcome }}" = "success" ]; then
            echo "Sesja zakonczona."
          elif [ "${{ steps.why.outputs.kind }}" = "weekly" ] || [ "${{ steps.why.outputs.kind }}" = "session" ]; then
            echo "::warning::Limit subskrypcji - zadanie odlozone, nie traktuj jako awarii."
          else
            echo "::error::Sesja padla z przyczyny innej niz limit."
            exit 1
          fi
```

Workflow towarzyszący — budzik dla poziomu B:

```yaml
name: Rate limit reaper

on:
  schedule:
    - cron: "*/30 * * * *"

jobs:
  wake:
    if: vars.AUTOPILOT == 'on'
    runs-on: ubuntu-latest
    permissions:
      issues: write
      actions: write
    env:
      GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    steps:
      - name: Re-dispatch parked issues whose reset has passed
        run: |
          gh issue list --label "blocked:rate-limit" --json number,comments --jq '.[].number' | while read -r N; do
            AT=$(gh issue view "$N" --json comments \
                 --jq '[.comments[].body | capture("nie wczesniej niz (?<t>\\S+)").t] | last // empty')
            [ -n "$AT" ] || continue
            [ "$(date -u +%s)" -ge "$(date -u -d "$AT" +%s)" ] || continue
            gh issue edit "$N" --remove-label "blocked:rate-limit"
            gh workflow run agent-session.yml -f issue="$N" -f skill=wayfinder -f attempt=2
          done
```

**Uwaga [D] do budzika:** `schedule` przypisuje przebieg użytkownikowi, a akcja **odrzuca
bota**. Sam reaper nie uruchamia akcji Claude'a, więc jest bezpieczny — ale `workflow_dispatch`
wywołany przez `GITHUB_TOKEN` będzie miał aktora `github-actions[bot]`, więc **agent-session
musi mieć `allowed_bots: "github-actions[bot]"`**, albo dispatch musi lecieć tokenem aplikacji
GitHub. To ten sam problem, co w sekcji 3.1 — **do przetestowania przed uzbrojeniem pętli**.

---

## 10. Co zostaje do sprawdzenia empirycznie

1. Czy tekst `You've hit your ... limit · resets ...` faktycznie trafia do
   `$RUNNER_TEMP/claude-execution-output.json` **[Z]**. Bez tego sekcja 7.5 punkt 1 upada
   i zostaje backoff stały.
2. Czy `--resume <session_id>` działa w drugim kroku akcji w tym samym jobie **[Z]**.
3. Czy `allowed_bots` wystarczy, żeby issue utworzone przez orchestratora wyzwoliło sesję **[Z]**.
4. Czy `--effort` przechodzi przez `claude_args` **[Z]** (obejście: `CLAUDE_CODE_EFFORT_LEVEL`).
5. Czy skrypt `statusLine` uruchamia się w trybie `-p` — jeśli tak, `rate_limits.*.resets_at`
   daje czas resetu w sekundach epoki i punkt 1 przestaje być potrzebny **[Z]**.

---

## Źródła

Dokumentacja oficjalna (code.claude.com):

- [GitHub Actions](https://code.claude.com/docs/en/github-actions) — setup, tryby, `claude_args`, parametry akcji, skille w prompt, koszty
- [Authentication](https://code.claude.com/docs/en/authentication) — `claude setup-token`, rok ważności, pierwszeństwo poświadczeń
- [Run Claude Code programmatically (headless)](https://code.claude.com/docs/en/headless) — `-p`, tryby uprawnień w CI, `--permission-prompts none`, `--bare`
- [Choose a permission mode](https://code.claude.com/docs/en/permission-modes) — `acceptEdits`, `dontAsk`, `bypassPermissions`, root/sudo
- [Manage permissions](https://code.claude.com/docs/en/permissions) — składnia reguł, co wymaga zgody
- [Skills](https://code.claude.com/docs/en/skills) — `.claude/skills/`, `/nazwa`, `allowed-tools`
- [Model configuration](https://code.claude.com/docs/en/model-config) — aliasy, effort levels, `--fallback-model`
- [Settings reference](https://code.claude.com/docs/en/settings-reference) — `autoContinueAtUsageLimit`, `effortLevel`, `permissions.*`
- [Interactive mode → Wait for a usage limit to reset](https://code.claude.com/docs/en/interactive-mode#wait-for-a-usage-limit-to-reset) — **kluczowe: wykluczenie `-p`**
- [Errors → Usage limits](https://code.claude.com/docs/en/errors#youve-hit-your-session-limit) — treść komunikatów, `CLAUDE_CODE_RETRY_WATCHDOG`, tabela ponowień
- [CLI reference](https://code.claude.com/docs/en/cli-reference) — `--max-turns`, `--permission-mode`, `--effort`, `--resume`, `--setting-sources`
- [Status line](https://code.claude.com/docs/en/statusline) — pola `rate_limits.*.resets_at`
- [Tools reference](https://code.claude.com/docs/en/tools-reference#websearch-tool-behavior) — WebSearch, limit 200 wywołań

Kod źródłowy `anthropics/claude-code-action` (gałąź `main`):

- `action.yml` — inputy, outputy (`session_id`, `execution_file`), mapowanie env
- `src/modes/agent/index.ts` — tryb automation: brak domyślnych uprawnień
- `src/modes/tag/index.ts` — tryb tag: `--permission-mode acceptEdits`, komentarz o braku prompt handlera
- `src/mcp/install-mcp-server.ts` — serwery MCP dokładane tylko przy pasujących `--allowedTools`
- `base-action/src/parse-sdk-options.ts` — `settingSources`, `env = {...process.env}`, pass-through `extraArgs`
- `base-action/src/run-claude-sdk.ts` — brak obsługi limitu użycia, rzucanie na `is_error`
- `base-action/src/execution-file.ts` — `$RUNNER_TEMP/claude-execution-output.json`
- `docs/usage.md`, `docs/configuration.md`, `docs/security.md`, `docs/capabilities-and-limitations.md`, `docs/faq.md`

GitHub:

- [Actions limits](https://docs.github.com/en/actions/reference/limits) — 6 h na job, 35 dni na run, 50 ponowień
