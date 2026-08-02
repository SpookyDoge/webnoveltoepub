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

## Wspierane serwisy

| Serwis | Parser | Źródło listy rozdziałów | Playwright |
|---|---|---|---|
| RoyalRoad | `royalroad.py` | `window.chapters` (JSON) → fallback tabela | nie |
| FreeWebNovel | `freewebnovel.py` | `#idData`, paginacja `?page=N` (40/stronę) | nie |

## Roadmapa i ograniczenia

1. **Kolejka zadań w tle — priorytet #1.** Konwersja trzyma otwarty jeden
   request HTTP przez cały czas pobierania (300 rozdziałów × 0.75 s ≈ kilka
   minut). To realny timeout na reverse proxy. Dotyczy też `/api/preview` przy
   powieściach z dużą liczbą stron listy (4400 rozdziałów = 111 żądań).
2. Obrazki wewnątrz rozdziałów są **wycinane** (okładki działają).
3. `.exe` na Windows przez PyInstaller.
4. Cache rozdziałów między uruchomieniami.
5. Tłumaczenie treści rozdziałów — osobna, późniejsza faza.

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
