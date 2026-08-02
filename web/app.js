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
  convertProgress: document.getElementById("convert-progress"),
  convertBar: document.getElementById("convert-bar"),
  convertCounter: document.getElementById("convert-counter"),
  tabConvert: document.getElementById("tab-convert"),
  tabLibrary: document.getElementById("tab-library"),
  panelConvert: document.getElementById("panel-convert"),
  panelLibrary: document.getElementById("panel-library"),
  libraryList: document.getElementById("library-list"),
  libraryCount: document.getElementById("library-count"),
  libraryEmpty: document.getElementById("library-empty"),
  libraryStatus: document.getElementById("library-status"),
  libraryProgress: document.getElementById("library-progress"),
  libraryBar: document.getElementById("library-bar"),
  libraryCounter: document.getElementById("library-counter"),
  updateAll: document.getElementById("update-all"),
  libraryRefresh: document.getElementById("library-refresh"),
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
  const items = chapters.map((chapter) => chapterRow(chapter, chapter.index <= maxChapters));

  el.chapterList.replaceChildren(...items);
  el.rangeStart.value = 1;
  el.rangeStart.max = chapters.length;
  el.rangeEnd.value = Math.min(chapters.length, maxChapters);
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

function setStatus(key) {
  if (!key) {
    el.status.hidden = true;
    return;
  }
  el.status.textContent = t(key);
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
    "fetch_error",
  ];
  const match = known.find((key) => String(detail || "").startsWith(key));
  return match ? `error.${match}` : "error.unknown";
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
 * @param {object} handlers    keyed by SSE event type
 * @returns {Promise<string>}  the job id, once the job has finished
 */
function runJob(path, body, handlers = {}) {
  return new Promise((resolve, reject) => {
    fetch(path, {
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
      })
      .catch(reject);
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
  clearError();
  setStatus(null);
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
          renderNovel({ metadata, chapters: [], max_chapters: state.maxChapters });
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

  el.convertButton.disabled = true;
  setStatus("convert.working");
  setProgress(el.convertProgress, el.convertBar, el.convertCounter, 0, selected.length);

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
        chapter_downloaded: ({ index, total }) => {
          setProgress(el.convertProgress, el.convertBar, el.convertCounter, index, total);
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
    setStatus("convert.done");
  } catch (error) {
    showJobError(error);
    setStatus(null);
  } finally {
    el.convertButton.disabled = false;
    el.convertProgress.hidden = true;
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

      const update = document.createElement("button");
      update.type = "button";
      update.textContent = t("library.update");
      update.disabled = !entry.file_path;
      update.addEventListener("click", () => updateEntry(entry, update));

      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = t("library.remove");
      remove.addEventListener("click", () => removeEntry(entry));

      actions.append(update, remove);
      li.append(info, actions);
      return li;
    })
  );
}

async function updateEntry(entry, button) {
  clearError();
  button.disabled = true;
  setLibraryStatus("library.updating", { title: entry.title });

  try {
    await runJob(`/api/library/${entry.id}/update`, null, {
      update_started: ({ new_chapters }) => {
        setProgress(el.libraryProgress, el.libraryBar, el.libraryCounter, 0, new_chapters);
      },
      chapter_downloaded: ({ index, total }) => {
        setProgress(el.libraryProgress, el.libraryBar, el.libraryCounter, index, total);
      },
      entry_finished: (result) => setLibraryStatus(libraryStatusKey(result), result),
    });
  } catch (error) {
    showJobError(error);
  } finally {
    button.disabled = false;
    el.libraryProgress.hidden = true;
    loadLibrary();
  }
}

async function updateAll() {
  clearError();
  el.updateAll.disabled = true;
  setLibraryStatus("library.updating_all");

  let done = 0;
  try {
    await runJob("/api/library/update-all", null, {
      bulk_progress: ({ index, total, title }) => {
        done = index;
        setProgress(el.libraryProgress, el.libraryBar, el.libraryCounter, index, total);
        setLibraryStatus("library.updating", { title });
      },
      chapter_downloaded: ({ index, total }) => {
        el.libraryCounter.textContent = `${done} · ${index}/${total}`;
      },
    });
    setLibraryStatus("library.update_all_done");
  } catch (error) {
    showJobError(error);
  } finally {
    el.updateAll.disabled = false;
    el.libraryProgress.hidden = true;
    loadLibrary();
  }
}

/** Maps an update result onto the message that explains what happened. */
function libraryStatusKey(result) {
  if (result.status === "updated") return "library.updated_ok";
  if (result.status === "up_to_date") return "library.up_to_date";
  if (result.status === "no_file") return "library.no_file";
  return "library.update_failed";
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

function setProgress(container, bar, counter, value, total) {
  container.hidden = false;
  bar.max = total || 1;
  bar.value = value;
  counter.textContent = `${value} / ${total}`;
}

function selectTab(name) {
  const isLibrary = name === "library";
  el.panelConvert.hidden = isLibrary;
  el.panelLibrary.hidden = !isLibrary;
  el.tabConvert.classList.toggle("active", !isLibrary);
  el.tabLibrary.classList.toggle("active", isLibrary);
  el.tabConvert.setAttribute("aria-selected", String(!isLibrary));
  el.tabLibrary.setAttribute("aria-selected", String(isLibrary));
  if (isLibrary) loadLibrary();
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
// Start
// ---------------------------------------------------------------------------

async function init() {
  el.form.addEventListener("submit", loadPreview);
  el.convertButton.addEventListener("click", convert);
  el.tabConvert.addEventListener("click", () => selectTab("convert"));
  el.tabLibrary.addEventListener("click", () => selectTab("library"));
  el.updateAll.addEventListener("click", updateAll);
  el.libraryRefresh.addEventListener("click", loadLibrary);
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
}

init().catch((error) => {
  console.error(error);
  document.body.insertAdjacentHTML(
    "afterbegin",
    `<p style="color:red;padding:1rem">Init failed: ${error.message}</p>`
  );
});
