**English** | [Polski](README.pl.md)

# webnoveltoepub

Self-hosted web app that turns web novels into EPUB files — a server-side
counterpart to the [WebToEpub](https://github.com/dteviot/WebToEpub) browser
extension. Paste a novel's URL, review the detected chapters, download an EPUB.

## Quick start

```bash
git clone https://github.com/SpookyDoge/webnoveltoepub.git
cd webnoveltoepub
docker compose up --build
```

Open <http://localhost:8000> and paste a novel URL. Chapters appear in the list
as they are discovered, and the conversion shows a live progress bar. Every
novel you convert is remembered in the **Library** tab, where a single click
pulls in whatever chapters have been published since — see
[Library](#library). That's it: the default image is ~200 MB and needs no
configuration.

Interactive API docs (if you'd rather script it) live at
<http://localhost:8000/docs>. The existing `/api/preview` and `/api/convert`
routes are unchanged; the UI uses their job-based variants (`/api/jobs/*`),
which stream progress over Server-Sent Events.

**No Docker?** There is a single-file Windows executable — download it, run it,
and the app opens in your browser. See [Windows (.exe, no Docker)](#windows-exe-no-docker).

## Supported sites

| Site | Notes |
| ---- | ----- |
| [RoyalRoad](https://www.royalroad.com) | full novel page, e.g. `/fiction/12345/slug` |
| [FreeWebNovel](https://freewebnovel.com) | full novel page, e.g. `/novel/slug` |

Paste the link to the novel's **main page** (the one with the chapter list),
not to a single chapter — though chapter URLs are normalised automatically.

Want another site? See [Contributing](#contributing--development) — one site is
one file.

## Library

The **Library** tab lists every novel you have converted: cover, chapter count
and when it was last refreshed.

- **Update** fetches only the chapters the stored EPUB does not have yet and
  appends them to the existing file. A novel you first grabbed at chapter 200
  costs 3 requests to bring up to 203, not 203.
- **Update all** walks the whole library, pausing between novels, and reports
  what was updated, what was already current and what failed. One unreachable
  site does not stop the rest.
- **Download** hands back the stored EPUB, so the library is useful without
  re-converting anything.
- **Remove** drops the entry and asks whether the EPUB file should go too.
- **Import from WebToEpub** reads a library exported from the browser
  extension — both the `.zip` export and the older `.json` one. The EPUBs are
  copied in and can be updated from then on like any other entry.

Updating needs the EPUB on disk, so it requires `WNE_SAVE_TO_DISK=true` (already
the default in the CasaOS files and in the Windows `.exe`). Without it the
library still records what you converted, but those entries are history only and
say so.

Imported entries carry one caveat: WebToEpub does not record how many chapters
a book holds, so the count is worked out from the EPUB itself and reported back
after the import. If it looks wrong, correct `chapter_count` in `library.json`
before the first update.

Chapter lists are assumed to grow at the end, which is how web novels work. If a
site reorders or removes chapters, the update says the list shifted rather than
quietly appending the wrong ones.

## Automatic updates

**Off by default** — nothing reaches out to the internet unless you ask it to.
Turn it on under **Settings**, where you can choose how often the whole library
is checked (hourly at the fastest, since web novels publish a few chapters a day
at most) and whether to run a check shortly after the app starts. The tab also
shows when the last automatic check ran, when the next one is due, and a log of
the last 20 runs.

Changes take effect immediately — no restart.

> Under Docker or CasaOS the app keeps running, so the schedule genuinely fires
> in the background. In the Windows `.exe` the app only lives while its window is
> open, so an interval measured in hours will rarely come round; the Settings tab
> says so too.

## Stopping a long conversion

Long conversions can be paused or stopped from the progress bar, and **nothing
already downloaded is thrown away**. Stopping finishes the chapter in flight,
then builds a valid — if shorter — EPUB from what arrived and records it in the
library with the right chapter count. A later **Update** picks up exactly where
it left off. Pause simply waits, and Resume carries on without re-downloading
anything. During **Update all**, Stop ends the whole run while keeping every
novel already refreshed.

## Configuration

Everything is optional. Copy `.env.example` to `.env`, or set the variables in
your compose file.

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `WNE_PORT` | `8000` | host port for the web UI |
| `WNE_DEFAULT_LANGUAGE` | `en` | UI language when the browser's language can't be matched (`en`, `pl`) |
| `WNE_MAX_CHAPTERS` | `0` | cap on chapters per EPUB; `0` means no limit |
| `WNE_REQUEST_DELAY` | `0.75` | seconds between HTTP requests — please keep this polite |
| `WNE_SAVE_TO_DISK` | `false` | also save every generated EPUB to `WNE_OUTPUT_DIR` |

The UI language is detected from your browser and can be switched at any time;
adding a new one means dropping a JSON file into `web/locales/`. The remaining
(mostly internal) variables are documented in `.env.example`.

## Running on CasaOS / other self-hosted panels

Ready-made compose files live in [`deploy/`](deploy/):

| File | What you get |
| ---- | ------------ |
| [`deploy/docker-compose.casaos.yml`](deploy/docker-compose.casaos.yml) | lightweight build (~200 MB) — **start here** |
| [`deploy/docker-compose.casaos-playwright.yml`](deploy/docker-compose.casaos-playwright.yml) | bundles headless Chromium (~1.5 GB) for sites that render chapters with JavaScript |

Pick the lightweight one unless a parser explicitly needs a browser; none of
the currently supported sites do.

**Install:** copy the contents of the file → in CasaOS go to **App Store →
Custom install** → paste → **Install**.

Generated EPUB files are written to `/DATA/AppData/webnoveltoepub/output` on the
host, so you can pick them up in the CasaOS **File Manager** at that path
(besides downloading them straight from the browser).

> **Note:** these files pull a prebuilt image from
> `ghcr.io/spookydoge/webnoveltoepub`, published automatically on every release
> tag. Once the first release is out this step is optional — until then, build
> and tag the image locally, because CasaOS itself cannot build from source:
>
> ```bash
> docker build --target runtime -t ghcr.io/spookydoge/webnoveltoepub:latest .
> ```

Unlike the repo's `docker-compose.yml`, these files use no compose profiles and
no `${VAR:-default}` interpolation — panels tend to run a pasted file as-is and
may ignore a separate `.env`.

## Windows (.exe, no Docker)

Grab the latest `webnoveltoepub-windows-v*.exe` from the
[Releases page](https://github.com/SpookyDoge/webnoveltoepub/releases/latest)
and double-click it. No Python, no Docker, no installer — a console window
opens, the app starts on a free local port (8000 by default) and your browser
opens at it. Closing the console window stops the app.

Generated EPUB files land in an `output` folder next to the `.exe`, on top of
the usual browser download.

> **SmartScreen warning on first run.** The executable is not code-signed — a
> certificate costs money every year, which is hard to justify for a
> non-commercial open source project. So Windows shows a blue "Windows
> protected your PC" screen about an unknown publisher. Click **More info** →
> **Run anyway**. This is expected; if you'd rather not, use the Docker version
> or build the `.exe` yourself:
>
> ```bash
> pip install -r requirements-build.txt
> pyinstaller build/pyinstaller.spec --noconfirm
> ```

**Limitation:** heavy mode (JavaScript rendering) is not available in this
build — Chromium weighs ~300 MB and bundling it would balloon a 20 MB download.
If a site ever needs it, the UI says so and points you at the Docker version.
None of the currently supported sites need it.

## Contributing / Development

Contributions are very welcome, especially new site parsers — each supported
site is a single self-registering file in `app/parsers/`, so adding one touches
nothing else. Run the test suite with `pytest` and the linter with
`ruff check app tests`; tests are fully offline, so nothing in CI hits a live
site.

Architecture, the step-by-step parser guide, conventions and known pitfalls are
in **[CLAUDE.md](CLAUDE.md)** — read that before your first PR.

AI-assisted contributions (e.g. [Claude Code](https://claude.com/claude-code))
are welcome; `CLAUDE.md` doubles as a project brief you can hand to an agent.
Please review what you submit and make sure it passes the tests.

## Responsible use

This tool fetches pages you point it at, one at a time, with a configurable
delay. Use it for content you're allowed to download — many web novels permit
personal offline reading but not redistribution. Check each site's terms of
service, keep `WNE_REQUEST_DELAY` sane, and don't republish what you generate.

## License

MIT — see [LICENSE](LICENSE).
