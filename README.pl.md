[English](README.md) | **Polski**

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

Wejdź na <http://localhost:8000> i wklej adres powieści. Rozdziały pojawiają się
na liście w miarę wykrywania, a konwersja pokazuje pasek postępu na żywo. Każda
przekonwertowana powieść zapisuje się w zakładce **Biblioteka**, gdzie jednym
kliknięciem dociągniesz rozdziały wydane od tamtego czasu — patrz
[Biblioteka](#biblioteka). To wszystko: domyślny obraz waży ~200 MB i nie
wymaga żadnej konfiguracji.

Interaktywna dokumentacja API (gdybyś wolał to oskryptować) jest pod
<http://localhost:8000/docs>. Dotychczasowe `/api/preview` i `/api/convert`
działają bez zmian; interfejs korzysta z wariantów zadaniowych
(`/api/jobs/*`) ze strumieniem postępu przez SSE.

**Nie chcesz Dockera?** Jest jednoplikowa wersja .exe dla Windows — pobierasz,
uruchamiasz i aplikacja otwiera się w przeglądarce. Szczegóły w sekcji
[Windows (.exe, bez Dockera)](#windows-exe-bez-dockera).

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

## Biblioteka

Zakładka **Biblioteka** pokazuje każdą przekonwertowaną powieść: okładkę, liczbę
rozdziałów i datę ostatniej aktualizacji.

- **Aktualizuj** pobiera wyłącznie rozdziały, których zapisany EPUB jeszcze nie
  ma, i dopisuje je do istniejącego pliku. Powieść pobrana do rozdziału 200
  kosztuje 3 żądania, żeby dobić do 203 — nie 203.
- **Aktualizuj wszystkie** przechodzi całą bibliotekę z przerwami między
  powieściami i raportuje, co zaktualizowano, co było już aktualne, a co
  padło. Jeden niedostępny serwis nie zatrzymuje reszty.
- **Usuń** kasuje wpis i pyta, czy skasować także plik EPUB.

Aktualizacja wymaga pliku na dysku, czyli `WNE_SAVE_TO_DISK=true` (domyślnie
włączone w plikach dla CasaOS i w wersji `.exe`). Bez tego biblioteka nadal
zapisuje, co konwertowałeś, ale takie wpisy są wyłącznie historią i wprost to
komunikują.

Zakładamy, że listy rozdziałów rosną na końcu — tak działają web novele. Jeśli
serwis przestawi albo usunie rozdziały, aktualizacja zgłosi, że lista się
przesunęła, zamiast po cichu dopisać nie te.

## Automatyczne sprawdzanie

**Domyślnie wyłączone** — nic nie łączy się z internetem, dopóki sam o to nie
poprosisz. Włączysz je w zakładce **Ustawienia**, gdzie wybierzesz, co ile
sprawdzać całą bibliotekę (najczęściej co godzinę, bo web novele publikują co
najwyżej kilka rozdziałów dziennie) oraz czy sprawdzać krótko po starcie
aplikacji. Ta sama zakładka pokazuje, kiedy było ostatnie sprawdzenie, kiedy
wypada następne, i log 20 ostatnich przebiegów.

Zmiany działają od razu — bez restartu.

> Pod Dockerem i CasaOS aplikacja chodzi non-stop, więc harmonogram naprawdę
> działa w tle. W wersji `.exe` dla Windows aplikacja żyje tylko wtedy, gdy jej
> okno jest otwarte, więc odstęp liczony w godzinach rzadko zdąży zadziałać —
> zakładka Ustawienia też o tym informuje.

## Przerywanie długiej konwersji

Długą konwersję można wstrzymać albo zatrzymać przy pasku postępu i **nic z
tego, co już pobrane, nie przepada**. Zatrzymanie kończy rozdział będący w
locie, po czym składa poprawny — choć krótszy — EPUB z tego, co dotarło, i
zapisuje go w bibliotece z właściwą liczbą rozdziałów. Późniejszy **Update**
podejmuje dokładnie od tego miejsca. Pauza po prostu czeka, a Wznów kontynuuje
bez pobierania czegokolwiek ponownie. Przy **Aktualizuj wszystkie** Stop kończy
całą serię, zachowując każdą już odświeżoną powieść.

## Konfiguracja

Wszystko jest opcjonalne. Skopiuj `.env.example` do `.env` albo ustaw zmienne
w swoim pliku compose.

| Zmienna | Domyślnie | Znaczenie |
| ------- | --------- | --------- |
| `WNE_PORT` | `8000` | port hosta dla interfejsu webowego |
| `WNE_DEFAULT_LANGUAGE` | `en` | język UI, gdy nie da się dopasować języka przeglądarki (`en`, `pl`) |
| `WNE_MAX_CHAPTERS` | `0` | limit rozdziałów w jednym EPUB-ie; `0` = bez limitu |
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
> `ghcr.io/spookydoge/webnoveltoepub`, publikowany automatycznie przy każdym
> tagu release'owym. Po wydaniu pierwszej wersji ten krok jest opcjonalny —
> do tego czasu zbuduj obraz i otaguj go lokalnie, bo CasaOS nie buduje
> obrazów ze źródeł:
>
> ```bash
> docker build --target runtime -t ghcr.io/spookydoge/webnoveltoepub:latest .
> ```

W odróżnieniu od `docker-compose.yml` z roota repo, pliki te nie używają
profili ani interpolacji `${VAR:-default}` — panele zwykle uruchamiają wklejony
plik as-is i potrafią zignorować osobny `.env`.

## Windows (.exe, bez Dockera)

Pobierz najnowszy `webnoveltoepub-windows-v*.exe` ze
[strony Releases](https://github.com/SpookyDoge/webnoveltoepub/releases/latest)
i kliknij dwukrotnie. Bez Pythona, bez Dockera, bez instalatora — otwiera się
okno konsoli, aplikacja startuje na wolnym porcie lokalnym (domyślnie 8000)
i przeglądarka otwiera się na tym adresie. Zamknięcie konsoli zatrzymuje
aplikację.

Wygenerowane EPUB-y trafiają do folderu `output` obok pliku `.exe`, niezależnie
od zwykłego pobrania w przeglądarce.

> **Ostrzeżenie SmartScreen przy pierwszym uruchomieniu.** Plik nie jest
> podpisany certyfikatem code-signing — certyfikat kosztuje co roku, co trudno
> uzasadnić przy niekomercyjnym projekcie open source. Windows pokaże więc
> niebieski ekran „Windows protected your PC" z informacją o nieznanym wydawcy.
> Kliknij **More info** → **Run anyway**. To normalne; jeśli wolisz tego
> uniknąć, użyj wersji Docker albo zbuduj `.exe` samodzielnie:
>
> ```bash
> pip install -r requirements-build.txt
> pyinstaller build/pyinstaller.spec --noconfirm
> ```

**Ograniczenie:** tryb ciężki (renderowanie JavaScriptu) jest w tej wersji
niedostępny — Chromium waży ~300 MB i dołączenie go rozdęłoby 20-megabajtowy
plik do pobrania. Gdyby jakiś serwis go wymagał, UI to komunikuje i odsyła do
wersji Docker. Żaden z obecnie wspieranych serwisów go nie potrzebuje.

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
