/* webnoveltoepub - frontend with no framework and no build step. */

const STORAGE_KEY = "wne.language";
const FALLBACK_LANGUAGE = "en";

const state = {
  language: FALLBACK_LANGUAGE,
  strings: {},
  languages: [],
  preview: null,
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

  el.chaptersCount.textContent = t("chapters.found", { count: chapters.length });
  if (chapters.length > maxChapters) {
    el.limitWarning.textContent = t("chapters.limit_warning", { max: maxChapters });
    el.limitWarning.hidden = false;
  } else {
    el.limitWarning.hidden = true;
  }

  el.bookLanguage.value = metadata.language || "";
  el.chaptersCard.hidden = false;
}

function renderChapters(chapters, maxChapters) {
  const items = chapters.map((chapter) => {
    const li = document.createElement("li");
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = String(chapter.index);
    // By default tick only as many as the server would let through anyway.
    checkbox.checked = chapter.index <= maxChapters;
    checkbox.addEventListener("change", updateSelectedCount);

    const num = document.createElement("span");
    num.className = "num";
    num.textContent = chapter.index;

    const title = document.createElement("span");
    title.textContent = chapter.title;

    label.append(checkbox, num, title);
    li.append(label);
    return li;
  });

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
  const known = ["invalid_url", "unsupported_site", "parser_error", "fetch_error"];
  const match = known.find((key) => String(detail || "").startsWith(key));
  return match ? `error.${match}` : "error.unknown";
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

async function loadPreview(event) {
  event.preventDefault();
  clearError();
  setStatus(null);
  el.previewButton.disabled = true;
  el.previewButton.textContent = t("form.loading");

  try {
    const response = await fetch("/api/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: el.url.value.trim() }),
    });

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      showError(errorKeyFromDetail(body.detail));
      return;
    }

    state.preview = await response.json();
    renderNovel(state.preview);
    renderChapters(state.preview.chapters, state.preview.max_chapters);
  } catch (error) {
    showError("error.network", error.message);
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

  try {
    const response = await fetch("/api/convert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: state.preview.metadata.source_url,
        selected,
        include_cover: el.includeCover.checked,
        language: el.bookLanguage.value.trim() || null,
      }),
    });

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      showError(errorKeyFromDetail(body.detail));
      setStatus(null);
      return;
    }

    const blob = await response.blob();
    triggerDownload(blob, fileNameFrom(response) || "novel.epub");
    setStatus("convert.done");
  } catch (error) {
    showError("error.network", error.message);
    setStatus(null);
  } finally {
    el.convertButton.disabled = false;
  }
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
