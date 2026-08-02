🇬🇧 English | 🇵🇱 [Polski](README.pl.md)

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

Open <http://localhost:8000> and paste a novel URL. That's it — the default
image is ~200 MB and needs no configuration.

Interactive API docs (if you'd rather script it) live at
<http://localhost:8000/docs>.

## Supported sites

| Site | Notes |
| ---- | ----- |
| [RoyalRoad](https://www.royalroad.com) | full novel page, e.g. `/fiction/12345/slug` |
| [FreeWebNovel](https://freewebnovel.com) | full novel page, e.g. `/novel/slug` |

Paste the link to the novel's **main page** (the one with the chapter list),
not to a single chapter — though chapter URLs are normalised automatically.

Want another site? See [Contributing](#contributing--development) — one site is
one file.

## Configuration

Everything is optional. Copy `.env.example` to `.env`, or set the variables in
your compose file.

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `WNE_PORT` | `8000` | host port for the web UI |
| `WNE_DEFAULT_LANGUAGE` | `en` | UI language when the browser's language can't be matched (`en`, `pl`) |
| `WNE_MAX_CHAPTERS` | `300` | hard cap on chapters per EPUB |
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
