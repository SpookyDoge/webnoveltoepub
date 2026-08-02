**English** | [Polski](README.pl.md)

# webnoveltoepub

Self-hosted web app that turns web novels into EPUB files — a server-side
counterpart to the [WebToEpub](https://github.com/dteviot/WebToEpub) browser
extension. Paste a novel's URL, review the detected chapters, download an EPUB.

## Quick start

Save this as `docker-compose.yml` and run `docker compose up -d`:

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

Then open <http://localhost:8000> and paste a novel URL. Chapters appear as they
are discovered and the conversion shows a live progress bar. The default image
is ~200 MB and needs no configuration.

> The prebuilt image is published on every release tag. Until the first release
> is out, build it yourself:
>
> ```bash
> git clone https://github.com/SpookyDoge/webnoveltoepub.git
> cd webnoveltoepub && docker compose up --build
> ```

Prefer no Docker? See [Windows (.exe)](#windows-exe). Interactive API docs live
at `/docs`.

## Supported sites

| Site | Paste this |
| ---- | ---------- |
| [RoyalRoad](https://www.royalroad.com) | novel page, e.g. `/fiction/12345/slug` |
| [FreeWebNovel](https://freewebnovel.com) | novel page, e.g. `/novel/slug` |

Use the novel's main page (the one with the chapter list); chapter URLs are
normalised automatically. Missing a site? One site is one file — see
[Contributing](#contributing).

## Library

The **Library** tab lists every novel you have converted.

- **Update** fetches only the chapters your EPUB does not have yet and appends
  them. A novel grabbed at chapter 200 costs 3 requests to reach 203, not 203.
- **Update all** walks the whole library and reports what changed. One
  unreachable site does not stop the rest.
- **Download** hands back the stored EPUB; **Remove** drops the entry and asks
  about the file.
- **Import from WebToEpub** reads a library exported from the browser extension
  (`.zip` or the older `.json`). The EPUBs are copied in and become updatable.

Updates report progress on the **Convert** tab, in the same panel a normal
conversion uses — the app switches you there, showing which novel (and, during
"Update all", which position in the run) is being handled.

Updating needs the EPUB on disk, so `WNE_SAVE_TO_DISK=true` (already the default
in the compose above, the CasaOS files and the `.exe`). Without it the library
still records what you converted, but those entries are history only.

Two caveats: chapter lists are assumed to grow at the end, and an update says so
rather than guessing if a site reorders them; and because WebToEpub does not
record chapter counts, imported entries get a count worked out from the EPUB —
correct it in `library.json` if it looks wrong.

## Automatic updates

**Off by default** — nothing reaches the internet unless you ask. Turn it on
under **Settings**, choose how often the library is checked (hourly at the
fastest) and whether to check shortly after startup. The tab shows the last and
next run plus a log of the last 20. Changes apply immediately, no restart.

> Under Docker the app keeps running, so the schedule genuinely fires. The
> Windows `.exe` only lives while its window is open, so an interval measured in
> hours will rarely come round.

## Pausing and stopping

Long runs can be paused or stopped from the progress bar, and **nothing already
downloaded is lost**. Stop finishes the chapter in flight, then builds a valid —
if shorter — EPUB and records it with the right chapter count, so a later
**Update** resumes exactly there. During "Update all", Stop ends the whole run
while keeping every novel already refreshed.

## Configuration

All optional. Copy `.env.example` to `.env`, or set them in your compose file.

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `WNE_PORT` | `8000` | host port for the web UI |
| `WNE_DEFAULT_LANGUAGE` | `en` | UI language when the browser's cannot be matched (`en`, `pl`) |
| `WNE_MAX_CHAPTERS` | `0` | cap on chapters per EPUB; `0` means no limit |
| `WNE_REQUEST_DELAY` | `0.75` | seconds between HTTP requests — please keep this polite |
| `WNE_SAVE_TO_DISK` | `false` | also save every generated EPUB to `WNE_OUTPUT_DIR` |

The UI language is detected from your browser and switchable at any time; adding
one means dropping a JSON file into `web/locales/`. Remaining variables are
documented in `.env.example`.

## CasaOS and other self-hosted panels

Ready-made files live in [`deploy/`](deploy/): the lightweight
[`docker-compose.casaos.yml`](deploy/docker-compose.casaos.yml) (**start here**)
and [`docker-compose.casaos-playwright.yml`](deploy/docker-compose.casaos-playwright.yml),
which bundles headless Chromium (~1.5 GB) for sites that render chapters with
JavaScript. None of the currently supported sites need it.

Copy a file's contents → **App Store → Custom install** → paste → **Install**.
EPUBs land in `/DATA/AppData/webnoveltoepub/output`, visible in the CasaOS File
Manager. Unlike the repo's `docker-compose.yml`, these use no profiles and no
`${VAR:-default}` interpolation, since panels run a pasted file as-is.

## Windows (.exe)

Grab `webnoveltoepub-windows-v*.exe` from the
[Releases page](https://github.com/SpookyDoge/webnoveltoepub/releases/latest) and
double-click it. No Python, no Docker, no installer — the app starts on a free
local port and your browser opens at it. EPUBs land in an `output` folder next
to the `.exe`.

> **SmartScreen warning on first run.** The executable is not code-signed (a
> certificate costs money every year, hard to justify for a non-commercial
> project), so Windows warns about an unknown publisher: **More info** → **Run
> anyway**. To avoid it, use Docker or build it yourself:
>
> ```bash
> pip install -r requirements-build.txt
> pyinstaller build/pyinstaller.spec --noconfirm
> ```

**Limitation:** JavaScript rendering is not available in this build — Chromium
(~300 MB) would balloon a 20 MB download. The UI says so and points at Docker if
a site ever needs it.

## Contributing

Contributions are very welcome, especially new site parsers — each supported
site is a single self-registering file in `app/parsers/`, so adding one touches
nothing else. Run `pytest` and `ruff check app tests`; the tests are fully
offline, so nothing in CI hits a live site.

Architecture, the step-by-step parser guide, conventions and known pitfalls are
in **[CLAUDE.md](CLAUDE.md)** — read it before your first PR. AI-assisted
contributions are welcome; `CLAUDE.md` doubles as a brief you can hand to an
agent. Please review what you submit and make sure the tests pass.

## Responsible use

This tool fetches pages you point it at, one at a time, with a configurable
delay. Use it for content you are allowed to download — many web novels permit
personal offline reading but not redistribution. Check each site's terms, keep
`WNE_REQUEST_DELAY` sane, and don't republish what you generate.

## License

MIT — see [LICENSE](LICENSE).
