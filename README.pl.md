🇵🇱 Polski | 🇬🇧 [English](README.md)

# webnoveltoepub

Self-hosted aplikacja webowa, która zamienia web novele w pliki EPUB —
serwerowy odpowiednik wtyczki [WebToEpub](https://github.com/dteviot/WebToEpub).
Wklejasz adres powieści, przeglądasz wykryte rozdziały, pobierasz EPUB-a.

## Szybki start

```bash
git clone https://github.com/SpookyDoge/webnoveltoepub.git
cd webnoveltoepub
docker compose up --build
```

Wejdź na <http://localhost:8000> i wklej adres powieści. To wszystko — domyślny
obraz waży ~200 MB i nie wymaga żadnej konfiguracji.

Interaktywna dokumentacja API (gdybyś wolał to oskryptować) jest pod
<http://localhost:8000/docs>.

## Wspierane serwisy

| Serwis | Uwagi |
| ------ | ----- |
| [RoyalRoad](https://www.royalroad.com) | strona powieści, np. `/fiction/12345/slug` |
| [FreeWebNovel](https://freewebnovel.com) | strona powieści, np. `/novel/slug` |

Wklejaj link do **strony głównej powieści** (tej ze spisem rozdziałów), a nie do
pojedynczego rozdziału — choć adresy rozdziałów i tak są normalizowane
automatycznie.

Brakuje jakiegoś serwisu? Zajrzyj do sekcji [Rozwój projektu](#rozwój-projektu)
— jeden serwis to jeden plik.

## Konfiguracja

Wszystko jest opcjonalne. Skopiuj `.env.example` do `.env` albo ustaw zmienne
w swoim pliku compose.

| Zmienna | Domyślnie | Znaczenie |
| ------- | --------- | --------- |
| `WNE_PORT` | `8000` | port hosta dla interfejsu webowego |
| `WNE_DEFAULT_LANGUAGE` | `en` | język UI, gdy nie da się dopasować języka przeglądarki (`en`, `pl`) |
| `WNE_MAX_CHAPTERS` | `300` | twardy limit rozdziałów w jednym EPUB-ie |
| `WNE_REQUEST_DELAY` | `0.75` | odstęp w sekundach między żądaniami HTTP — nie zaniżaj bez potrzeby |
| `WNE_SAVE_TO_DISK` | `false` | zapisuj każdy wygenerowany EPUB także w `WNE_OUTPUT_DIR` |

Język interfejsu jest wykrywany z przeglądarki i można go przełączyć w każdej
chwili; dodanie kolejnego to wrzucenie pliku JSON do `web/locales/`. Pozostałe
(w większości wewnętrzne) zmienne opisuje `.env.example`.

## Uruchamianie na CasaOS i innych panelach self-hosted

Gotowe pliki compose leżą w katalogu [`deploy/`](deploy/):

| Plik | Co dostajesz |
| ---- | ------------ |
| [`deploy/docker-compose.casaos.yml`](deploy/docker-compose.casaos.yml) | wersja lekka (~200 MB) — **zacznij od niej** |
| [`deploy/docker-compose.casaos-playwright.yml`](deploy/docker-compose.casaos-playwright.yml) | z headless Chromium (~1.5 GB), dla serwisów renderujących rozdziały JavaScriptem |

Wybierz wersję lekką, chyba że jakiś parser wprost potrzebuje przeglądarki —
żaden z obecnie wspieranych serwisów jej nie wymaga.

**Instalacja:** skopiuj zawartość pliku → w CasaOS wejdź w **App Store →
Custom install** → wklej → **Install**.

Wygenerowane EPUB-y trafiają na hoście do `/DATA/AppData/webnoveltoepub/output`,
więc znajdziesz je w **File Managerze** CasaOS pod tą ścieżką (niezależnie od
pobierania ich wprost z przeglądarki).

> **Uwaga:** te pliki pobierają gotowy obraz z
> `ghcr.io/spookydoge/webnoveltoepub`. Dopóki nie jest opublikowany, zbuduj go
> i otaguj lokalnie — CasaOS nie buduje obrazów ze źródeł:
>
> ```bash
> docker build --target runtime -t ghcr.io/spookydoge/webnoveltoepub:latest .
> ```

W odróżnieniu od `docker-compose.yml` z roota repo, pliki te nie używają
profili ani interpolacji `${VAR:-default}` — panele zwykle uruchamiają wklejony
plik as-is i potrafią zignorować osobny `.env`.

## Rozwój projektu

Kontrybucje są mile widziane, zwłaszcza nowe parsery — każdy wspierany serwis to
pojedynczy, samorejestrujący się plik w `app/parsers/`, więc dodanie kolejnego
nie dotyka niczego poza nim. Testy odpalasz przez `pytest`, linter przez
`ruff check app tests`; testy działają w pełni offline, więc CI nie puka do
żadnego żywego serwisu.

Architektura, instrukcja dodawania parsera krok po kroku, konwencje i znane
pułapki są w **[CLAUDE.md](CLAUDE.md)** — przeczytaj przed pierwszym PR-em.

Kontrybucje wspierane przez AI (np. [Claude Code](https://claude.com/claude-code))
są mile widziane; `CLAUDE.md` jest jednocześnie briefem projektu, który możesz
podać agentowi. Sprawdź tylko, co wysyłasz, i upewnij się, że testy przechodzą.

## Odpowiedzialne używanie

Narzędzie pobiera strony, które mu wskażesz, pojedynczo i z konfigurowalnym
odstępem. Używaj go do treści, które wolno Ci pobierać — wiele web noveli
pozwala na czytanie offline na własny użytek, ale nie na redystrybucję.
Sprawdzaj regulaminy serwisów, nie zaniżaj `WNE_REQUEST_DELAY` i nie publikuj
ponownie tego, co wygenerujesz.

## Licencja

MIT — patrz [LICENSE](LICENSE).
