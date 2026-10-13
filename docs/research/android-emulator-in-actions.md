# Emulator Androida w GitHub Actions: instalacja APK, sterowanie, trwałość stanu

Data badania: 2026-09-20

> **Konwencja oznaczeń.** Każde twierdzenie ma etykietę:
> **[DOK]** — potwierdzone oficjalną dokumentacją (link przy twierdzeniu).
> **[ŹRÓDŁO]** — potwierdzone pierwotnym źródłem niebędącym dokumentacją (kod źródłowy, issue autora narzędzia, changelog).
> **[POMIAR]** — zmierzone w trakcie tego badania na prawdziwym emulatorze **albo** pochodzące z cudzego opublikowanego pomiaru (zaznaczam który). **Uwaga: pomiary własne robione były na Windows/WHPX/API 36, nie na Linux/KVM/API 34.** Rząd wielkości i kolejność wariantów są miarodajne, bezwzględne liczby dla runnera — nie.
> **[SZAC]** — moje oszacowanie/wnioskowanie. Nie zweryfikowane pomiarem. Traktuj jako hipotezę do sprawdzenia empirycznie.

---

## 0. Streszczenie (TL;DR)

1. **Emulator na `ubuntu-latest` z akceleracją KVM: TAK, potwierdzone.** GitHub udostępnił sprzętową wirtualizację na standardowych (nie larger) runnerach Linux 2 kwietnia 2024. Wymaga jednego kroku z regułą udev. **[DOK]**
2. **Instalacja APK, zrzut ekranu, swipe: TAK, wszystko udokumentowane w ADB.** **[DOK]**
3. **Prędkość: rząd 1–3 ruchy/s naiwnie, ~5 ruchów/s po optymalizacji.** **[SZAC]** — to oszacowanie, nie pomiar. Wąskim gardłem prawdopodobnie nie jest ADB, tylko **czas stabilizacji ekranu po ruchu przy renderowaniu programowym**. Patrz §4.4.
4. **Trwałość stanu między jobami: TAK, ale przez `actions/cache`, nie przez artefakty** — i najpewniej przez **przeniesienie dysku AVD, nie snapshotu RAM**. Google pisze wprost, że *„snapshots are not reliable when software rendering is enabled"*, a my musimy renderować programowo. **[DOK]**, patrz §5.2.
5. **Wybierz API ≥ 31.** Do API 30 każde `adb shell input` startowało nową JVM; od API 31 to cienki wrapper na `cmd`. Różnica rzędu wielkości w narzucie na ruch. **[ŹRÓDŁO]**, patrz §4.3.
6. **Największe ryzyka nie są techniczne.** Obrazy z Google Play **nie dają roota** (udokumentowane), gra może nie wystartować bez GMS lub wykryć emulator, a ToS GitHuba zakazuje używania Actions do „działań niezwiązanych z projektem". Patrz §7 i §8.
7. **Dwie rzeczy, które dotyczą pętli, a nie dotyczą emulatora:** repo jest dziś **prywatne** (§1.1), a łańcuch „workflow tworzy issue → issue odpala workflow" **nie zadziała** z domyślnym `GITHUB_TOKEN` (§6.2).

---

## 1. Runner: co dostajemy za darmo

### 1.1 Repo publiczne vs prywatne — to nie jest kosmetyka

| Parametr | Repo **publiczne** | Repo **prywatne** (stan obecny) |
|---|---|---|
| `ubuntu-latest` vCPU | **4** | 2 |
| RAM | **16 GB** | 8 GB |
| SSD (spec) | 14 GB | 14 GB |
| Minuty Actions | **darmowe i nielimitowane** | pula darmowa, potem płatne |

**[DOK]** — [GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners): *„Use of the standard GitHub-hosted runners is free and unlimited on public repositories."*
**[DOK]** — [Billing for GitHub Actions](https://docs.github.com/billing/managing-billing-for-github-actions/about-billing-for-github-actions): *„GitHub Actions usage is free for self-hosted runners and for public repositories that use standard GitHub-hosted runners."*

> **UWAGA — stan faktyczny w dniu badania.** `gh repo view --json visibility` zwraca `PRIVATE`. Dopóki repo jest prywatne, dostajemy **połowę CPU i RAM**, minuty są metrowane, a pula storage'u dla planu Free to 500 MB. Założenie „repo staje się publiczne" nie jest wygodą — jest **warunkiem koniecznym** całej pętli.

`ubuntu-latest` mapuje się obecnie na **Ubuntu 24.04**. **[DOK]**

### 1.2 Miejsce na dysku

Dokumentacja podaje 14 GB SSD, ale realnie system plików ma ~72 GB, z czego świeży runner ma **~20–22 GB wolnego** (reszta to preinstalowane narzędzia). **[SZAC]** — liczba powtarzalna w raportach społeczności ([actions/runner-images #9329](https://github.com/actions/runner-images/discussions/9329)), ale nie w oficjalnej dokumentacji.

Budżet dyskowy jednej sesji **[SZAC]**:
- obraz systemu `google_apis_playstore;x86_64` API 34: ~1,3–1,6 GB
- AVD po pierwszym boocie (`userdata-qemu.img.qcow2` + snapshot RAM): ~2–4 GB
- APK gry: ~100–300 MB
- zrzuty ekranu: zależne od długości sesji, patrz §4.5

Mieści się. Gdyby zabrakło — `jlumbroso/free-disk-space` zwalnia dodatkowe ~30 GB kosztem ~3 min.

### 1.3 Android SDK na obrazie runnera

Preinstalowane: cmdline-tools 12.0, platform-tools 37.0.1, build-tools, platformy android-34…37.
**Nie ma preinstalowanego emulatora ani żadnego obrazu systemu.** `ANDROID_HOME=/usr/local/lib/android/sdk`. **[DOK]** — [Ubuntu2404-Readme.md](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md)

Konsekwencja: każdy job bez cache'u pobiera emulator + obraz systemu (~1,5–2 GB). To argument za cache'owaniem `~/.android/avd` **i** `$ANDROID_HOME/system-images`.

---

## 2. KVM: jak włączyć

GitHub Changelog, 2 kwietnia 2024: sprzętowa akceleracja dla testów Androida dostępna na **2-vCPU GitHub-hosted Linux runners** (wcześniej tylko larger runners ≥4 vCPU). Wymaga dodania użytkownika runnera do grupy `kvm` przez regułę udev. **[DOK]** — [changelog](https://github.blog/changelog/2024-04-02-github-actions-hardware-accelerated-android-virtualization-now-available/)

Kanoniczny krok (identyczny w README `reactivecircus/android-emulator-runner`) **[ŹRÓDŁO]**:

```yaml
- name: Enable KVM group perms
  run: |
    echo 'KERNEL=="kvm", GROUP="kvm", MODE="0666", OPTIONS+="static_node=kvm"' \
      | sudo tee /etc/udev/rules.d/99-kvm4all.rules
    sudo udevadm control --reload-rules
    sudo udevadm trigger --name-match=kvm
```

Weryfikacja, że akceleracja faktycznie działa (warto mieć w workflow — bez tego cicho degradujemy do emulacji programowej):

```yaml
- name: Verify KVM
  run: |
    ls -l /dev/kvm
    sudo apt-get install -y cpu-checker
    kvm-ok
    $ANDROID_HOME/emulator/emulator -accel-check
```

`-accel-check` i `kvm-ok` to udokumentowane przez Google narzędzia diagnostyczne. **[DOK]** — [emulator-acceleration](https://developer.android.com/studio/run/emulator-acceleration)

### 2.1 Ile to daje — liczby

Pomiar autora issue [#370](https://github.com/ReactiveCircus/android-emulator-runner/issues/370) w repo `android-emulator-runner`, zdefiniowany jako czas od `emulator -avd` do `adb shell getprop sys.boot_completed` == 1 **[ŹRÓDŁO]**:

| Konfiguracja | Czas bootu |
|---|---|
| Linux **z KVM** | **15 s** |
| Linux bez akceleracji | 2 min 23 s |
| macOS (Hypervisor.Framework) | 1 min 23 s |

Czyli KVM to ~9,5× szybszy boot. Autor raportuje też skrócenie swojego zestawu testów UI z 12 do 6 minut.

**Architektura obrazu musi pasować do CPU hosta.** Na x86_64 używamy obrazów `x86_64`; obrazy ARM na hoście Intel/AMD **nie mogą** korzystać z akceleracji. **[DOK]** — *„AVDs that don't follow the requirements, such as ARM- or MIPS-based system images on Intel or AMD CPUs, can't use the VM acceleration."*

---

## 3. Grafika: pułapka `-gpu swiftshader_indirect`

Runner nie ma GPU, więc renderowanie jest programowe. Ale **domyślna wartość w `android-emulator-runner` (`-gpu swiftshader_indirect`) jest już wycofana**: dokumentacja Google oznacza `swiftshader_indirect`, `swangle_indirect` i `guest` jako **deprecated od emulatora 36.4.9**. Aktualne wartości to `software`, `swiftshader`, `swangle`, `lavapipe`, `auto`, `host`. **[DOK]** — [emulator-acceleration#command-gpu](https://developer.android.com/studio/run/emulator-acceleration)

Praktyczny wniosek: w `emulator-options` podajemy jawnie `-gpu swiftshader` (albo `-gpu software`) zamiast polegać na domyślce akcji.

**Ryzyko wydajnościowe [SZAC]:** Block Blast to gra 2D z animacjami, nie WebGL2. Programowa rasteryzacja na 4 vCPU powinna wyrobić czytelną planszę, ale **animacje (spadanie klocków, znikanie linii, cząsteczki) będą klatkowały**, a to wprost wydłuża czas, w którym ekran jest „nieustabilizowany" i nie nadaje się do parsowania. To jest realne ryzyko dla przepustowości pętli i **trzeba je zmierzyć, nie zakładać**. Wskaźnik do sprawdzenia: ile czasu mija od `input swipe` do momentu, w którym dwa kolejne zrzuty ekranu są identyczne.

---

## 4. Sterowanie: instalacja, zrzut ekranu, ruch

### 4.1 Instalacja APK

```bash
adb wait-for-device
adb install -r -g app.apk                 # pojedynczy APK
adb install-multiple -r -g base.apk split_*.apk   # split APK / AAB z Play Console
```

**[DOK]** — [adb](https://developer.android.com/tools/adb):
- `-r` — *„Reinstall an existing app, keeping its data."*
- `-g` — *„Grant all permissions listed in the app manifest."* (eliminuje dialogi uprawnień, które zasłoniłyby planszę)
- `install-multiple` — *„This is useful if you download all the APKs for a specific device for your app from the Play Console and want to install them on an emulator or physical device."*

**To jest istotne:** aplikacje z Google Play są dziś dystrybuowane jako **AAB → zestaw split APK** (base + config.<abi> + config.<dpi> + config.<lang>). Pobranie „jednego APK" z serwisu-mirrora często daje niekompletny zestaw i instalacja padnie z `INSTALL_FAILED_MISSING_SPLIT`. **[SZAC]** — mechanizm udokumentowany, konkretny tryb awarii z autopsji.

### 4.2 Zrzut ekranu

```bash
adb exec-out screencap -p > screen.png
```

**[DOK]** — dosłownie z dokumentacji adb: *„use 'exec-out' instead of 'shell' to get raw data"*.

Trzy warianty, w kolejności rosnącej wydajności:

| Wariant | Co się dzieje | Koszt |
|---|---|---|
| `adb shell screencap -p /sdcard/s.png` + `adb pull` | kodowanie PNG na urządzeniu **plus** zapis na dysk **plus** drugie połączenie ADB | najgorszy |
| `adb exec-out screencap -p > s.png` | kodowanie PNG na urządzeniu, strumień na stdout, jedno połączenie | średni |
| `adb exec-out screencap > s.raw` | **bez kodowania**: nagłówek (szerokość, wysokość, format) + surowe RGBA | najlepszy po stronie urządzenia, ale ~5–10× więcej bajtów przez transport |

**[DOK]** — dokumentacja adb podaje wprost, że `exec-out` służy do danych binarnych (*„use 'exec-out' instead of 'shell' to get raw data"*), bo `shell` przepuszcza strumień przez translację końców linii, która psuje PNG.

#### Format surowy: pomiar obala intuicję

Format surowy to 16-bajtowy nagłówek (`width`, `height`, `pixelFormat`, `dataspace`, little-endian) i dalej upakowane wiersze RGBA. **[ŹRÓDŁO]** — AOSP `cmds/screencap/screencap.cpp`. Zweryfikowane empirycznie: 1080×2424 → dokładnie 10 471 696 B = 16 + 1080·2424·4.

**Intuicja mówi, że surowy wygrywa, bo nie płacimy za kodowanie PNG na emulowanym CPU. Pomiar mówi, że nie.** **[POMIAR]** (Windows/WHPX, API 36, `-gpu swiftshader`, ADB przez pętlę zwrotną TCP, 1080×2424 — inny host niż runner, ale kolejność wariantów jest miarodajna):

| Operacja | n | średnia |
|---|---|---|
| `adb shell true` (czysty round-trip ADB) | 15 | **57 ms** |
| `adb shell screencap /dev/null` (samo przechwycenie, **bez transferu**) | 10 | **229 ms** |
| `adb exec-out screencap` (surowy, 10,5 MB przez kabel) | 10 | **625 ms** |
| `adb exec-out screencap -p` (PNG) | 10 | **333 ms** |
| `adb exec-out screencap --jpeg` | 10 | **156 ms** |
| `adb shell screencap -p /sdcard/x.png` + `adb pull` | 5 | **143 ms** |
| przepustowość kanału `exec-out`, 10 MB | 3 | **8–33 MB/s** |

Trzy wnioski, każdy przeciwny obiegowej opinii:

1. **Samo przechwycenie z SurfaceFlingera kosztuje ~150–230 ms i jest największym stałym składnikiem** — większym niż kodowanie PNG prostego ekranu. Tego nie da się obejść wyborem formatu.
2. **Surowy format przegrywa**, bo stały transfer 10,5 MB przy 8–33 MB/s to 300–1300 ms. Plansza Block Blasta to duże, płaskie obszary jednolitego koloru — czyli materiał idealny dla PNG. **Dla tej gry `-p` albo `--jpeg` powinno bić format surowy.**
3. **`--jpeg` był najszybszy** (156 ms). Nieudokumentowany w `usage`, ale obecny w `LONG_OPTIONS` w źródle. **[ŹRÓDŁO]**

> **Zastrzeżenie do liczb kodowania:** w pomiarze bufor ramki w trybie headless wracał **cały czarny**, więc czasy kodowania PNG/JPEG to dolne ograniczenie, nie wartość reprezentatywna dla prawdziwego ekranu gry. Czasy przechwycenia, transferu i round-tripu ADB są tym nietknięte. **Kolejność wariantów trzeba potwierdzić na prawdziwym ekranie Block Blasta** — to krok 4 w §9.2.

Niezależne potwierdzenie rzędu wielkości: Appium mierzy **~350 ms na zrzut na emulatorze z akceleracją**, spadające do ~150 ms przy zamianie na serwer MJPEG. **[POMIAR — strona trzecia]** — [appiumpro.com/editions/83](https://appiumpro.com/editions/83)

#### Optymalizacje

- **Zmniejszyć ekran**: `adb shell wm size 540x1212` ćwiartuje koszt przechwycenia **i** transferu naraz. Rasteryzacja programowa skaluje się najgorzej z rozdzielczością (§3), więc to uderza w dwa wąskie gardła. Do odczytu planszy 8×8 nie potrzeba 1080p. **Najtańsza dostępna optymalizacja.**
- **Strumień zamiast pojedynczych zrzutów** — jedyna droga powyżej ~5 ruchów/s (§4.4). `scrcpy` deklaruje *„low latency: 35~70ms"* i koduje przez `MediaCodec` na urządzeniu **[DOK]**; `minicap` podaje 10–20 FPS na słabym i 30–40 FPS na nowszym sprzęcie **[DOK]**. **Uwaga: README `minicap` wprost wyklucza emulatory** (*„excluding 3.x and emulators"*), więc dla nas zostaje droga w stylu scrcpy. Obie mają wadę dla pętli odpytującej: *„a new frame is produced only when the screen content changes"* — nieruchoma plansza nie generuje klatek. **[DOK]**

### 4.3 Ruch palcem

```bash
adb shell input swipe X1 Y1 X2 Y2 DURATION_MS
adb shell input tap X Y
```

Składnia jest stabilna od lat: `input swipe X1 Y1 X2 Y2 [czas_ms]`. Do umieszczenia klocka w Block Blaście potrzebne jest przeciągnięcie, więc `swipe` jest właściwym prymitywem; `tap` to `swipe` o zerowej długości.

#### Ważna korekta powszechnego mitu

W internecie powtarza się, że „`adb shell input` startuje JVM i kosztuje 200–300 ms". **To było prawdą, ale już nie jest — i przełom wypada dokładnie w zakresie API, który nas interesuje.**

Źródło: `frameworks/base/cmds/input/` w AOSP. **[ŹRÓDŁO]**

Android 11 (API 30) — `cmds/input/input`:
```sh
#!/system/bin/sh
export CLASSPATH=/system/framework/input.jar
exec app_process /system/bin com.android.commands.input.Input "$@"
```

Android 12 (API 31) i nowsze — `cmds/input/input.sh`:
```sh
#!/system/bin/sh
cmd input "$@"
```

Czyli **do API 30 każde wywołanie faktycznie odpalało nową maszynę wirtualną** (`app_process`). **Od API 31 `input` to cienki wrapper na `cmd`**, który rozmawia binderem z już działającym `InputManagerService` — bez startu JVM.

**Wniosek praktyczny:** wybieraj **API ≥ 31** (rekomendacja: 34). To nie jest kosmetyka wersji — to różnica rzędu wielkości w narzucie na ruch. **[SZAC]** co do skali, **[ŹRÓDŁO]** co do mechanizmu.

#### Co zostaje jako narzut

Nawet z `cmd input` każde `adb shell ...` to osobne połączenie z serwerem ADB i osobna usługa shell na urządzeniu. Dwie drogi, by to obejść **[SZAC]**:
1. **Trwała sesja shell** — jedno `adb shell` karmione komendami przez stdin, zamiast N wywołań `adb`. Eliminuje N handshake'ów. Tania, nie wymaga roota, mierzona w §9.2 krok 5b.
2. **`sendevent` / zapis do `/dev/input/eventX`** — omija warstwę `input` całkowicie, najniższa możliwa latencja. Ale wymaga uprawnień do węzłów `/dev/input`, czyli w praktyce roota — a **roota nie ma na obrazie z Play Store** (§7.2). Ta droga jest dostępna tylko na obrazie `default`/AOSP, który z kolei nie ma GMS. **Konflikt jest realny i trzeba go świadomie rozstrzygnąć.**

### 4.4 Ile ruchów na sekundę

**To jest oszacowanie [SZAC], nie pomiar.** Nie znalazłem żadnego wiarygodnego, pierwotnego źródła podającego zmierzoną latencję cyklu ADB na emulatorze w CI. Skrypt z §9.2 (kroki 4–7) istnieje po to, żeby zastąpić tę tabelę liczbami.

Budżet jednego cyklu na runnerze publicznym (4 vCPU, KVM, `-gpu swiftshader`):

| Składnik | Naiwnie | Zoptymalizowanie |
|---|---|---|
| zrzut ekranu | 150–400 ms (`screencap -p`, 1080p) | 40–100 ms (raw, 540p) |
| parsowanie planszy po stronie hosta | 10–50 ms | 10–50 ms |
| decyzja agenta (CPU, bez GPU) | zależy od algorytmu | zależy od algorytmu |
| `input swipe` | 60–150 ms (API ≥ 31) | 20–60 ms (trwała sesja shell) |
| **czekanie, aż animacja ucichnie** | **200–1500 ms** | **200–1500 ms** |
| **Razem** | **~0,5–2 s/ruch** | **~0,3–1,7 s/ruch** |

Czyli **rząd 1–3 ruchy/s naiwnie, może 5 ruchów/s po optymalizacji**.

> **Najważniejsza obserwacja tej sekcji:** wąskim gardłem prawdopodobnie **nie jest ADB ani emulator, tylko czas stabilizacji ekranu po ruchu** — animacja spadania i znikania linii, renderowana programowo bez GPU (§3). Optymalizowanie ADB przed zmierzeniem tego składnika byłoby dopracowywaniem niewłaściwej rzeczy. **Zmierz krok 7 z §9.2, zanim cokolwiek przyspieszysz.**

**Co to znaczy dla sesji:** przy 1,5 ruchu/s i jobie 5 h (§6.1) jedno ogniwo daje ~27 000 ruchów. Partia Block Blasta to rzędy setek–tysięcy ruchów, więc jedno ogniwo mieści wiele partii. **Do weryfikacji transferu to wystarcza z zapasem. Do treningu RL w prawdziwej grze — nie** (trening idzie na symulatorze, a oryginał służy do weryfikacji).

### 4.5 Budżet danych

Zrzut 1080×1920 PNG to ~1–2 MB. Przy 2 ruchach/s i sesji 5 h to ~36 000 zrzutów ≈ 40 GB. **Nie wolno zapisywać wszystkich zrzutów.** Zapisujemy sparsowany stan planszy (kilkadziesiąt bajtów) + zrzuty tylko przy anomaliach. **[SZAC]**

---

## 5. Trwałość stanu między jobami

### 5.1 Mechanizm: snapshoty AVD

Snapshot to *„a stored image of an Android Virtual Device (AVD) that preserves the entire state of the device at the time it was saved"* — ustawienia systemu, stan aplikacji, dane użytkownika. Quick Boot daje start *„up to 10 times faster than a cold boot"*. Każdy AVD ma **jeden** snapshot Quick Boot i **dowolnie wiele** nazwanych. **[DOK]** — [emulator-snapshots](https://developer.android.com/studio/run/emulator-snapshots)

Sterowanie z linii poleceń **[DOK]** — [emulator-commandline](https://developer.android.com/studio/run/emulator-commandline):

| Flaga | Działanie |
|---|---|
| `-snapshot NAME` | ładuje snapshot `NAME` przy starcie i **zapisuje go pod tą samą nazwą przy wyjściu**; jeśli nie istnieje — pełny boot i zapis |
| `-no-snapshot-load` | zimny start, ale stan zapisywany przy wyjściu |
| `-no-snapshot-save` | quick boot, **bez** zapisu przy wyjściu |
| `-no-snapshot` | całkowicie wyłącza Quick Boot (to jest w **domyślnych** `emulator-options` akcji!) |
| `-snapshot-list` | wypisuje dostępne snapshoty |

Snapshot **w trakcie działania**, bez zabijania emulatora **[DOK]** — [emulator-console](https://developer.android.com/studio/run/emulator-console):

```bash
adb emu avd snapshot save  bb_state
adb emu avd snapshot load  bb_state
adb emu avd snapshot list
```

`adb emu` to wariant „fire-and-forget" konsoli emulatora — **nie wymaga tokenu `auth`** (token z `~/.emulator_console_auth_token` jest potrzebny tylko przy wejściu przez `telnet`). To jest właściwa droga dla pętli zapisującej stan okresowo w trakcie długiego joba.

### 5.2 Dwa udokumentowane ograniczenia, które psują plan

**[DOK]**, dosłownie z [emulator-snapshots](https://developer.android.com/studio/run/emulator-snapshots):

> **(A)** *„Snapshots are valid for the system image, AVD configuration, and emulator features they are saved with. When you make a change in any of these areas, all snapshots of the affected AVD become invalid. Any update to the Android Emulator, system image, or AVD settings resets the AVD's saved state, so the next time you start the AVD, it must perform a cold boot."*

> **(B)** *„Snapshots are not reliable when software rendering is enabled. If snapshots don't work, click Edit this AVD in the Device Manager and change Graphics to either Hardware or Automatic."*

**Punkt (B) to bezpośredni konflikt z naszą sytuacją.** Runner GitHuba nie ma GPU, więc **musimy** używać renderowania programowego (§3) — czyli dokładnie trybu, w którym Google mówi, że snapshoty są zawodne. To nie jest „może zadziała": to udokumentowane ostrzeżenie, wprost dotyczące naszej konfiguracji.

Punkt (A) oznacza dodatkowo, że snapshot trzeba unieważnić przy **każdej** zmianie wersji emulatora lub obrazu systemu — a te aktualizują się same, bo `sdkmanager` ciągnie najnowsze. Klucz cache'u musi więc zawierać wersję emulatora i obrazu, inaczej pętla będzie cicho przywracać niesprawny snapshot.

**[SZAC]** Trzecie, nieudokumentowane ryzyko: snapshot QEMU zapisuje stan RAM i CPU. Runnery GitHuba nie gwarantują tego samego modelu CPU między jobami. Dokumentacja Google nie wymienia „host CPU" na liście (A) wprost, więc traktuję to jako hipotezę — ale to typowy tryb awarii migracji stanu QEMU i **trzeba go sprawdzić eksperymentalnie**.

**Obejście, które omija oba problemy [SZAC]:** nie przenoś snapshotu RAM. Przenoś **tylko dysk** — `userdata-qemu.img.qcow2` z katalogu `~/.android/avd/<nazwa>.avd/` — i pozwól na zimny boot. Zimny boot z KVM to 15 s (§2.1), więc kosztuje grosze, a dysk niesie zainstalowaną aplikację wraz z jej danymi (czyli postęp w grze), nie zależąc od stanu RAM ani modelu CPU. **To jest mocniejszy projekt niż snapshot RAM** i rekomendowałbym go jako domyślny.

### 5.3 Artefakty vs cache — werdykt

| Mechanizm | Limit | Czy wlicza się do puli storage | Wygasanie |
|---|---|---|---|
| `actions/cache` | **10 GB / repo** (podnoszalne przez admina) | **NIE** — *„Cache storage and custom image storage remain separate from this shared allowance"* | brak dostępu > 7 dni ⇒ usunięcie |
| `actions/upload-artifact` | brak udokumentowanego twardego limitu na pojedynczy artefakt; max **500 artefaktów na job** | TAK, wspólna pula z GitHub Packages (Free: 500 MB) | domyślnie 90 dni, konfigurowalne 1–90 |

**[DOK]** — [dependency caching](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching), [billing](https://docs.github.com/billing/managing-billing-for-github-actions/about-billing-for-github-actions), [upload-artifact README](https://github.com/actions/upload-artifact).

**Werdykt: stan AVD trzymamy w `actions/cache`, nie w artefaktach.** Powody:
1. Cache nie zjada puli storage'u; artefakty zjadają.
2. Eviction cache'u jest LRU — pętla, która czyta stan w każdym cyklu, sama utrzymuje wpis przy życiu.
3. 10 GB mieści AVD + obraz systemu.

**Pułapka zasięgu [DOK]:** *„Workflow runs cannot restore caches created for child branches or sibling branches."* Run może odczytać cache z własnej gałęzi lub z gałęzi domyślnej. Pętla musi więc żyć na `main` (albo konsekwentnie na jednej gałęzi), inaczej stan nie przechodzi.

**Pułapka niemutowalności [DOK]:** wpis cache o danym kluczu jest niemutowalny. Pętla zapisująca stan co cykl musi generować **nowe klucze** (np. `avd-state-${{ github.run_id }}`) i odczytywać przez `restore-keys: avd-state-`. Inaczej drugi zapis cicho nic nie zrobi.

---

## 6. Limity czasu i współbieżności

| Limit | Wartość | Źródło |
|---|---|---|
| **Czas jednego joba (GitHub-hosted)** | **6 godzin** — *„If a job reaches this limit, the job is terminated and fails."* | **[DOK]** [limits](https://docs.github.com/en/actions/reference/limits) |
| Czas jednego workflow run | 35 dni (łącznie z czekaniem i approvalami) | **[DOK]** |
| Macierz | max 256 jobów na run | **[DOK]** |
| **Równoległe joby, plan Free** | **20** (standard runners) | **[DOK]** |
| GITHUB_TOKEN API | 1 000 req/h na repo | **[DOK]** |

### 6.1 Sześć godzin a sesja weryfikacyjna

6 h to **twardy limit i job jest zabijany jako FAILED**, nie „zatrzymywany". Więc sesja weryfikacyjna musi:
- mieć własny `timeout-minutes` **poniżej** 360 (np. 320), żeby zdążyć zapisać stan i zakończyć się kontrolowanie jako *success*;
- zapisywać snapshot AVD + postęp **inkrementalnie w trakcie**, nie tylko na końcu — inaczej jedno przekroczenie limitu kasuje całą sesję.

Wzorzec: job jako **ogniwo łańcucha**, nie jako całość sesji. Każde ogniwo: `restore cache → boot ze snapshotu → graj N minut → zapisz snapshot → zapisz cache → wywołaj następne ogniwo`.

### 6.2 Łańcuch jobów — ukryta blokada

**To jest najważniejsza pułapka dla pętli.** Dokumentacja GitHuba **[DOK]** ([trigger a workflow](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)):

> *„When you use the repository's GITHUB_TOKEN to perform tasks, events triggered by the GITHUB_TOKEN will not create a new workflow run"* — z wyjątkiem `workflow_dispatch` i `repository_dispatch`.

Pułapka dla pętli, która tworzy issues i oczekuje, że utworzenie issue z etykietą odpali sesję: z domyślnym `GITHUB_TOKEN` **to nie zadziała** — issue utworzone przez workflow nie odpali workflow na `issues: opened`. Pętla zatrzyma się po pierwszym obrocie.

Obejścia **[DOK]**:
- **PAT** (fine-grained) w sekrecie repo używany do `gh issue create`, albo
- **token instalacyjny GitHub App**, albo
- jawne `workflow_dispatch` / `repository_dispatch` jako mechanizm łańcuchowania (te działają nawet z `GITHUB_TOKEN`).

Najprostsze i najbardziej odporne dla tej pętli: **`workflow_dispatch`/`repository_dispatch`**, bo nie wymaga żadnego dodatkowego sekretu ani rotacji tokenu.

### 6.3 Harmonogram wygasa

**[DOK]:** *„In a public repository, scheduled workflows are automatically disabled when no repository activity has occurred in 60 days."* Najkrótszy interwał `schedule` to 5 minut, a *„The `schedule` event can be delayed during periods of high loads… some queued jobs may be dropped."*

Dla pętli, która ma sama siebie podtrzymywać: **nie opieraj łańcucha wyłącznie na `schedule`**. Zdarzenia cron bywają gubione. `schedule` nadaje się tylko jako *watchdog* („czy pętla żyje? jeśli nie — wznów"), nie jako główny mechanizm napędowy.

---

## 7. Google Play, GMS i wykrywanie emulatora

### 7.1 Trzy rodziny obrazów

**[DOK]** — [managing-avds](https://developer.android.com/studio/run/managing-avds):

| Rodzina | `target` | Co zawiera |
|---|---|---|
| AOSP | `default` | brak aplikacji i usług Google |
| Google APIs | `google_apis` | Google Play **services**, bez sklepu |
| Google Play | `google_apis_playstore` | *„includes both the Google Play Store app and access to Google Play services"*; te urządzenia *„are CTS compliant"* |
| ATD (szybkie, okrojone) | `aosp_atd`, `google_atd` | Play Store **usunięty** |

Format pakietu: `system-images;android-<API>;<tag>;<abi>`, np. `system-images;android-34;google_apis_playstore;x86_64`.

**Pokrycie ABI dla Play Store [ŹRÓDŁO — manifesty repozytorium SDK Google, odczytane 2026-09-20]:**
- `x86`: **tylko API 24–30**. Powyżej API 30 **nie ma** obrazów x86 z Play Store.
- `x86_64`: API 28 → 37.x
- `arm64-v8a`: API 28 → 37.x
- `armeabi-v7a`: brak obrazów z Play Store.

> **Pułapka konfiguracyjna.** `android-emulator-runner` ma `arch` domyślnie ustawione na **`x86`**. W połączeniu z `target: google_apis_playstore` i API > 30 ta domyślka daje pakiet, który nie istnieje. **Zawsze podawaj `arch: x86_64` jawnie.** **[ŹRÓDŁO]** — `action.yml` + manifesty SDK.

### 7.2 Obrazy z Play Store nie dają roota — to jest twarde

**[DOK]**, dosłownie z [managing-avds](https://developer.android.com/studio/run/managing-avds):

> *„To ensure app security and a consistent experience with physical devices, system images with the Google Play Store included are signed with a release key, which means that you can't get elevated privileges (root) with these images."*

> *„If you require elevated privileges (root) to aid with app troubleshooting, you can use the Android Open Source Project (AOSP) system images that don't include Google apps or services. Then you can use the `adb root` and `adb unroot` commands…"*

Mechanizm potwierdzony w źródle AOSP (`packages/modules/adb/daemon/main.cpp`): `adb root` udaje się tylko przy `ro.debuggable=1`, a obrazy Play to buildy `user`. **[ŹRÓDŁO]**

**Konsekwencja dla automatyzacji [SZAC]:** `emulator -writable-system` + `adb remount` są **bezużyteczne** na obrazie Play, bo pierwszy krok udokumentowanej sekwencji (`adb root; adb disable-verity; adb reboot; adb root; adb remount`) po prostu odmawia. Czyli: **albo Play Store, albo root — nie oba naraz.**

Dla naszej pętli to na szczęście mało boli: `screencap`, `input`, `install` i `adb emu` **nie wymagają roota**. Root byłby potrzebny dopiero do „szybkiej ścieżki" wejścia przez `/dev/input/eventX` — patrz §4.3.

### 7.3 Czy zadziała APK ściągnięty z Play

Mechanicznie tak — i to jest udokumentowany scenariusz (`install-multiple`, §4.1). Ale:

**[DOK]** — [app-bundle](https://developer.android.com/guide/app-bundle):
> *„Partial installs of sideloaded apps—that is, apps that are not installed using the Google Play Store and are missing one or more required split APKs—fail on all Google-certified devices and devices running Android 10 (API level 29) or higher."*

Tryby awarii **[SZAC, oparte na udokumentowanym mechanizmie]**:
- Splity ściągnięte z fizycznego telefonu arm64 zawierają `split_config.arm64_v8a` → na emulatorze **x86_64** instalacja padnie albo apka wywali się przy ładowaniu natywnych bibliotek. Trzeba dopasować ABI **albo** użyć obrazu `arm64-v8a` (który na hoście x86 traci akcelerację KVM — patrz §2.1; to realny konflikt).
- Brak splitów gęstości/języka → `INSTALL_FAILED_MISSING_SPLIT` na API ≥ 29.
- Najczystsze wyjście: **universal APK**.

**GMS:** **[DOK]** — [Google Play services setup](https://developers.google.com/android/guides/setup): *„devices without the Google Play Store don't have Google Play services installed"*; dla emulatora wymagany jest *„an AVD that runs the Google APIs platform based on Android 7.0 (API level 24) or higher."*

**[SZAC]:** na obrazie `default`/AOSP aplikacja wołająca GMS przy starcie (reklamy, Firebase, Play Billing, licensing) najpewniej pokaże „Google Play services is missing" albo się wyłoży. `google_apis` naprawia prawie wszystko **poza** rzeczami wymagającymi uprawnienia z Play (licencja, IAP) — te potrzebują sklepu i zalogowanego konta.

**Werdykty Play Integrity dla sideloadu [DOK]** — [verdicts](https://developer.android.com/google/play/integrity/verdicts):
- `appLicensingVerdict: UNLICENSED` — *„This happens when, for example, the user sideloads your app or doesn't acquire it from Google Play."*
- `appRecognitionVerdict: UNRECOGNIZED_VERSION` — *„certificate or package name does not match Google Play records"*.

### 7.4 Czy gry wykrywają emulator

**[DOK]** — `deviceRecognitionVerdict`, [verdicts](https://developer.android.com/google/play/integrity/verdicts):

| Etykieta | Co znaczy | Emulator? |
|---|---|---|
| `MEETS_DEVICE_INTEGRITY` (domyślna) | *„genuine and certified Android device"*; na Androidzie 13+ **sprzętowy** dowód zablokowanego bootloadera | **Nie** |
| `MEETS_STRONG_INTEGRITY` (opt-in) | j.w. + świeże poprawki bezpieczeństwa | **Nie** |
| `MEETS_BASIC_INTEGRITY` (opt-in) | *„The device bootloader can be locked or unlocked… The device may not be certified"*; na 13+ wymaga tylko, by korzeń zaufania pochodził od Google | Być może **[SZAC]** |
| `MEETS_VIRTUAL_INTEGRITY` (warunkowa) | *„The app is running on an Android-powered emulator with Google Play services"* — ale **tylko** dla aplikacji wydawanych na Google Play Games for PC | Tak, lecz nie dla nas |
| **puste** | *„…or the app is not running on a physical device (such as an emulator that does not pass Google Play integrity checks)"* | Typowy przypadek |

**SafetyNet jest martwy [DOK]:** *„The SafetyNet Attestation API was deprecated in 2022 and fully turned down in January 2025."* Wszystko, co opisuje `ctsProfileMatch`/`basicIntegrity`, dotyczy wyłączonego API. — [deprecation timeline](https://developer.android.com/privacy-and-security/safetynet/deprecation-timeline)

**Sygnały niskopoziomowe [ŹRÓDŁO — AOSP `device/generic/goldfish`]:** `ro.hardware=goldfish|ranchu`, właściwości `ro.boot.qemu.*` i `vendor.qemu.*`, `ro.hardware.egl=emulation`, nazwy produktów `sdk_phone64_x86_64` / `sdk_gphone64_x86_64` w `Build.FINGERPRINT`. Klasyczne `ro.kernel.qemu=1` na nowoczesnych obrazach ranchu już nie występuje. Bez roota **nie da się** tych właściwości sfałszować na obrazie Play (§7.2).

**Google nigdzie nie stwierdza wprost, że emulator Android Studio przechodzi lub nie przechodzi `MEETS_BASIC_INTEGRITY`.** To brak dokumentacji, nie fakt w żadną stronę. **[DOK — nieobecność]**

Dwa fakty, które przemawiają za tym, że stockowy AVD z Play jest traktowany jako „normalne" urządzenie **[DOK]**: (1) *„Devices with this logo and device type Phone are CTS compliant"*; (2) Google traktuje komunikat „This device isn't Play Protect certified" na AVD jako **błąd do naprawienia**, nie jako zachowanie zamierzone — jest na liście znanych problemów emulatora z obejściem „zaktualizuj obraz systemu". — [emulator-troubleshooting](https://developer.android.com/studio/run/emulator-troubleshooting)

### 7.5 Block Blast konkretnie

Pakiet: `com.block.juggle`, wydawca HungryStudio.

**[DOK]** Gra jest oficjalnie dystrybuowana przez **Google Play Games on PC** — czyli przez własny emulator Androida Google'a: [play.google.com/pc-store](https://play.google.com/pc-store/games/details?id=com.block.juggle). Wymagania podane na tej stronie: Windows 10 v2004, 10 GB wolnego SSD, 4 fizyczne rdzenie, 8 GB RAM, włączona wirtualizacja sprzętowa.

**[DOK]** Listing w Play deklaruje grę offline: *„Offline games anywhere. No connection is required."* Jednocześnie: *„Contains ads"* i *„In-app purchases"*.

**[SZAC] — i to jest najważniejszy wniosek tej sekcji:** skoro wydawca sam wypuszcza grę do emulowanego środowiska Android, to **nie stosuje blanketowej blokady emulatorów**. To mocna przesłanka, że gra uruchomi się na AVD. **Nie wynika z tego**, że zaakceptuje akurat emulator Android Studio — Play Games for PC to odrębne, atestowane przez Google środowisko z własnym werdyktem `MEETS_VIRTUAL_INTEGRITY`, którego nasz AVD nie dostanie.

**Czego nie udało się ustalić z żadnego wiarygodnego źródła:** czy Block Blast wymusza jakikolwiek werdykt Play Integrity, czy wymaga GMS do samego startu, i czy blokuje emulatory inne niż Play Games for PC. **To jest pytanie empiryczne — do rozstrzygnięcia jednym runem, nie kolejnym czytaniem.**

---

## 8. Regulamin GitHuba — ryzyko łatwe do przeoczenia

[GitHub Terms for Additional Products and Features](https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features) zakazuje na GitHub-hosted runnerach **[DOK]**:

> *„any other activity unrelated to the production, testing, deployment, or publication of the software project associated with the repository"*

oraz

> *„any activity that places a burden on our servers, where that burden is disproportionate to the benefits provided to users"*

Konsekwencje przy złamaniu: *„termination of jobs, restrictions in your ability to use GitHub Actions, disabling of repositories… or in some cases, suspension or termination of your GitHub account."*

**Ocena [SZAC]:** trening agenta RL i testowanie mostu ADB **dla projektu, który jest w tym repo**, mieści się w „testing the software project". Ale pętla działająca 24/7 bez końca, zajmująca ciągle 20 równoległych darmowych jobów po 6 h, żeby bić rekord w komercyjnej grze, jest blisko granicy „disproportionate burden" i „unrelated activity". To ryzyko **tej samej klasy** co ryzyko bana konta w grze, które właściciel już świadomie przyjął — ale to go nie wymienia. Do decyzji właściciela, nie do rozstrzygnięcia w bilecie badawczym.

---

## 9. Szkic workflow (gotowy do uruchomienia)

Dwa pliki. Pierwszy to **jednorazowy eksperyment rozstrzygający** (§10) — powinien być uruchomiony **zanim** ktokolwiek napisze most produkcyjny. Drugi to szkielet ogniwa pętli.

### 9.1 `.github/workflows/emulator-probe.yml` — eksperyment rozstrzygający

Cel: odpowiedzieć na pytania z §10 jednym runem. Nic nie zakłada, wszystko mierzy.

```yaml
name: Emulator probe

on:
  workflow_dispatch:
    inputs:
      apk-url:
        description: "URL do APK (universal) lub pusty, by testować samym emulatorem"
        required: false
        default: ""
      api-level:
        default: "34"
      target:
        description: "default | google_apis | google_apis_playstore"
        default: "google_apis_playstore"

jobs:
  probe:
    runs-on: ubuntu-latest
    timeout-minutes: 45

    steps:
      - uses: actions/checkout@v4

      - name: Enable KVM group perms
        run: |
          echo 'KERNEL=="kvm", GROUP="kvm", MODE="0666", OPTIONS+="static_node=kvm"' \
            | sudo tee /etc/udev/rules.d/99-kvm4all.rules
          sudo udevadm control --reload-rules
          sudo udevadm trigger --name-match=kvm

      - name: Verify KVM is really on
        run: |
          set -eux
          ls -l /dev/kvm
          sudo apt-get update -qq && sudo apt-get install -y cpu-checker
          kvm-ok
          "$ANDROID_HOME/emulator/emulator" -accel-check || true
          nproc; free -g; df -h /

      - name: Cache AVD + system image
        uses: actions/cache@v4
        id: avd-cache
        with:
          # klucz MUSI zawierać wszystko, co unieważnia snapshot (patrz 5.2 A)
          key: avd-${{ inputs.api-level }}-${{ inputs.target }}-x86_64-v1
          path: |
            ~/.android/avd/*
            ~/.android/adb*
            /usr/local/lib/android/sdk/system-images/*

      - name: Create AVD (cold, first time only)
        if: steps.avd-cache.outputs.cache-hit != 'true'
        uses: reactivecircus/android-emulator-runner@v2
        with:
          api-level: ${{ inputs.api-level }}
          target: ${{ inputs.target }}
          arch: x86_64            # KONIECZNE: domyslka to x86, brak obrazow Play > API 30
          profile: pixel_6
          cores: 3                # runner publiczny ma 4 vCPU; zostaw jeden hostowi
          ram-size: 4096M
          force-avd-creation: false
          emulator-options: >-
            -no-window -gpu swiftshader -noaudio -no-boot-anim
            -camera-back none -camera-front none
          disable-animations: false
          script: echo "AVD created and snapshotted."

      - name: Probe
        uses: reactivecircus/android-emulator-runner@v2
        with:
          api-level: ${{ inputs.api-level }}
          target: ${{ inputs.target }}
          arch: x86_64
          profile: pixel_6
          cores: 3
          ram-size: 4096M
          force-avd-creation: false
          emulator-boot-timeout: 900
          emulator-options: >-
            -no-snapshot-save -no-window -gpu swiftshader -noaudio
            -no-boot-anim -camera-back none -camera-front none
          disable-animations: true
          script: bash tools/emulator_probe.sh "${{ inputs.apk-url }}"

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: probe-results
          path: |
            probe-out/
          retention-days: 7
          compression-level: 0
```

### 9.2 `tools/emulator_probe.sh` — mierzy, zamiast zakładać

```bash
#!/usr/bin/env bash
# Uruchamiany przez android-emulator-runner, gdy emulator jest juz wystartowany.
set -uo pipefail
APK_URL="${1:-}"
OUT=probe-out
mkdir -p "$OUT"
exec > >(tee "$OUT/probe.log") 2>&1

adb wait-for-device
adb shell 'while [ "$(getprop sys.boot_completed)" != "1" ]; do sleep 1; done'

echo "=== 1. Czy to na pewno emulator i czy ma KVM ==="
adb shell getprop ro.build.fingerprint
adb shell getprop ro.hardware
adb shell getprop ro.product.model
adb shell getprop ro.boot.qemu 2>/dev/null || true
adb shell getprop | grep -i -E 'qemu|goldfish|ranchu' > "$OUT/qemu-props.txt" || true

echo "=== 2. Czy jest Play Store / GMS ==="
adb shell pm list packages | grep -E 'com\.android\.vending|com\.google\.android\.gms' \
  || echo "BRAK GMS/Play Store"

echo "=== 3. Instalacja APK ==="
if [ -n "$APK_URL" ]; then
  curl -fsSL "$APK_URL" -o app.apk
  file app.apk
  if unzip -l app.apk | grep -q 'base\.apk'; then
    mkdir -p splits && unzip -q app.apk -d splits
    adb install-multiple -r -g splits/*.apk
  else
    adb install -r -g app.apk
  fi
  PKG=$(adb shell pm list packages -3 | sed 's/package://' | tr -d '\r' | head -1)
  echo "Zainstalowany pakiet: $PKG"
  adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1
  sleep 15
  # czy proces zyje po 15 s, czy sie wywalil?
  adb shell pidof "$PKG" && echo "APKA ZYJE" || echo "APKA PADLA / NIE WSTALA"
  adb logcat -d -t 2000 > "$OUT/logcat.txt"
fi

echo "=== 4. BENCHMARK: zrzut ekranu ==="
# 4a. PNG kodowany na urzadzeniu (naiwne podejscie)
S=$(date +%s%N)
for i in $(seq 1 20); do adb exec-out screencap -p > "$OUT/s.png"; done
E=$(date +%s%N)
echo "screencap -p        : $(( (E-S)/20000000 )) ms/zrzut"
ls -l "$OUT/s.png"

# 4b. raw, bez kodowania PNG na urzadzeniu
S=$(date +%s%N)
for i in $(seq 1 20); do adb exec-out screencap > "$OUT/s.raw"; done
E=$(date +%s%N)
echo "screencap (raw)     : $(( (E-S)/20000000 )) ms/zrzut"
ls -l "$OUT/s.raw"

echo "=== 5. BENCHMARK: wejscie ==="
# 5a. kazde wywolanie startuje osobny proces app_process na urzadzeniu
S=$(date +%s%N)
for i in $(seq 1 20); do adb shell input swipe 300 1200 700 800 100; done
E=$(date +%s%N)
echo "adb shell input swipe: $(( (E-S)/20000000 )) ms/ruch"

# 5b. jedna trwala sesja shell, 20 ruchow bez 20 handshake'ow ADB
S=$(date +%s%N)
printf 'for i in $(seq 1 20); do input swipe 300 1200 700 800 100; done\nexit\n' \
  | adb shell > /dev/null
E=$(date +%s%N)
echo "trwaly shell         : $(( (E-S)/20000000 )) ms/ruch"

echo "=== 6. Pelny cykl zrzut -> ruch -> zrzut ==="
S=$(date +%s%N)
for i in $(seq 1 10); do
  adb exec-out screencap > "$OUT/a.raw"
  adb shell input swipe 300 1200 700 800 60
  adb exec-out screencap > "$OUT/b.raw"
done
E=$(date +%s%N)
echo "pelny cykl           : $(( (E-S)/10000000 )) ms/cykl"

echo "=== 7. Ile trwa ustabilizowanie ekranu po ruchu (swiftshader!) ==="
adb shell input swipe 300 1200 700 800 60
for ms in 100 200 400 800 1600 3200; do
  adb exec-out screencap > "$OUT/st_$ms.raw"
  sleep "$(awk "BEGIN{print $ms/1000}")"
done
md5sum "$OUT"/st_*.raw

echo "=== 8. Snapshot: czy w ogole dziala przy renderowaniu programowym ==="
S=$(date +%s%N); adb emu avd snapshot save probe_snap; E=$(date +%s%N)
echo "snapshot save        : $(( (E-S)/1000000 )) ms"
adb emu avd snapshot list
S=$(date +%s%N); adb emu avd snapshot load probe_snap; E=$(date +%s%N)
echo "snapshot load        : $(( (E-S)/1000000 )) ms"
adb wait-for-device && adb shell getprop sys.boot_completed

echo "=== 9. Rozmiar stanu na dysku ==="
du -sh ~/.android/avd/*.avd/ 2>/dev/null
du -sh ~/.android/avd/*.avd/snapshots/ 2>/dev/null || true
ls -la ~/.android/avd/*.avd/ | sed -n '1,40p'
```

### 9.3 Ogniwo pętli (szkic, po zaliczeniu eksperymentu)

Kluczowe różnice wobec eksperymentu: `timeout-minutes` poniżej 360, zapis stanu **w trakcie**, łańcuchowanie przez `workflow_dispatch` (nie przez `issues`, §6.2).

```yaml
name: BB session link

on:
  workflow_dispatch:
    inputs:
      link-index: { default: "0" }

permissions:
  contents: write
  actions: write          # potrzebne, by odpalic kolejne ogniwo

jobs:
  guard:
    runs-on: ubuntu-latest
    outputs:
      go: ${{ steps.c.outputs.go }}
    steps:
      - id: c
        run: echo "go=${{ vars.AUTOPILOT }}" >> "$GITHUB_OUTPUT"

  play:
    needs: guard
    if: needs.guard.outputs.go == 'true'
    runs-on: ubuntu-latest
    timeout-minutes: 320          # < 360, zeby zdazyc posprzatac
    steps:
      - uses: actions/checkout@v4

      - name: Enable KVM group perms
        run: |
          echo 'KERNEL=="kvm", GROUP="kvm", MODE="0666", OPTIONS+="static_node=kvm"' \
            | sudo tee /etc/udev/rules.d/99-kvm4all.rules
          sudo udevadm control --reload-rules
          sudo udevadm trigger --name-match=kvm

      # ZAPIS: klucz unikalny per run, odczyt przez prefiks (cache jest niemutowalny)
      - uses: actions/cache/restore@v4
        with:
          path: |
            ~/.android/avd/*
            /usr/local/lib/android/sdk/system-images/*
          key: bb-state-
          restore-keys: bb-state-

      - uses: reactivecircus/android-emulator-runner@v2
        with:
          api-level: 34
          target: google_apis_playstore
          arch: x86_64
          cores: 3
          ram-size: 4096M
          force-avd-creation: false
          emulator-options: >-
            -no-window -gpu swiftshader -noaudio -no-boot-anim
            -camera-back none -camera-front none
          script: python -m bridge.session --minutes 280

      - uses: actions/cache/save@v4
        if: always()
        with:
          path: |
            ~/.android/avd/*
            /usr/local/lib/android/sdk/system-images/*
          key: bb-state-${{ github.run_id }}

      - name: Chain next link
        if: always() && vars.AUTOPILOT == 'true'
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          # workflow_dispatch DZIALA z GITHUB_TOKEN (wyjatek od reguly z 6.2)
          gh workflow run "BB session link" \
            -f link-index=$(( ${{ inputs.link-index }} + 1 ))
```

> **Uwaga do 9.3:** `gh workflow run` wywołane z `GITHUB_TOKEN` **zadziała**, bo `workflow_dispatch` jest jawnym wyjątkiem od reguły „GITHUB_TOKEN nie wyzwala workflow" **[DOK]**. To dokładnie ten powód, dla którego łańcuch pętli powinien iść przez dispatch, a nie przez tworzenie issues.

---

## 10. Co trzeba zmierzyć, zanim się na tym oprzemy

Rzeczy, których **nie da się rozstrzygnąć czytaniem dokumentacji** — wymagają jednego eksperymentalnego runa:

Rzeczy, których **nie da się rozstrzygnąć czytaniem dokumentacji**. Skrypt z §9.2 odpowiada na wszystkie w jednym runie — numery kroków skryptu w nawiasach.

| # | Pytanie | Dlaczego to blokuje | Krok w `emulator_probe.sh` |
|---|---|---|---|
| 1 | Czy Block Blast instaluje się i startuje na `google_apis_playstore;x86_64` API 34 bez logowania do Google | Bez tego nie ma mostu | 3 |
| 2 | Czy gra wykrywa emulator i odmawia działania | j.w. | 3 (logcat) |
| 3 | Realny czas cyklu zrzut→ruch→zrzut na 4-vCPU runnerze | §4.4 to oszacowanie, nie pomiar | 4, 5, 6 |
| 4 | Ile trwa ustabilizowanie ekranu po ruchu przy `-gpu swiftshader` | Determinuje realną przepustowość bardziej niż samo ADB | 7 |
| 5 | **Czy snapshoty w ogóle działają przy renderowaniu programowym** | Google mówi wprost, że są zawodne (§5.2 B) | 8 |
| 6 | Czy stan przeżywa przeniesienie na **inną maszynę** w innym jobie | Cała trwałość pętli o to stoi | wymaga 2 kolejnych runów |
| 7 | Rozmiar stanu AVD na dysku | Czy mieści się w 10 GB cache'u | 9 |

**Punkt 5 jest udokumentowanym ostrzeżeniem, nie hipotezą** — i to on najbardziej zagraża projektowi z §5. Jeśli snapshoty padną przy `swiftshader`, plan B (przenoszenie samego `userdata-qemu.img.qcow2` + zimny boot, §5.2) staje się planem A.

**Punkt 6 to najcichsze ryzyko.** Snapshot RAM QEMU zapisuje stan CPU; runnery GitHuba nie gwarantują identycznego modelu procesora między jobami. Dokumentacja Google nie wymienia „host CPU" wprost na liście unieważniającej, więc to **[SZAC]** — ale awaria byłaby niedeterministyczna i trudna do zdiagnozowania po fakcie. Sprawdzić przez dwa runy rozdzielone w czasie, nie przez dwa joby tego samego workflow.

---

## Źródła

**Dokumentacja GitHuba**
- [Actions limits](https://docs.github.com/en/actions/reference/limits)
- [GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
- [Billing for GitHub Actions](https://docs.github.com/billing/managing-billing-for-github-actions/about-billing-for-github-actions)
- [Dependency caching reference](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching)
- [Trigger a workflow](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)
- [Events that trigger workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
- [Terms for Additional Products and Features](https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features)
- [Changelog: hardware accelerated Android virtualization (2024-04-02)](https://github.blog/changelog/2024-04-02-github-actions-hardware-accelerated-android-virtualization-now-available/)

**Dokumentacja Androida**
- [adb](https://developer.android.com/tools/adb)
- [Emulator command-line options](https://developer.android.com/studio/run/emulator-commandline)
- [Emulator console](https://developer.android.com/studio/run/emulator-console)
- [Configure hardware acceleration](https://developer.android.com/studio/run/emulator-acceleration)
- [Emulator snapshots](https://developer.android.com/studio/run/emulator-snapshots)
- [Emulator troubleshooting / known issues](https://developer.android.com/studio/run/emulator-troubleshooting)
- [Create and manage AVDs](https://developer.android.com/studio/run/managing-avds)
- [Android App Bundle](https://developer.android.com/guide/app-bundle)
- [Play Integrity — verdicts](https://developer.android.com/google/play/integrity/verdicts)
- [SafetyNet deprecation timeline](https://developer.android.com/privacy-and-security/safetynet/deprecation-timeline)
- [Google Play services setup](https://developers.google.com/android/guides/setup)

**Źródła AOSP (kod)**
- [`cmds/input/input.sh` (main / API ≥ 31) — `cmd input "$@"`](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/cmds/input/input.sh)
- [`cmds/input/input` (android11-release / API 30) — `exec app_process …`](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android11-release/cmds/input/input)
- [`packages/modules/adb/daemon/main.cpp` — warunek `ro.debuggable` dla `adb root`](https://android.googlesource.com/platform/packages/modules/adb/+/refs/heads/main/daemon/main.cpp)
- [`device/generic/goldfish/init.ranchu.rc` — właściwości emulatora](https://android.googlesource.com/device/generic/goldfish/+/refs/heads/main/init.ranchu.rc)

**Kod źródłowy / repozytoria**
- [ReactiveCircus/android-emulator-runner – README](https://github.com/ReactiveCircus/android-emulator-runner/blob/main/README.md)
- [ReactiveCircus/android-emulator-runner – action.yml](https://github.com/ReactiveCircus/android-emulator-runner/blob/main/action.yml)
- [Issue #370 – pomiary czasu bootu z KVM](https://github.com/ReactiveCircus/android-emulator-runner/issues/370)
- [actions/runner-images – Ubuntu2404-Readme.md](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md)
