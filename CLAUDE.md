# CLAUDE.md — brief projektu

Szybki kontekst na start sesji. Szczegóły użytkowe są w [README.md](README.md)
(wersja PL: [README.pl.md](README.pl.md)); tutaj są decyzje, konwencje i pułapki.

## Czym to jest

`webnoveltoepub` — self-hosted aplikacja webowa konwertująca web novele na EPUB.
Serwerowy odpowiednik wtyczki WebToEpub. Open source, **MIT**, repo ma trafić na
GitHuba jako czytelny projekt do współtworzenia.

- Backend: Python + FastAPI · scraping: requests + BeautifulSoup (Playwright
  opcjonalnie) · EPUB: ebooklib · front: SPA bez frameworka i bez build stepu
- Uruchomienie: `docker compose up`. W planach dodatkowo **.exe na Windows**
  (PyInstaller) dla użytkowników, którzy nie chcą Dockera.
- UI dwujęzyczne (PL/EN) od początku.

**Cały kod źródłowy jest po angielsku** — komentarze, docstringi, komunikaty
logów i treści wyjątków. Ten plik pozostaje po polsku (brief dla właściciela
repo); po polsku zostają też `README.pl.md` i tłumaczenia w `web/locales/pl.json`
(projekt celuje w społeczność międzynarodową).

## Architektura `app/`

Warstwy są rozdzielone tak, żeby **parser wiedział tylko o HTML-u** — nie o HTTP,
nie o EPUB-ie. Dzięki temu dodanie serwisu nie dotyka niczego poza jednym plikiem.

| Moduł | Odpowiedzialność | Dlaczego osobno |
|---|---|---|
| `fetcher.py` | HTTP: throttling, retry, cache na czas zadania, Playwright | parsery nie powtarzają logiki sieciowej; podmiana na `FakeFetcher` daje testy offline |
| `sanitize.py` | allowlista tagów/atrybutów, komentarze, pułapki CSS | jedno miejsce na bezpieczeństwo XHTML — poprawka działa dla wszystkich parserów naraz |
| `parsers/` | wiedza o konkretnym serwisie | jedyna warstwa, która się psuje przy zmianie layoutu |
| `epub_builder.py` | składanie EPUB-a, nazwy plików | parsery nie znają ebooklib |
| `service.py` | orkiestracja URL → rozdziały → EPUB, obsługa błędów | trzyma politykę "padnięty rozdział nie kładzie książki" |
| `library.py` | trwały rejestr powieści (JSON) | zapis/odczyt oddzielony od orkiestracji; testowalny bez sieci i HTTP |
| `progress.py` | rejestr zadań + strumień SSE | jeden mechanizm progresu dla wszystkich długich operacji |
| `main.py` | FastAPI, walidacja URL, mapowanie wyjątków na HTTP, statyki | cienka warstwa; logika biznesowa jest testowalna bez HTTP |

Kod jest **synchroniczny**, `main.py` odpala go przez `asyncio.to_thread` — nie
blokuje pętli zdarzeń i pozwala działać synchronicznemu API Playwrighta.

## Dodanie parsera

1. **Najpierw rekonesans na żywym HTML-u.** Szukaj osadzonego JSON-a / meta
   tagów, zanim sięgniesz po selektory CSS — są znacznie stabilniejsze.
   (RoyalRoad: `window.chapters`. FreeWebNovel: `og:novel:*`.)
2. Nowy plik `app/parsers/<serwis>.py`, klasa dziedzicząca `BaseParser`.
   Rejestracja jest automatyczna (`__init_subclass__` + `discover()`) — **nie ma
   centralnej listy do aktualizacji**.
3. Atrybuty: `name`, `label`, `domains`, `requires_playwright`.
4. Metody: `get_metadata`, `get_chapter_list`, `get_chapter_content`.
   `get_cover_image` ma działającą implementację domyślną.
5. Referencja: [app/parsers/royalroad.py](app/parsers/royalroad.py) (osadzony
   JSON + fallback na HTML), [app/parsers/freewebnovel.py](app/parsers/freewebnovel.py)
   (paginacja listy rozdziałów).
6. Testy offline + wpis w tabeli w README.

Pomocniki z `BaseParser`: `self.soup(url)` (z cache'em), `select_first`,
`first_text`, `meta_content`, `normalize_url`.

Rzuć `ParserError` z komunikatem, z którym użytkownik coś zrobi — `main.py`
zamienia go na 422, a front pokazuje przetłumaczoną podpowiedź.

## Konwencje

- **Testy offline.** `FakeFetcher` z `tests/conftest.py` serwuje HTML ze słownika.
  Fixture'y są **syntetyczne** — odwzorowują strukturę serwisu, nie są zrzutem
  cudzej strony. Testy nie dotykają sieci. Żywy serwis sprawdzamy ręcznie,
  jednorazowo, przy dodawaniu parsera.
- Fixture ma odwzorowywać **prawdziwe zagnieżdżenie i śmieci** (reklamy, bloki
  „najnowsze rozdziały"), bo to na nich wykładają się selektory.
- `ruff check app tests` musi przechodzić; linia ≤ 100 znaków.
- i18n: żadnych stringów w HTML/JS — atrybut `data-i18n` + klucz w
  `web/locales/*.json`. Test w `tests/test_api.py` pilnuje, żeby pliki
  tłumaczeń miały identyczny zestaw kluczy.
- Nowy język UI = wrzucenie pliku JSON, zero zmian w kodzie.

## Docker — stan faktyczny

Dwa targety w jednym `Dockerfile`:
- `runtime` — lekki (~200 MB), domyślny, port 8000
- `playwright` — + Chromium (~1.5 GB), za profilem compose, port 8001

Zweryfikowane end-to-end: `docker compose up --build` → healthcheck zielony
w ~4 s → API, statyki i pełna konwersja działają z kontenera.

### Dystrybucja: `deploy/`

Osobna, uproszczona ścieżka dla paneli self-hosted (CasaOS): dwa samodzielne
pliki compose bez profili i bez interpolacji `${VAR:-default}`, z bind mountem
na `/DATA/AppData/webnoveltoepub/output` i etykietami `x-casaos`.
`docker-compose.yml` w roocie zostaje nietknięty — służy developmentowi.

Wersja lekka z `deploy/docker-compose.casaos.yml` przetestowana lokalnie:
bind mount, `user: "0:0"` i zapis EPUB-ów do `/app/output` działają
(nagłówek `X-Saved-Path` + pliki na wolumenie).

### Publikacja obrazu

`.github/workflows/publish-image.yml` publikuje oba warianty do GHCR pod
`ghcr.io/spookydoge/webnoveltoepub` — **nowy release wystarczy otagować**:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

Push taga `v*.*.*` uruchamia build obu targetów i wypycha cztery tagi:
`latest` + `<wersja>` oraz `playwright` + `playwright-<wersja>`. Ruchome
`latest`/`playwright` są tym, na co wskazują pliki z `deploy/`, więc każdy
release automatycznie aktualizuje instalacje CasaOS.

Szczegóły warte zapamiętania:
- Logowanie idzie przez wbudowany `GITHUB_TOKEN` (`permissions: packages:
  write`) — żadnego osobnego sekretu nie trzeba zakładać.
- Nazwa obrazu jest wpisana wprost, nie przez `${{ github.repository }}`:
  GHCR odrzuca wielkie litery, a właściciel repo to `SpookyDoge`.
- Przed pushem wariant runtime przechodzi smoke test (kontener musi wstać
  i odpowiedzieć na `/api/health`), żeby zepsute `latest` nie trafiło
  do instalacji CasaOS.
- `workflow_dispatch` z ręcznie podaną wersją pozwala opublikować pierwszy
  obraz albo powtórzyć nieudany release bez tworzenia nowego taga.

**Znane ograniczenie:** workflow buduje wyłącznie **amd64**, a pliki z `deploy/`
deklarują w `x-casaos.architectures` również `arm64`. Na Raspberry Pi i innych
ARM-ach obraz się nie uruchomi. Do zrobienia: buildx + QEMU (uwaga: emulowany
build wariantu playwright jest bardzo wolny) albo zawężenie deklaracji do amd64.

### Schemat `x-casaos` — pilnować typów

Autorytatywne źródło to `ComposeAppStoreInfo` w `openapi.yaml` z repo
CasaOS-AppManagement, plus działające przykłady z CasaOS-AppStore (Jellyfin,
N8n). Wymagane pola: `author`, `category`, `description`, `developer`, `icon`,
`screenshot_link`, `tagline`, `thumbnail`, `title`, `tips`, `index`, `port_map`.
Mapami lokalizacji są **tylko** `title`, `tagline`, `description` (oraz opisy
`envs`/`ports`/`volumes` w sekcji serwisu); reszta to zwykłe stringi.

### Zapis EPUB-ów na dysk

`WNE_SAVE_TO_DISK` (domyślnie `false`) + `WNE_OUTPUT_DIR` (domyślnie `output`,
czyli `/app/output` w kontenerze). Aplikacja jest z założenia bezstanowa —
zapis istnieje po to, żeby użytkownik panelu znalazł pliki w File Managerze.
Kopia nigdy nie nadpisuje istniejącego pliku (sufiks `-2`, `-3`), a błąd dysku
jest tylko logowany: konwersja ma się udać nawet gdy bind mount jest read-only.

## Biblioteka

`app/library.py` — trwały rejestr przekonwertowanych powieści, żeby dało się
dociągnąć nowe rozdziały bez pobierania całości od nowa.

**Format: jeden plik JSON, nie SQLite.** Danych jest tyle co nic (rekord na
powieść), zapis następuje raz na konwersję, a self-hoster może otworzyć plik
i poprawić ścieżkę edytorem tekstu. SQLite dałby współbieżność, której nie
potrzebujemy, kosztem czytelności. Zapis jest atomowy (`mkstemp` + `os.replace`
w tym samym katalogu) i serializowany blokadą — konwersje chodzą w wątkach
i dwie mogą skończyć naraz.

Domyślna lokalizacja to `<WNE_OUTPUT_DIR>/library.json`, celowo na tym samym
wolumenie co EPUB-y: na CasaOS to bind mount, więc biblioteka przeżywa
odtworzenie kontenera.

- `id` wpisu = `uuid5(source_url)`, ta sama pochodna co `dc:identifier`
  w EPUB-ie — plik i wpis zawsze da się skojarzyć.
- **Konwersja bez `WNE_SAVE_TO_DISK` też tworzy wpis**, ale bez pliku.
  Aktualizacja takiego wpisu zwraca status `no_file` i mówi o tym w UI,
  zamiast po cichu pobierać całą powieść od zera.
- Delta liczona jest jako `chapter_list[chapter_count:]`, czyli zakłada, że
  serwisy **dopisują** rozdziały na koniec. `last_chapter_url` służy za
  kontrolę: jeśli zapisany rozdział nie stoi już na swojej pozycji, wynik
  dostaje ostrzeżenie `chapter_list_shifted`.
- Dopisywanie do EPUB-a: `epub_builder.append_chapters()` czyta plik i dokłada
  rozdziały, więc **stare rozdziały nie są pobierane ponownie**.

**Pułapka ebooklib przy round-tripie** — dwie rzeczy, które się wywalają:
`read_epub()` zwraca spis treści jako obiekty `Link` z `uid=None`, co writer
NCX wstawia wprost do atrybutu XML (`TypeError: Argument must be bytes or
unicode, got 'NoneType'`), a nowym elementom nie nadaje `id`. Dlatego
`append_chapters` odbudowuje TOC z faktycznych dokumentów (odzyskując tytuły
z `Link`ów) i jawnie ustawia `uid` nowych rozdziałów. Nie upraszczać.

## Progres na żywo (SSE)

`app/progress.py` — **jeden** mechanizm dla wszystkich długich operacji:
skanowania listy, konwersji i aktualizacji biblioteki.

Dlaczego zadania + SSE, a nie strumieniowanie samej pracy: warstwa serwisowa
jest synchroniczna i chodzi w wątku roboczym, więc nie może `yield`ować do
odpowiedzi HTTP. Rejestr zadań rozdziela te dwa światy. SSE zamiast pollingu,
bo po stronie przeglądarki to trzy linijki `EventSource`, ruch i tak jest
jednokierunkowy, i nie ma interwału, którym trzeba by żonglować między
opóźnieniem a obciążeniem.

Eventy siedzą w **liście append-only** z `Condition`, nie w kolejce: klient,
który podłączy się z opóźnieniem, odtwarza historię od zera i płynnie
przechodzi w tryb na żywo, a ten sam event nie może dojść dwa razy.

### Jak dodać progres do nowej operacji

1. Przyjmij `emit: Emitter | None = None` w funkcji serwisowej i wołaj
   `emit("cos_sie_stalo", ...)` w ciekawych miejscach.
2. W trasie odpal `registry.run("nazwa", lambda emit: twoja_funkcja(..., emit))`
   i zwróć `{"job_id": job.id}`.
3. Front: `runJob(path, body, {typ_eventu: handler})` w `web/app.js`.

Kolejkowanie, strumień SSE, odtwarzanie historii i sprzątanie są już zrobione.

Uwagi:
- Nagłówek `X-Accel-Buffering: no` jest **konieczny** — nginx domyślnie buforuje
  odpowiedź i wstrzymałby wszystkie eventy do końca zadania, czyli dokładnie to,
  czemu ten mechanizm ma zapobiegać.
- Lista rozdziałów raportowana jest **partiami** (`chapters_found`), jedna na
  stronę źródła. Strona to jedno żądanie HTTP, więc jej rozdziały i tak stają
  się znane naraz; 4400 osobnych ramek nic by nie dało wizualnie.
- Parsery zgłaszają partie przez opcjonalny hook `on_chapters_found` +
  `report_chapters()`. Kontrakt parsera to nadal te same trzy metody, a parser,
  który nigdy nie zawoła `report_chapters`, działa bez zmian.
- Zadania żyją w pamięci (`JOB_TTL_SECONDS`), bo trzymają gotowy EPUB, który ma
  sens tylko dla przeglądarki, która o niego poprosiła.

## Scheduler automatycznych aktualizacji

`app/scheduler.py` — jedno zadanie asyncio startowane z `lifespan` FastAPI.

**Dlaczego gołe asyncio, nie APScheduler:** jest dokładnie jedno zadanie
okresowe, aplikacja i tak ma pętlę zdarzeń, a ciało pętli tylko oddaje robotę
do wątku. Zależność dołożyłaby wagi instalacji (i kolejną rzecz do wrzucenia
do `.exe`) w zamian za jakieś dwadzieścia linijek.

- Pętla budzi się co `TICK_SECONDS` (60 s), a nie śpi przez cały interwał —
  dzięki temu **zmiana ustawień działa bez restartu**. `PUT /api/settings`
  dodatkowo woła `scheduler.nudge()`, więc reakcja jest natychmiastowa.
- Sprawdzanie przy starcie (`check_on_startup`) odpala się po
  `STARTUP_DELAY_SECONDS` (30 s), niezależnie od interwału.
- **Reużywa `service.update_all`** — scheduler nie ma własnej kopii logiki
  aktualizacji.
- **Włączenie automatu nie odpala sprawdzenia od razu.** Zapisuje się wpis
  `baseline`, a pierwszy realny przebieg następuje interwał później — inaczej
  zaznaczenie checkboxa uderzałoby naraz we wszystkie serwisy z biblioteki.
- `_run_once` **nigdy nie rzuca**: nieudane sprawdzenie ląduje w logu
  przebiegów, a pętla żyje dalej.

**Pułapka:** `asyncio.Event` tworzy się dopiero w `start()`, nie w
`__init__`. Obiekt schedulera powstaje przy imporcie modułu — długo przed
istnieniem pętli zdarzeń — a Event wiąże się z pierwszą, która go awaituje.
Tworzenie go w konstruktorze wywalało wszystkie testy z `TestClient`
(„bound to a different event loop").

Ustawienia i log przebiegów leżą w `settings.json` **obok** `library.json`:
zapis checkboxa nie przepisuje wtedy wszystkich powieści, a uszkodzona
biblioteka nie kosztuje użytkownika konfiguracji (i odwrotnie).

## Pauza i zatrzymanie zadania

`JobControl` w `app/progress.py`; każdy `Job` ma własną instancję, a
`registry.run` podaje ją workerowi obok emitera.

**Stan sprawdzany jest MIĘDZY rozdziałami**, nigdy w środku żądania — rozdział
jest albo pobrany w całości, albo wcale, więc stop nie zostawia urwanego
tekstu. Ceną jest to, że przerwanie ląduje po rozdziale będącym w locie, i
dokładnie to obiecuje UI.

Stany: `running` → `paused` → `running` → `stopping` → `stopped` (albo `done`
/ `error`). Front dostaje je eventem `status`, a przyciski steruje przez
`POST /api/jobs/{id}/{pause,resume,stop}`.

Rzeczy, na które trzeba uważać:
- **Stop musi obudzić wstrzymanego workera** — `JobControl.stop()` ustawia
  `_resume`, inaczej Stop na spauzowanym zadaniu wisiałby w nieskończoność.
- **Po stopie liczba rozdziałów w bibliotece to pozycja ostatniego pobranego**
  (`chapter.index`), a nie liczba zapisanych. Po przerwaniu na 40. z 290
  wpisuje się 40, więc zwykły „Update" wznawia od 41 — czyli od tego, czego
  oczekuje `update_entry`.
- **Stop przed pierwszym rozdziałem** rzuca `StoppedBeforeStartError` →
  kod `stopped_empty`. Bez osobnego typu UI obwiniał parser o stronę, której
  nawet nie zdążył przeczytać.
- `update_all` sprawdza stan także **między powieściami**, więc Stop kończy
  całą serię — ale każda pozycja domknięta wcześniej jest już zapisana.

## Packaging `.exe` (Windows)

`build/pyinstaller.spec` pakuje `app/` + `web/` w jeden plik (~21 MB).
Punktem wejścia jest [app/desktop.py](app/desktop.py): szuka wolnego portu od
8000 w górę, startuje uvicorna na `127.0.0.1` i otwiera przeglądarkę.
Release buduje `.github/workflows/release-windows.yml` na `windows-latest`
i wiesza asset `webnoveltoepub-windows-v<wersja>.exe` przy releasie.

Zweryfikowane lokalnie na zbudowanym `.exe`: oba parsery wykryte, lokalizacje
i statyki serwowane z bundla, konwersja RoyalRoad → EPUB w folderze `output`
obok pliku, druga instancja przeskakuje na kolejny port.

Rzeczy, które trzeba pamiętać przy zmianach:
- **Parsery są importowane dynamicznie**, więc analiza statyczna PyInstallera
  ich nie widzi. `hiddenimports` w specu **globuje** `app/parsers/*.py`, więc
  nowy parser nie wymaga zmian w specu — ale nie wolno tego globa usunąć,
  bo `.exe` wstanie z zerem obsługiwanych serwisów.
- **Import w `desktop.py` musi być bezwzględny** (`from app.main import app`).
  PyInstaller uruchamia skrypt wejściowy jako `__main__`, więc import względny
  wywala się na `attempted relative import with no known parent package`.
- **`config.BASE_DIR` rozpoznaje `sys.frozen`** i wskazuje na `sys._MEIPASS`
  (tam ląduje `web/`), natomiast `desktop.bundle_dir()` celowo wskazuje obok
  `.exe` — `_MEIPASS` jest kasowany przy wyjściu i zabrałby EPUB-y użytkownika.
- **`.gitignore` ignoruje `build/`.** Reguła jest zawężona do `build/*` plus
  jawne `!build/pyinstaller.spec`, bo gita nie da się przekonać do odwrócenia
  wykluczenia katalogu dla pojedynczego pliku.
- `.exe` nie jest podpisany — SmartScreen ostrzega o nieznanym wydawcy.
  Certyfikat kosztuje rocznie; README opisuje obejście („More info" → „Run
  anyway").

**Playwright w `.exe`: świadomie nieobsługiwany.** Chromium (~300 MB) nie jest
pakowany. `PlaywrightUnavailableError` (podklasa `FetchError`) mapuje się na
422 z kodem `playwright_unavailable`, a front pokazuje przetłumaczoną
podpowiedź odsyłającą do wersji Docker. **TODO:** docelowo pobieranie Chromium
na żądanie z pytaniem w UI („~300 MB, jednorazowo — kontynuować?"). Dziś to
martwy kod, bo żaden parser nie ma `requires_playwright = True`.

**TODO — brak ikony.** W repo nie ma żadnej grafiki, więc `.exe` ma domyślną
ikonę PyInstallera. Spec podnosi `build/icon.ico`, jeśli plik się pojawi.
Ta sama luka dotyczy `deploy/*.yml`, które wskazują na nieistniejący
`web/icon.png`.

## Wspierane serwisy

| Serwis | Parser | Źródło listy rozdziałów | Playwright |
|---|---|---|---|
| RoyalRoad | `royalroad.py` | `window.chapters` (JSON) → fallback tabela | nie |
| FreeWebNovel | `freewebnovel.py` | `#idData`, paginacja `?page=N` (40/stronę) | nie |

## Roadmapa i ograniczenia

1. **Limit rozdziałów jest domyślnie wyłączony** (`WNE_MAX_CHAPTERS=0`).
   Konwersja nadal trzyma otwarty jeden request HTTP przez cały czas pobierania,
   ale progres leci przez SSE, więc nie wygląda to na zawieszenie. Przy bardzo
   długich powieściach (4400 rozdziałów × 0.75 s ≈ godzina) nadal realne jest
   ubicie żądania przez reverse proxy — docelowo warto oderwać pobieranie od
   requestu i zostawić samo SSE.
2. Obrazki wewnątrz rozdziałów są **wycinane** (okładki działają).
3. Cache rozdziałów między uruchomieniami.
4. Tłumaczenie treści rozdziałów — osobna, późniejsza faza.

## Fixed gotchas

Rzeczy, które **już raz po cichu zepsuły wynik**. Nie cofać.

- **`select_one("#a, .b")` nie wyraża priorytetu.** Lista selektorów CSS zwraca
  element wcześniejszy w *dokumencie*, więc przy zagnieżdżeniu wybiera szerszy
  wrapper razem z jego reklamami. Używać `BaseParser.select_first(...)`, które
  pyta selektorami po kolei.
- **Komentarze HTML trafiają do EPUB-a.** `decode()` wypisuje je dosłownie, a
  serwisy trzymają w nich wyłączony kod reklam (`<!--<script src="...ad.js">-->`).
  `sanitize.py` usuwa `Comment`/`CData`/`Doctype` — nie usuwać tego kroku.
- **`ł` nie ma dekompozycji NFKD.** Znikało z nazw plików EPUB
  (`zażółć` → `zazoc`). `epub_builder._TRANSLITERATION` mapuje ręcznie
  `ł/ø/đ/ß/æ/œ/þ` przed normalizacją.
- **Ten sam `ul.ul-list5` bywa w kilku blokach.** Na FreeWebNovel blok
  „najnowsze rozdziały" wstrzykiwał rozdział #290 na początek listy. Zawężać się
  najpierw do kontenera (`#idData`), potem szukać linków.
- **Statyki bez `Cache-Control` = użytkownik siedzi na starym froncie.**
  Bez tego nagłówka przeglądarka sama wymyśla okres świeżości i po
  aktualizacji potrafi dalej serwować stary `app.js` — wygląda to jak zepsute
  UI (raz już tak było: „przycisk biblioteki nie działa"). `RevalidatingStaticFiles`
  w `main.py` wymusza `no-cache`; ETagi i tak zwracają 304, gdy nic się nie zmieniło.
- **Konsola Git Bash na Windowsie pokazuje `?` zamiast UTF-8.** Zanim uznasz to
  za błąd kodowania, sprawdź surowe bajty w pliku — dwa razy okazało się
  artefaktem terminala.
- **`window.chapters` na RoyalRoad ≠ tabela HTML.** Numer rozdziału w URL-u
  FreeWebNovel (`/chapter-N`) to pozycja w kolejności, nie numer z tytułu.
- **`tips.custom` w `x-casaos` to zwykły string, nie mapa lokalizacji.** Mapa
  wywala import: `'Tips.Custom' expected type 'string'`. To jedyne pole, które
  wyłamuje się z konwencji sąsiednich `title`/`tagline`/`description`.
- **Klucze lokalizacji to `en_US`, nie `en_us`.** Casing ma znaczenie i nie
  powoduje błędu — CasaOS po prostu nie dopasowuje tłumaczenia i pokazuje
  puste nazwy/opisy.
- **`store_app_id` jest read-only.** Do identyfikacji aplikacji służy `id`
  w formacie odwróconej domeny (`io.github.<user>.<app>`).
- **Git Bash na Windowsie przerabia ścieżki uniksowe w `docker exec`.**
  `/app/output` staje się `C:/Program Files/Git/app/output`. Obejście:
  `MSYS_NO_PATHCONV=1` przed komendą.
