# webnoveltoepub

Self-hosted web app that turns web novels into EPUB files — a server-side
counterpart to the [WebToEpub](https://github.com/dteviot/WebToEpub) browser
extension. Paste a novel's URL, review the detected chapters, download an EPUB.

*Aplikacja webowa do konwersji web noveli na pliki EPUB — odpowiednik wtyczki
WebToEpub, ale jako serwis self-hosted. UI dostępne po polsku i angielsku.*

- **Backend:** Python + FastAPI
- **Scraping:** `requests` + BeautifulSoup by default, Playwright as an opt-in
  "heavy mode" for JS-rendered sites
- **EPUB:** `ebooklib`
- **Frontend:** dependency-free SPA, no build step, i18n (PL/EN) out of the box
- **Deploy:** `docker compose up`

---

## Quick start

```bash
git clone https://github.com/SpookyDoge/webnoveltoepub.git
cd webnoveltoepub
docker compose up --build
```

Open <http://localhost:8000>. That's it — the lightweight image is ~200 MB and
needs no configuration.

### Heavy mode (Playwright / Chromium)

Only needed for sites that render their chapter list or content with JavaScript.
The image is ~1.5 GB, so it lives behind a compose profile:

```bash
docker compose --profile playwright up --build app-playwright   # http://localhost:8001
```

A parser opts into it with `requires_playwright = True`; setting
`WNE_PLAYWRIGHT_ENABLED=true` forces it for every parser.

### Local development (no Docker)

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
pytest
```

---

## Project layout

```
app/
  main.py            FastAPI app: /api/* routes + static frontend mount
  service.py         orchestration: URL -> parser -> chapters -> EPUB
  models.py          domain models (the parser contract) + API schemas
  fetcher.py         HTTP layer: throttling, retries, per-job cache, Playwright
  sanitize.py        HTML allowlist cleaning, CSS-hidden-trap removal
  epub_builder.py    ebooklib wrapper, filename slugify
  i18n.py            discovers web/locales/*.json, serves them to the frontend
  parsers/
    base.py          BaseParser — the interface every site parser implements
    __init__.py      auto-discovery registry (import = registration)
    royalroad.py     reference implementation
web/
  index.html  app.js  styles.css
  locales/en.json  locales/pl.json
tests/
Dockerfile  docker-compose.yml  .env.example
```

## API

| Method | Path                    | Purpose                                     |
| ------ | ----------------------- | ------------------------------------------- |
| `GET`  | `/api/health`           | health check (used by Docker `HEALTHCHECK`) |
| `GET`  | `/api/parsers`          | list of supported sites                     |
| `GET`  | `/api/languages`        | available UI locales                        |
| `GET`  | `/api/languages/{code}` | translation strings for one locale          |
| `POST` | `/api/preview`          | `{url}` → metadata + chapter list           |
| `POST` | `/api/convert`          | `{url, selected[], …}` → EPUB file          |

Interactive docs: <http://localhost:8000/docs>.

```bash
curl -X POST localhost:8000/api/convert \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://www.royalroad.com/fiction/21220/mother-of-learning","start":1,"end":5}' \
  -o novel.epub
```

## Configuration

Copy `.env.example` to `.env` (or set the variables in your compose file).

| Variable                 | Default  | Meaning                                       |
| ------------------------ | -------- | --------------------------------------------- |
| `WNE_PORT`               | `8000`   | host port                                     |
| `WNE_MAX_CHAPTERS`       | `300`    | hard cap on chapters per EPUB                 |
| `WNE_REQUEST_DELAY`      | `0.75`   | seconds between HTTP requests — **be polite** |
| `WNE_REQUEST_TIMEOUT`    | `30`     | per-request timeout (s)                       |
| `WNE_MAX_RETRIES`        | `3`      | retries per request                           |
| `WNE_PLAYWRIGHT_ENABLED` | `false`  | force heavy mode for all parsers              |
| `WNE_DEFAULT_LANGUAGE`   | `en`     | UI fallback language                          |
| `WNE_USER_AGENT`         | see file | User-Agent sent to sites                      |
| `WNE_LOG_LEVEL`          | `INFO`   | logging level                                 |

---

## Adding a new site parser

This is the part designed to be easy. **One site = one file in `app/parsers/`.**
There is no central registry to update: subclassing `BaseParser` registers the
class automatically, and `discover()` imports every module in the package at
startup.

### 1. Create `app/parsers/mysite.py`

```python
from urllib.parse import urljoin

from ..models import ChapterContent, ChapterRef, NovelMetadata
from ..sanitize import html_to_text, sanitize_html
from .base import BaseParser, ParserError


class MySiteParser(BaseParser):
    name = "mysite"                  # stable id, used in the API
    label = "My Site"                # shown in the UI
    domains = ("mysite.com",)        # subdomains match too
    requires_playwright = False      # True only if the site needs JS rendering

    def get_metadata(self, url: str) -> NovelMetadata:
        soup = self.soup(url)
        return NovelMetadata(
            title=self.first_text(soup, "h1.novel-title") or "Unknown title",
            author=self.first_text(soup, "span.author") or "Unknown",
            description=html_to_text(soup.select_one("div.summary"), limit=2000),
            language="en",
            cover_url=self.meta_content(soup, "og:image"),
            source_url=url,
        )

    def get_chapter_list(self, url: str) -> list[ChapterRef]:
        soup = self.soup(url)
        links = soup.select("ul.chapter-list a[href]")
        if not links:
            raise ParserError("No chapters found — is this the novel's main page?")
        return [
            ChapterRef(
                index=i,
                title=a.get_text(strip=True),
                url=urljoin(url, a["href"]),
            )
            for i, a in enumerate(links, start=1)
        ]

    def get_chapter_content(self, chapter: ChapterRef) -> ChapterContent:
        soup = self.soup(chapter.url)
        content = soup.select_one("div.chapter-body")
        if content is None:
            raise ParserError(f"No content at {chapter.url}")
        return ChapterContent(
            title=self.first_text(soup, "h1.chapter-title") or chapter.title,
            html=sanitize_html(content, base_url=chapter.url),
        )
```

That is the whole contract. `get_cover_image()` has a working default that
downloads `metadata.cover_url`; override it only if the cover needs special
handling.

### 2. Helpers you get for free

| Helper                                 | What it does                                                                                                             |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `self.soup(url)`                       | fetch + parse; **responses are cached per job**, so calling it in both `get_metadata` and `get_chapter_list` costs one request |
| `self.fetcher.get_text/get_bytes(url)` | raw fetch with throttling and retries                                                                                    |
| `self.first_text(soup, *selectors)`    | first non-empty match — great for layout fallbacks                                                                       |
| `self.meta_content(soup, *names)`      | reads `<meta property/name/itemprop>` (`og:title`, …)                                                                    |
| `sanitize_html(node, base_url=...)`    | tag/attribute allowlist, drops scripts, resolves relative links, removes CSS-hidden anti-scraping paragraphs              |
| `html_to_text(node, limit=...)`        | flattened text for descriptions                                                                                          |
| `normalize_url(url)`                   | override to turn a chapter URL into the novel's main URL                                                                  |

### 3. Write a test

Copy `tests/test_royalroad.py` — it uses the `fake_fetcher` fixture from
`tests/conftest.py`, which serves HTML from a dict, so tests are offline,
deterministic and fast. Keep fixtures **synthetic**: mimic the site's structure,
don't paste real page dumps.

```bash
pytest tests/test_mysite.py
```

### 4. Conventions worth following

- **Raise `ParserError`** with a message a user can act on when the layout does
  not match — the API turns it into a `422` and the UI shows a translated hint.
- **Build fallbacks:** prefer embedded JSON (often the most stable source) over
  HTML tables, and pass several selectors to `first_text`.
- **Never fabricate content.** A failed chapter is recorded as a warning and gets
  a placeholder page pointing at the source URL; the rest of the book still builds.
- **Index chapters from 1**, in reading order.
- Add the parser to the table below in your PR.

## Supported sites

| Site                                         | Parser                        | Heavy mode |
| -------------------------------------------- | ----------------------------- | ---------- |
| [RoyalRoad](https://www.royalroad.com)       | `app/parsers/royalroad.py`    | no         |
| [FreeWebNovel](https://freewebnovel.com)     | `app/parsers/freewebnovel.py` | no         |

## Roadmap

Phase 1 (this repo) covers the end-to-end pipeline. Next up:

- [ ] more parsers (ScribbleHub, Wuxiaworld, NovelUpdates, …)
- [ ] background jobs + progress bar (long novels currently hold one HTTP request open)
- [ ] images inside chapters (currently stripped; covers are supported)
- [ ] per-chapter caching between runs
- [ ] standalone Windows `.exe` (PyInstaller) for people who don't want Docker
- [ ] optional machine translation of chapter text as a separate phase
- [ ] more UI locales — just drop a `web/locales/<code>.json` file in, the
      backend and the language switcher pick it up automatically

## Adding a UI language

1. Copy `web/locales/en.json` to `web/locales/<code>.json` (e.g. `de.json`).
2. Translate the values; set `_meta.name` to the language's endonym.
3. Restart. It appears in the switcher — no code changes.

`tests/test_api.py` asserts that every locale file has the same key set, so a
half-finished translation fails CI rather than silently showing raw keys.

## Notes on responsible use

This tool fetches pages you point it at, one at a time, with a configurable
delay. Use it for content you are allowed to download — many web novels are
published under terms that permit personal offline reading but not
redistribution. Check each site's terms of service, keep `WNE_REQUEST_DELAY`
sane, and don't republish what you generate.

## License

MIT — see [LICENSE](LICENSE).
