[English](README.md) | **Polski**

# webnoveltoepub

Self-hosted aplikacja webowa, która zamienia web novele w pliki EPUB —
serwerowy odpowiednik wtyczki [WebToEpub](https://github.com/dteviot/WebToEpub).
Wklejasz adres powieści, przeglądasz wykryte rozdziały, pobierasz EPUB-a.

## Szybki start

Zapisz to jako `docker-compose.yml` i odpal `docker compose up -d`:

```yaml
services:
  webnoveltoepub:
    image: ghcr.io/spookydoge/webnoveltoepub:latest
    container_name: webnoveltoepub
    ports:
      - "8000:8000"
    environment:
      WNE_SAVE_TO_DISK: "true"
    volumes:
      - ./output:/app/output
    restart: unless-stopped
```

Potem wejdź na <http://localhost:8000> i wklej adres powieści. Rozdziały
pojawiają się w miarę wykrywania, a konwersja pokazuje pasek postępu na żywo.
Domyślny obraz waży ~200 MB i nie wymaga żadnej konfiguracji.

> Gotowy obraz publikuje się przy każdym tagu release'owym. Do czasu pierwszego
> wydania zbuduj go sam:
>
> ```bash
> git clone https://github.com/SpookyDoge/webnoveltoepub.git
> cd webnoveltoepub && docker compose up --build
> ```

Nie chcesz Dockera? Patrz [Windows (.exe)](#windows-exe). Interaktywna
dokumentacja API jest pod `/docs`.

## Wspierane serwisy

| Serwis | Co wkleić |
| ------ | --------- |
| [RoyalRoad](https://www.royalroad.com) | strona powieści, np. `/fiction/12345/slug` |
| [FreeWebNovel](https://freewebnovel.com) | strona powieści, np. `/novel/slug` |

Wklejaj stronę główną powieści (tę ze spisem rozdziałów); adresy rozdziałów są
normalizowane automatycznie. Brakuje serwisu? Jeden serwis to jeden plik — patrz
[Rozwój projektu](#rozwój-projektu).

## Biblioteka

Zakładka **Biblioteka** pokazuje każdą przekonwertowaną powieść.

- **Aktualizuj** pobiera wyłącznie rozdziały, których zapisany EPUB jeszcze nie
  ma, i dopisuje je. Powieść pobrana do rozdziału 200 kosztuje 3 żądania, żeby
  dobić do 203 — nie 203.
- **Aktualizuj wszystkie** przechodzi całą bibliotekę i raportuje, co się
  zmieniło. Jeden niedostępny serwis nie zatrzymuje reszty.
- **Pobierz** oddaje zapisany EPUB, **Usuń** kasuje wpis i pyta o plik.
- **Importuj z WebToEpub** wczytuje bibliotekę wyeksportowaną z rozszerzenia
  przeglądarkowego (`.zip` albo starszy `.json`). EPUB-y są kopiowane i od tej
  pory można je aktualizować.

Aktualizacje pokazują postęp w zakładce **Konwersja**, w tym samym panelu co
zwykła konwersja — aplikacja tam przełącza, pokazując, która powieść (a przy
„Aktualizuj wszystkie" — która pozycja przebiegu) jest właśnie obrabiana.

Aktualizacja wymaga pliku na dysku, czyli `WNE_SAVE_TO_DISK=true` (domyślnie
włączone w powyższym compose, w plikach dla CasaOS i w wersji `.exe`). Bez tego
biblioteka nadal zapisuje, co konwertowałeś, ale takie wpisy to sama historia.

Dwa zastrzeżenia: zakładamy, że listy rozdziałów rosną na końcu — jeśli serwis
je przestawi, aktualizacja to zgłosi, zamiast po cichu dopisać nie te; a
ponieważ WebToEpub nie zapisuje liczby rozdziałów, wpisy z importu dostają ją
wyliczoną z samego EPUB-a — popraw `chapter_count` w `library.json`, jeśli
wygląda źle.

## Automatyczne sprawdzanie

**Domyślnie wyłączone** — nic nie łączy się z internetem, dopóki sam o to nie
poprosisz. Włączysz je w zakładce **Ustawienia**, gdzie wybierzesz, co ile
sprawdzać bibliotekę (najczęściej co godzinę) i czy sprawdzać krótko po starcie.
Zakładka pokazuje ostatni i następny przebieg oraz log 20 ostatnich. Zmiany
działają od razu, bez restartu.

> Pod Dockerem aplikacja chodzi non-stop, więc harmonogram naprawdę działa.
> W wersji `.exe` aplikacja żyje tylko przy otwartym oknie, więc odstęp liczony
> w godzinach rzadko zdąży zadziałać.

## Pauza i zatrzymanie

Długi przebieg można wstrzymać albo zatrzymać przy pasku postępu i **nic z tego,
co już pobrane, nie przepada**. Zatrzymanie domyka rozdział w locie, po czym
składa poprawny — choć krótszy — EPUB i zapisuje go z właściwą liczbą
rozdziałów, więc późniejszy **Update** podejmuje dokładnie stamtąd. Przy
„Aktualizuj wszystkie" Stop kończy cały przebieg, zachowując każdą już
odświeżoną powieść.

## Konfiguracja

Wszystko opcjonalne. Skopiuj `.env.example` do `.env` albo ustaw zmienne w swoim
pliku compose.

| Zmienna | Domyślnie | Znaczenie |
| ------- | --------- | --------- |
| `WNE_PORT` | `8000` | port hosta dla interfejsu webowego |
| `WNE_DEFAULT_LANGUAGE` | `en` | język UI, gdy nie da się dopasować języka przeglądarki (`en`, `pl`) |
| `WNE_MAX_CHAPTERS` | `0` | limit rozdziałów w jednym EPUB-ie; `0` = bez limitu |
| `WNE_REQUEST_DELAY` | `0.75` | odstęp w sekundach między żądaniami HTTP — nie zaniżaj bez potrzeby |
| `WNE_SAVE_TO_DISK` | `false` | zapisuj każdy wygenerowany EPUB także w `WNE_OUTPUT_DIR` |

Język interfejsu jest wykrywany z przeglądarki i można go przełączyć w każdej
chwili; dodanie kolejnego to wrzucenie pliku JSON do `web/locales/`. Pozostałe
zmienne opisuje `.env.example`.

## CasaOS i inne panele self-hosted

Gotowe pliki leżą w [`deploy/`](deploy/): wersja lekka
[`docker-compose.casaos.yml`](deploy/docker-compose.casaos.yml) (**zacznij od
niej**) oraz [`docker-compose.casaos-playwright.yml`](deploy/docker-compose.casaos-playwright.yml)
z headless Chromium (~1.5 GB) dla serwisów renderujących rozdziały
JavaScriptem. Żaden z obecnie wspieranych serwisów go nie wymaga.

Skopiuj zawartość pliku → **App Store → Custom install** → wklej → **Install**.
EPUB-y trafiają do `/DATA/AppData/webnoveltoepub/output`, widocznego w File
Managerze CasaOS. W odróżnieniu od `docker-compose.yml` z roota, pliki te nie
używają profili ani interpolacji `${VAR:-default}` — panele uruchamiają wklejony
plik as-is.

## Windows (.exe)

Pobierz `webnoveltoepub-windows-v*.exe` ze
[strony Releases](https://github.com/SpookyDoge/webnoveltoepub/releases/latest)
i kliknij dwukrotnie. Bez Pythona, bez Dockera, bez instalatora — aplikacja
startuje na wolnym porcie lokalnym i otwiera przeglądarkę. EPUB-y trafiają do
folderu `output` obok pliku `.exe`.

> **Ostrzeżenie SmartScreen przy pierwszym uruchomieniu.** Plik nie jest
> podpisany certyfikatem (certyfikat kosztuje co roku, co trudno uzasadnić przy
> projekcie niekomercyjnym), więc Windows ostrzega o nieznanym wydawcy: **More
> info** → **Run anyway**. Żeby tego uniknąć, użyj wersji Docker albo zbuduj
> `.exe` samodzielnie:
>
> ```bash
> pip install -r requirements-build.txt
> pyinstaller build/pyinstaller.spec --noconfirm
> ```

**Ograniczenie:** renderowanie JavaScriptu jest w tej wersji niedostępne —
Chromium (~300 MB) rozdęłoby 20-megabajtowy plik. UI to komunikuje i odsyła do
wersji Docker, gdyby jakiś serwis tego wymagał.

## Rozwój projektu

Kontrybucje są mile widziane, zwłaszcza nowe parsery — każdy wspierany serwis to
pojedynczy, samorejestrujący się plik w `app/parsers/`, więc dodanie kolejnego
nie dotyka niczego poza nim. Odpal `pytest` i `ruff check app tests`; testy
działają w pełni offline, więc CI nie puka do żadnego żywego serwisu.

Architektura, instrukcja dodawania parsera krok po kroku, konwencje i znane
pułapki są w **[CLAUDE.md](CLAUDE.md)** — przeczytaj przed pierwszym PR-em.
Kontrybucje wspierane przez AI są mile widziane; `CLAUDE.md` jest jednocześnie
briefem, który możesz podać agentowi. Sprawdź tylko, co wysyłasz, i upewnij się,
że testy przechodzą.

## Odpowiedzialne używanie

Narzędzie pobiera strony, które mu wskażesz, pojedynczo i z konfigurowalnym
odstępem. Używaj go do treści, które wolno Ci pobierać — wiele web noveli
pozwala na czytanie offline na własny użytek, ale nie na redystrybucję.
Sprawdzaj regulaminy serwisów, nie zaniżaj `WNE_REQUEST_DELAY` i nie publikuj
ponownie tego, co wygenerujesz.

## Licencja

MIT — patrz [LICENSE](LICENSE).
