/* webnoveltoepub - frontend with no framework and no build step. */

const STORAGE_KEY = "wne.language";
const FALLBACK_LANGUAGE = "en";

const state = {
  language: FALLBACK_LANGUAGE,
  strings: {},
  languages: [],
  parsers: [],
  preview: null,
  library: [],
  settings: null,
  jobId: null,
  // One long operation at a time. Two would double the request rate against
  // the same site (each job builds its own throttled Fetcher) and the single
  // Pause/Stop pair can only steer one of them.
  jobBusy: false,
};

// ---------------------------------------------------------------------------
// i18n
// ---------------------------------------------------------------------------

function t(key, params) {
  let value = state.strings[key];
  if (typeof value !== "string") return key;
  if (params) {
    for (const [name, replacement] of Object.entries(params)) {
      value = value.replaceAll(`{${name}}`, String(replacement));
    }
  }
  return value;
}

function detectLanguage(available) {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored && available.includes(stored)) return stored;

  for (const tag of navigator.languages || [navigator.language || ""]) {
    if (available.includes(tag)) return tag;
    const base = tag.split("-")[0];
    const match = available.find((code) => code.split("-")[0] === base);
    if (match) return match;
  }
  return available.includes(FALLBACK_LANGUAGE) ? FALLBACK_LANGUAGE : available[0];
}

async function setLanguage(code) {
  const response = await fetch(`/api/languages/${encodeURIComponent(code)}`);
  if (!response.ok) throw new Error(`Cannot load locale ${code}`);
  state.strings = await response.json();
  state.language = code;
  localStorage.setItem(STORAGE_KEY, code);
  document.documentElement.lang = code;
  applyTranslations();
}

function applyTranslations() {
  for (const element of document.querySelectorAll("[data-i18n]")) {
    element.textContent = t(element.dataset.i18n);
  }
  for (const element of document.querySelectorAll("[data-i18n-placeholder]")) {
    element.placeholder = t(element.dataset.i18nPlaceholder);
  }
  document.title = t("app.title");
  // Dynamically built fragments have to be redrawn after a language change.
  renderDynamic();
}

// ---------------------------------------------------------------------------
// Elements
// ---------------------------------------------------------------------------

const el = {
  form: document.getElementById("preview-form"),
  url: document.getElementById("url-input"),
  previewButton: document.getElementById("preview-button"),
  languageSelect: document.getElementById("language-select"),
  parserList: document.getElementById("parser-list"),
  errorBox: document.getElementById("error-box"),
  errorMessage: document.getElementById("error-message"),
  novelCard: document.getElementById("novel-card"),
  novelCover: document.getElementById("novel-cover"),
  novelTitle: document.getElementById("novel-title"),
  novelAuthor: document.getElementById("novel-author"),
  novelDescription: document.getElementById("novel-description"),
  novelSource: document.getElementById("novel-source"),
  novelTags: document.getElementById("novel-tags"),
  chaptersCard: document.getElementById("chapters-card"),
  chaptersCount: document.getElementById("chapters-count"),
  selectedCount: document.getElementById("selected-count"),
  limitWarning: document.getElementById("limit-warning"),
  chapterList: document.getElementById("chapter-list"),
  rangeStart: document.getElementById("range-start"),
  rangeEnd: document.getElementById("range-end"),
  includeCover: document.getElementById("include-cover"),
  bookLanguage: document.getElementById("book-language"),
  convertButton: document.getElementById("convert-button"),
  status: document.getElementById("status-message"),
  // The shared job panel - every long operation reports through these.
  jobCard: document.getElementById("job-card"),
  jobKind: document.getElementById("job-kind"),
  jobTitle: document.getElementById("job-title"),
  jobSeries: document.getElementById("job-series"),
  jobProgress: document.getElementById("job-progress"),
  jobBar: document.getElementById("job-bar"),
  jobCounter: document.getElementById("job-counter"),
  jobPause: document.getElementById("job-pause"),
  jobStop: document.getElementById("job-stop"),
  jobStopNote: document.getElementById("job-stop-note"),
  jobDownload: document.getElementById("job-download"),
  tabConvert: document.getElementById("tab-convert"),
  tabLibrary: document.getElementById("tab-library"),
  panelConvert: document.getElementById("panel-convert"),
  panelLibrary: document.getElementById("panel-library"),
  libraryList: document.getElementById("library-list"),
  libraryCount: document.getElementById("library-count"),
  libraryEmpty: document.getElementById("library-empty"),
  libraryStatus: document.getElementById("library-status"),
  updateAll: document.getElementById("update-all"),
  libraryRefresh: document.getElementById("library-refresh"),
  tabSettings: document.getElementById("tab-settings"),
  panelSettings: document.getElementById("panel-settings"),
  autoUpdateEnabled: document.getElementById("auto-update-enabled"),
  autoUpdateInterval: document.getElementById("auto-update-interval"),
  intervalRow: document.getElementById("interval-row"),
  checkOnStartup: document.getElementById("check-on-startup"),
  settingsSchedule: document.getElementById("settings-schedule"),
  settingsStatus: document.getElementById("settings-status"),
  saveSettings: document.getElementById("save-settings"),
  exeNote: document.getElementById("exe-note"),
  runLog: document.getElementById("run-log"),
  historyEmpty: document.getElementById("history-empty"),
  importButton: document.getElementById("import-button"),
  importFile: document.getElementById("import-file"),
};

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

function renderDynamic() {
  renderParserList();
  if (state.preview) {
    renderNovel(state.preview);
    updateSelectedCount();
  }
  if (state.library.length) renderLibrary();
  if (state.settings) renderSettings();
}

function renderParserList() {
  if (!state.parsers) return;
  el.parserList.replaceChildren(
    ...state.parsers.map((parser) => {
      const item = document.createElement("li");
      const heavy = parser.requires_playwright ? ` — ${t("supported.heavy")}` : "";
      item.textContent = `${parser.label} (${parser.domains.join(", ")})${heavy}`;
      return item;
    })
  );
}

function renderNovel(preview) {
  const { metadata, chapters, max_chapters: maxChapters } = preview;
  renderNovelInfo(metadata);

  el.chaptersCount.textContent = t("chapters.found", { count: chapters.length });
  if (maxChapters && chapters.length > maxChapters) {
    el.limitWarning.textContent = t("chapters.limit_warning", { max: maxChapters });
    el.limitWarning.hidden = false;
  } else {
    el.limitWarning.hidden = true;
  }

  el.bookLanguage.value = metadata.language || "";
  el.chaptersCard.hidden = false;
}

/** The novel card alone - shown as soon as metadata arrives, before the list. */
function renderNovelInfo(metadata) {
  el.novelTitle.textContent = metadata.title;
  el.novelAuthor.textContent = metadata.author;
  el.novelDescription.textContent = metadata.description || "";
  el.novelSource.textContent = metadata.source_url;
  el.novelSource.href = metadata.source_url;
  el.novelTags.textContent = metadata.tags.length
    ? `${t("novel.tags")}: ${metadata.tags.join(", ")}`
    : "";

  if (metadata.cover_url) {
    el.novelCover.src = metadata.cover_url;
    el.novelCover.alt = t("novel.cover_alt");
    el.novelCover.hidden = false;
  } else {
    el.novelCover.hidden = true;
  }
  el.novelCard.hidden = false;
}

/** Adds rows to the list as a scan discovers them, without redrawing it. */
function appendChapters(chapters) {
  el.chaptersCard.hidden = false;
  el.chapterList.append(
    ...chapters.map((chapter) => chapterRow(chapter, true))
  );
  updateSelectedCount();
}

function chapterRow(chapter, checked) {
  const li = document.createElement("li");
  const label = document.createElement("label");
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.value = String(chapter.index);
  checkbox.checked = checked;
  checkbox.addEventListener("change", updateSelectedCount);

  const num = document.createElement("span");
  num.className = "num";
  num.textContent = chapter.index;

  const title = document.createElement("span");
  title.textContent = chapter.title;

  label.append(checkbox, num, title);
  li.append(label);
  return li;
}

function renderChapters(chapters, maxChapters) {
  // By default tick only as many as the server would let through anyway.
  // 0 (or missing) means the server imposes no cap, so everything gets ticked.
  const cap = maxChapters > 0 ? maxChapters : Infinity;
  const items = chapters.map((chapter) => chapterRow(chapter, chapter.index <= cap));

  el.chapterList.replaceChildren(...items);
  el.rangeStart.value = 1;
  el.rangeStart.max = chapters.length;
  el.rangeEnd.value = Math.min(chapters.length, cap);
  el.rangeEnd.max = chapters.length;
  updateSelectedCount();
}

function checkboxes() {
  return [...el.chapterList.querySelectorAll("input[type=checkbox]")];
}

function selectedIndices() {
  return checkboxes().filter((box) => box.checked).map((box) => Number(box.value));
}

function updateSelectedCount() {
  el.selectedCount.textContent = t("chapters.selected", {
    count: selectedIndices().length,
  });
}

function showError(messageKey, detail) {
  el.errorMessage.textContent = detail ? `${t(messageKey)} (${detail})` : t(messageKey);
  el.errorBox.hidden = false;
  el.errorBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function clearError() {
  el.errorBox.hidden = true;
}

function setStatus(key, params) {
  if (!key) {
    el.status.hidden = true;
    return;
  }
  el.status.textContent = t(key, params);
  el.status.hidden = false;
}

/** Maps the API's `detail` onto a translation key. */
function errorKeyFromDetail(detail) {
  const known = [
    "invalid_url",
    "unsupported_site",
    "parser_error",
    // Must be checked before fetch_error: the backend sends a distinct code
    // for it, and it needs its own hint rather than "site unreachable".
    "playwright_unavailable",
    "stopped_empty",
    "import_error",
    "fetch_error",
  ];
  const match = known.find((key) => String(detail || "").startsWith(key));
  return match ? `error.${match}` : "error.unknown";
}

// ---------------------------------------------------------------------------
// Job panel - the one progress UI, shared by every long operation
// ---------------------------------------------------------------------------

/**
 * The progress panel on the Convert tab.
 *
 * Conversion, a single library update and a whole-library run all drive this
 * same object; they differ only in the context they pass to `begin` and in
 * which SSE events they forward to `setProgress`. Nothing else in the app
 * draws a progress bar.
 */
const jobPanel = {
  /**
   * Opens the panel for a new run.
   *
   * @param {string} kindKey  translation key naming the operation
   * @param {string} title    what is being worked on, if known yet
   * @param {boolean} series  true for "Update all", which changes what Stop
   *                          does - and the note under the buttons says so
   */
  begin({ kindKey, title = "", series = false }) {
    el.jobCard.hidden = false;
    el.jobKind.textContent = t(kindKey);
    this.setTitle(title);
    el.jobSeries.hidden = true;
    el.jobDownload.hidden = true;
    el.jobProgress.hidden = true;
    el.jobStopNote.textContent = t(series ? "job.stop_note_series" : "job.stop_note_single");
    el.jobStopNote.hidden = false;
    setStatus(null);
    el.jobCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  },

  setTitle(title) {
    el.jobTitle.textContent = title || "";
    el.jobTitle.hidden = !title;
  },

  /** "Updating 2 of 7: Mother of Learning" - only shown for a series. */
  setSeries(index, total, title) {
    el.jobSeries.textContent = t("job.series_position", { index, total, title });
    el.jobSeries.hidden = false;
    this.setTitle(title);
  },

  /**
   * Moves the bar. `unitKey` labels the counter, because in a series run the
   * bar switches between novels and chapters and bare numbers would be
   * ambiguous.
   */
  setProgress(value, total, unitKey = "job.counter_chapters") {
    el.jobProgress.hidden = false;
    el.jobBar.max = total || 1;
    el.jobBar.value = value;
    el.jobCounter.textContent = t(unitKey, { value, total });
  },

  /**
   * Hands the run to the Pause/Stop buttons.
   *
   * The row appears now rather than on the first progress event: the buttons
   * live in it, and a job still resolving the first request has no counts yet
   * but must still be stoppable. A `progress` with no value renders as an
   * indeterminate bar, which is exactly the state being reported.
   */
  attach(jobId) {
    el.jobProgress.hidden = false;
    el.jobBar.removeAttribute("value");
    el.jobCounter.textContent = "";
    attachControls(el.jobPause, el.jobStop, jobId);
  },

  /** Offers the finished EPUB, for runs that do not download one by themselves. */
  offerDownload(href, labelKey) {
    el.jobDownload.href = href;
    el.jobDownload.textContent = t(labelKey);
    el.jobDownload.hidden = false;
  },

  /** The run is over: controls go away, the status and result stay readable. */
  finish() {
    el.jobProgress.hidden = true;
    el.jobStopNote.hidden = true;
    releaseControls(el.jobPause, el.jobStop);
  },

  hide() {
    el.jobCard.hidden = true;
  },
};

/**
 * Claims the single job slot, or explains why it cannot be had.
 *
 * The busy message goes to the Convert tab together with the panel showing
 * what is already running - that is the answer to "why can't I?".
 */
function claimJob({ quiet = false } = {}) {
  if (state.jobBusy) {
    // The poller checks first and would only lose a race, so it stays quiet;
    // a user who clicked deserves to be told why nothing happened.
    if (!quiet) {
      selectTab("convert");
      showError("error.job_busy");
    }
    return false;
  }
  state.jobBusy = true;
  return true;
}

function releaseJob() {
  state.jobBusy = false;
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

/**
 * Runs a job and streams its progress.
 *
 * The one place that knows about job endpoints - preview, conversion and
 * library updates all go through here, so adding progress to a future
 * long-running operation is a matter of passing different handlers.
 *
 * @param {string} path        endpoint that starts the job
 * @param {object|null} body   JSON payload for it
 * @param {object} handlers    keyed by SSE event type; `onStart` is special
 *                             and receives the job id as soon as it is known,
 *                             which is what the Pause/Stop buttons steer.
 * @returns {Promise<string>}  the job id, once the job has finished
 */
function runJob(path, body, handlers = {}) {
  const { onStart, ...eventHandlers } = handlers;
  return fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === null ? null : JSON.stringify(body),
  })
    .then(async (response) => {
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw Object.assign(new Error("start_failed"), { detail: payload.detail });
      }
      return response.json();
    })
    .then(({ job_id: jobId }) => {
      if (onStart) onStart(jobId);
      return followJob(jobId, eventHandlers);
    });
}

/**
 * Streams an already-running job.
 *
 * Split out of `runJob` so a job this browser did not start - a scheduled
 * update, or any job still going after a page reload - can be picked up and
 * shown exactly like one we launched ourselves. The event history is
 * append-only and replayed from the start, so joining late loses nothing.
 */
function followJob(jobId, handlers = {}) {
  return new Promise((resolve, reject) => {
    const source = new EventSource(`/api/jobs/${jobId}/events`);

    for (const [type, handler] of Object.entries(handlers)) {
      source.addEventListener(type, (event) => handler(JSON.parse(event.data)));
    }

    source.addEventListener("done", () => {
      source.close();
      resolve(jobId);
    });
    source.addEventListener("error", (event) => {
      source.close();
      let detail = null;
      try {
        detail = JSON.parse(event.data).detail;
      } catch {
        // A transport-level EventSource error carries no data payload.
      }
      reject(Object.assign(new Error("job_failed"), { detail }));
    });
  });
}

function showJobError(error) {
  if (error && error.detail) {
    showError(errorKeyFromDetail(error.detail), null);
  } else {
    showError("error.network", error && error.message);
  }
}

async function loadPreview(event) {
  event.preventDefault();
  // A scan is a long scrape too, so it takes the same single job slot.
  if (!claimJob()) return;
  clearError();
  setStatus(null);
  // A finished run's panel would otherwise sit above the new novel.
  jobPanel.hide();
  el.previewButton.disabled = true;
  el.previewButton.textContent = t("form.loading");

  // Reset so a second scan does not append to the previous novel's list.
  state.preview = null;
  el.chapterList.replaceChildren();
  state.chapters = [];

  try {
    const jobId = await runJob(
      "/api/jobs/preview",
      { url: el.url.value.trim() },
      {
        metadata: ({ metadata }) => {
          state.previewMetadata = metadata;
          // The cap only becomes meaningful once we know how many chapters
          // there are, which is after the scan - so 0 (no warning) until then.
          renderNovel({ metadata, chapters: [], max_chapters: 0 });
        },
        // The whole point of the stream: chapters land in the list as each
        // page of the source's table of contents comes back.
        chapters_found: ({ chapters, total }) => {
          appendChapters(chapters);
          el.chaptersCount.textContent = t("chapters.found", { count: total });
        },
      }
    );

    const response = await fetch(`/api/jobs/${jobId}/result`);
    state.preview = await response.json();
    renderNovel(state.preview);
    renderChapters(state.preview.chapters, state.preview.max_chapters);
  } catch (error) {
    showJobError(error);
  } finally {
    releaseJob();
    el.previewButton.disabled = false;
    el.previewButton.textContent = t("form.preview");
  }
}

async function convert() {
  clearError();
  const selected = selectedIndices();
  if (!selected.length) {
    showError("error.no_selection");
    return;
  }
  if (!claimJob()) return;

  el.convertButton.disabled = true;
  jobPanel.begin({
    kindKey: "job.kind_convert",
    title: state.preview.metadata.title,
  });
  setStatus("convert.working");
  jobPanel.setProgress(0, selected.length);
  // A stopped run still produces a download, so "done" must not overwrite the
  // explanation that the book is deliberately short.
  let stopped = false;

  try {
    const jobId = await runJob(
      "/api/jobs/convert",
      {
        url: state.preview.metadata.source_url,
        selected,
        include_cover: el.includeCover.checked,
        language: el.bookLanguage.value.trim() || null,
      },
      {
        onStart: (jobId) => jobPanel.attach(jobId),
        chapter_downloaded: ({ index, total }) => jobPanel.setProgress(index, total),
        // Emitted when Stop lands: the book is built from what arrived.
        stopped: ({ downloaded }) => {
          stopped = true;
          setStatus(downloaded ? "job.stopped" : "job.stopped_empty");
        },
        stage: () => setStatus("convert.building"),
      }
    );

    const response = await fetch(`/api/jobs/${jobId}/result`);
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      showError(errorKeyFromDetail(payload.detail));
      setStatus(null);
      return;
    }

    const blob = await response.blob();
    triggerDownload(blob, fileNameFrom(response) || "novel.epub");
    if (!stopped) setStatus("convert.done");
  } catch (error) {
    showJobError(error);
    setStatus(null);
  } finally {
    releaseJob();
    el.convertButton.disabled = false;
    jobPanel.finish();
    loadLibrary();
  }
}

// ---------------------------------------------------------------------------
// Library
// ---------------------------------------------------------------------------

async function loadLibrary() {
  try {
    const response = await fetch("/api/library");
    state.library = await response.json();
    renderLibrary();
  } catch (error) {
    console.error(error);
  }
}

function renderLibrary() {
  const entries = state.library || [];
  el.libraryCount.textContent = t("library.count", { count: entries.length });
  el.libraryEmpty.hidden = entries.length > 0;
  el.updateAll.disabled = entries.length === 0;

  el.libraryList.replaceChildren(
    ...entries.map((entry) => {
      const li = document.createElement("li");
      li.className = "library-item";

      if (entry.cover_url) {
        const cover = document.createElement("img");
        cover.src = entry.cover_url;
        cover.alt = "";
        cover.loading = "lazy";
        li.append(cover);
      }

      const info = document.createElement("div");
      info.className = "library-info";

      const title = document.createElement("strong");
      title.textContent = entry.title;

      const meta = document.createElement("p");
      meta.className = "meta";
      meta.textContent = [
        entry.author,
        t("library.chapters", { count: entry.chapter_count }),
        t("library.updated", { date: formatDate(entry.updated_at) }),
      ].join(" · ");

      info.append(title, meta);

      // An entry with no file cannot be topped up - saying so beats an
      // Update button that always fails.
      if (!entry.file_path) {
        const warn = document.createElement("p");
        warn.className = "meta warn-text";
        warn.textContent = t("library.no_file");
        info.append(warn);
      }

      const actions = document.createElement("div");
      actions.className = "library-actions";

      const download = document.createElement("a");
      download.className = "button-link";
      download.textContent = t("library.download");
      if (entry.file_path) {
        download.href = `/api/library/${entry.id}/download`;
        // The server sets the file name; this just marks it as a download.
        download.setAttribute("download", "");
      } else {
        download.setAttribute("aria-disabled", "true");
      }

      const update = document.createElement("button");
      update.type = "button";
      update.textContent = t("library.update");
      update.disabled = !entry.file_path;
      update.addEventListener("click", () => updateEntry(entry, update));

      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = t("library.remove");
      remove.addEventListener("click", () => removeEntry(entry));

      actions.append(download, update, remove);
      li.append(info, actions);
      return li;
    })
  );
}

/**
 * Tops up one novel, reporting into the shared panel on the Convert tab.
 *
 * The user is moved there: it is where every long operation is shown, and
 * leaving them here would put Pause/Stop on a tab they are not looking at.
 */
async function updateEntry(entry, button) {
  if (!claimJob()) return;
  clearError();
  button.disabled = true;
  selectTab("convert");
  jobPanel.begin({ kindKey: "job.kind_update", title: entry.title });
  setStatus("library.updating", { title: entry.title });

  try {
    await runJob(`/api/library/${entry.id}/update`, null, {
      onStart: (jobId) => jobPanel.attach(jobId),
      // The title the server knows wins - the row may have been stale.
      entry_started: ({ title }) => jobPanel.setTitle(title),
      update_started: ({ new_chapters }) => jobPanel.setProgress(0, new_chapters),
      chapter_downloaded: ({ index, total }) => jobPanel.setProgress(index, total),
      entry_finished: (result) => {
        setStatus(libraryStatusKey(result), result);
        if (result.status === "updated" || result.status === "stopped") {
          jobPanel.offerDownload(
            `/api/library/${entry.id}/download`,
            "job.download_updated"
          );
        }
      },
    });
  } catch (error) {
    showJobError(error);
  } finally {
    releaseJob();
    button.disabled = false;
    jobPanel.finish();
    loadLibrary();
  }
}

/**
 * Walks the whole library, one novel at a time.
 *
 * The panel carries two levels of context: which novel of how many is being
 * handled, and the chapter progress inside it.
 */
/**
 * SSE handlers for a whole-library run.
 *
 * Shared by the manual button and by a run the scheduler started, because the
 * job is the same on both sides - only the label above the bar differs.
 */
function updateAllHandlers() {
  return {
    bulk_progress: ({ index, total, title }) => {
      jobPanel.setSeries(index, total, title);
      // Until this novel reports chapters, the bar tracks the series - a
      // novel that turns out to be up to date reports none at all.
      jobPanel.setProgress(index, total, "job.counter_novels");
    },
    update_started: ({ new_chapters }) => jobPanel.setProgress(0, new_chapters),
    chapter_downloaded: ({ index, total }) => jobPanel.setProgress(index, total),
  };
}

async function updateAll() {
  if (!claimJob()) return;
  clearError();
  el.updateAll.disabled = true;
  selectTab("convert");
  jobPanel.begin({ kindKey: "job.kind_update_all", series: true });
  setStatus("library.updating_all");

  try {
    await runJob("/api/library/update-all", null, {
      // Stop here ends the whole series; novels already refreshed stay saved.
      onStart: (jobId) => jobPanel.attach(jobId),
      ...updateAllHandlers(),
    });
    setStatus("library.update_all_done");
  } catch (error) {
    showJobError(error);
  } finally {
    releaseJob();
    el.updateAll.disabled = false;
    jobPanel.finish();
    loadLibrary();
  }
}

// ---------------------------------------------------------------------------
// Scheduled runs
// ---------------------------------------------------------------------------

/** How often to look for a job this browser did not start. */
const ACTIVE_POLL_MS = 5000;

/**
 * Looks for a running job nobody in this tab launched.
 *
 * A scheduled update would otherwise happen invisibly: there is no request to
 * hang a stream off, because the timer - not the browser - started it. Polling
 * one in-memory lookup every few seconds is cheaper than a second push
 * channel, and it doubles as recovery after a page reload.
 */
async function pollActiveJob() {
  if (state.jobBusy) return;
  try {
    const active = await fetch("/api/jobs/active").then((r) => r.json());
    // A manual job with nothing claimed here means another tab owns it.
    if (!active || active.trigger === "manual") return;
    await adoptScheduledJob(active);
  } catch {
    // Server asleep or offline; the next tick tries again.
  }
}

/** Shows a scheduler-started run as if the user had clicked Update all. */
async function adoptScheduledJob(active) {
  if (!claimJob({ quiet: true })) return;
  clearError();
  selectTab("convert");
  // The label is the only difference from a manual run: it answers "why is
  // this happening when I did not touch anything?".
  jobPanel.begin({ kindKey: "job.kind_auto_update", series: true });
  jobPanel.attach(active.job_id);
  setStatus("library.updating_all");

  try {
    await followJob(active.job_id, updateAllHandlers());
    setStatus("library.update_all_done");
  } catch (error) {
    showJobError(error);
  } finally {
    releaseJob();
    jobPanel.finish();
    loadLibrary();
    // The run log gained an entry; refresh it if Settings is on screen.
    loadSettings();
  }
}

/** Maps an update result onto the message that explains what happened. */
function libraryStatusKey(result) {
  if (result.status === "updated") return "library.updated_ok";
  if (result.status === "up_to_date") return "library.up_to_date";
  if (result.status === "no_file") return "library.no_file";
  return "library.update_failed";
}

/** Imports a library exported from the WebToEpub browser extension. */
async function importLibrary(file) {
  if (!file) return;
  clearError();
  el.importButton.disabled = true;
  setLibraryStatus("library.importing");

  try {
    const response = await fetch("/api/library/import", {
      method: "POST",
      // Sent as a raw body, which is what the endpoint expects.
      body: file,
    });
    const payload = await response.json();
    if (!response.ok) {
      showError(errorKeyFromDetail(payload.detail));
      setLibraryStatus("library.import_failed");
      return;
    }
    setLibraryStatus("library.imported", payload);
    loadLibrary();
  } catch (error) {
    showJobError(error);
    setLibraryStatus("library.import_failed");
  } finally {
    el.importButton.disabled = false;
    // Clear it so picking the same file twice fires a change event again.
    el.importFile.value = "";
  }
}

async function removeEntry(entry) {
  const alsoFile =
    entry.file_path && window.confirm(t("library.confirm_delete_file", { title: entry.title }));
  try {
    await fetch(`/api/library/${entry.id}?delete_file=${alsoFile ? "true" : "false"}`, {
      method: "DELETE",
    });
    loadLibrary();
  } catch (error) {
    showJobError(error);
  }
}

function setLibraryStatus(key, params) {
  el.libraryStatus.textContent = t(key, params);
  el.libraryStatus.hidden = false;
}

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString(state.language);
}

function selectTab(name) {
  const panels = {
    convert: [el.tabConvert, el.panelConvert],
    library: [el.tabLibrary, el.panelLibrary],
    settings: [el.tabSettings, el.panelSettings],
  };
  for (const [key, [tab, panel]] of Object.entries(panels)) {
    const active = key === name;
    panel.hidden = !active;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  }
  if (name === "library") loadLibrary();
  if (name === "settings") loadSettings();
}

function fileNameFrom(response) {
  const header = response.headers.get("Content-Disposition") || "";
  const utf8 = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8) return decodeURIComponent(utf8[1]);
  const plain = header.match(/filename="([^"]+)"/i);
  return plain ? plain[1] : null;
}

function triggerDownload(blob, fileName) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function applyRange() {
  const start = Number(el.rangeStart.value) || 1;
  const end = Number(el.rangeEnd.value) || Number.MAX_SAFE_INTEGER;
  for (const box of checkboxes()) {
    const index = Number(box.value);
    box.checked = index >= start && index <= end;
  }
  updateSelectedCount();
}

function setAll(checked) {
  for (const box of checkboxes()) box.checked = checked;
  updateSelectedCount();
}


// ---------------------------------------------------------------------------
// Job control (pause / resume / stop)
// ---------------------------------------------------------------------------

/** Wires a Pause/Stop pair to whichever job is currently running. */
function attachControls(pauseButton, stopButton, jobId) {
  state.jobId = jobId;
  let paused = false;

  pauseButton.disabled = false;
  stopButton.disabled = false;
  pauseButton.textContent = t("job.pause");

  pauseButton.onclick = async () => {
    paused = !paused;
    await fetch("/api/jobs/" + jobId + (paused ? "/pause" : "/resume"), { method: "POST" });
    pauseButton.textContent = t(paused ? "job.resume" : "job.pause");
    setStatus(paused ? "job.paused" : null);
  };

  stopButton.onclick = async () => {
    // Stop is final: disable both so a second click cannot confuse the state.
    pauseButton.disabled = true;
    stopButton.disabled = true;
    setStatus("job.stopping");
    await fetch("/api/jobs/" + jobId + "/stop", { method: "POST" });
  };
}

function releaseControls(pauseButton, stopButton) {
  state.jobId = null;
  pauseButton.onclick = null;
  stopButton.onclick = null;
  pauseButton.disabled = true;
  stopButton.disabled = true;
  pauseButton.textContent = t("job.pause");
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

async function loadSettings() {
  try {
    const response = await fetch("/api/settings");
    state.settings = await response.json();
    renderSettings();
  } catch (error) {
    console.error(error);
  }
}

function renderSettings() {
  const config = state.settings;
  if (!config) return;

  el.autoUpdateEnabled.checked = config.auto_update_enabled;
  el.autoUpdateInterval.value = config.auto_update_interval_hours;
  el.checkOnStartup.checked = config.check_on_startup;
  el.intervalRow.hidden = !config.auto_update_enabled;
  // Only shown in the .exe, where the process dies with its window.
  el.exeNote.hidden = config.runs_in_background;

  el.settingsSchedule.textContent = config.auto_update_enabled
    ? [
        t("settings.last_run", {
          date: config.last_run_at ? formatDate(config.last_run_at) : t("settings.never"),
        }),
        config.next_run_at ? t("settings.next_run", { date: formatDate(config.next_run_at) }) : "",
      ]
        .filter(Boolean)
        .join(" \u00b7 ")
    : t("settings.disabled");

  renderRunLog(config.recent_runs || []);
}

function renderRunLog(runs) {
  el.historyEmpty.hidden = runs.length > 0;
  el.runLog.replaceChildren(
    ...runs.map((run) => {
      const li = document.createElement("li");
      li.className = "library-item";

      const info = document.createElement("div");
      info.className = "library-info";

      const when = document.createElement("strong");
      when.textContent = formatDate(run.finished_at) + " (" + run.trigger + ")";

      const summary = document.createElement("p");
      summary.className = "meta";
      // A stopped or skipped pass is not a failure, and the log has to say so
      // rather than showing counts that look like a run that went nowhere.
      const outcome = t(`settings.run_status_${run.status || "ok"}`);
      summary.textContent =
        run.status === "skipped"
          ? outcome
          : `${outcome} · ${t("settings.run_summary", run)}`;

      info.append(when, summary);
      li.append(info);
      return li;
    })
  );
}

async function saveSettings() {
  el.saveSettings.disabled = true;
  try {
    const response = await fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        auto_update_enabled: el.autoUpdateEnabled.checked,
        // The server enforces the same floor; this keeps the UI honest.
        auto_update_interval_hours: Math.max(1, Number(el.autoUpdateInterval.value) || 24),
        check_on_startup: el.checkOnStartup.checked,
      }),
    });
    if (!response.ok) throw new Error("save_failed");
    state.settings = await response.json();
    renderSettings();
    setSettingsStatus("settings.saved");
  } catch (error) {
    console.error(error);
    setSettingsStatus("settings.save_failed");
  } finally {
    el.saveSettings.disabled = false;
  }
}

function setSettingsStatus(key) {
  el.settingsStatus.textContent = t(key);
  el.settingsStatus.hidden = false;
}

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------

async function init() {
  el.form.addEventListener("submit", loadPreview);
  el.convertButton.addEventListener("click", convert);
  el.tabConvert.addEventListener("click", () => selectTab("convert"));
  el.tabLibrary.addEventListener("click", () => selectTab("library"));
  el.updateAll.addEventListener("click", updateAll);
  el.libraryRefresh.addEventListener("click", loadLibrary);
  el.tabSettings.addEventListener("click", () => selectTab("settings"));
  el.saveSettings.addEventListener("click", saveSettings);
  el.importButton.addEventListener("click", () => el.importFile.click());
  el.importFile.addEventListener("change", (event) => importLibrary(event.target.files[0]));
  el.autoUpdateEnabled.addEventListener("change", () => {
    el.intervalRow.hidden = !el.autoUpdateEnabled.checked;
  });
  el.languageSelect.addEventListener("change", (event) => setLanguage(event.target.value));
  document.getElementById("select-all").addEventListener("click", () => setAll(true));
  document.getElementById("select-none").addEventListener("click", () => setAll(false));
  document.getElementById("apply-range").addEventListener("click", applyRange);

  const [languages, parsers] = await Promise.all([
    fetch("/api/languages").then((r) => r.json()),
    fetch("/api/parsers").then((r) => r.json()),
  ]);

  state.languages = languages;
  state.parsers = parsers;

  el.languageSelect.replaceChildren(
    ...languages.map(({ code, name }) => new Option(name, code))
  );

  const chosen = detectLanguage(languages.map((lang) => lang.code));
  el.languageSelect.value = chosen;
  await setLanguage(chosen);

  // Catches both a scheduled run starting and one still going after a reload.
  pollActiveJob();
  setInterval(pollActiveJob, ACTIVE_POLL_MS);
}

init().catch((error) => {
  console.error(error);
  document.body.insertAdjacentHTML(
    "afterbegin",
    `<p style="color:red;padding:1rem">Init failed: ${error.message}</p>`
  );
});
