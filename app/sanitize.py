"""Cleaning chapter HTML into something EPUB readers can digest.

E-ink readers dislike scripts, iframes and arbitrary CSS, and EPUB validators
demand well-formed XHTML. Instead of pulling in `bleach` we run a small
allowlist over BeautifulSoup - full control and zero extra dependencies.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import (
    BeautifulSoup,
    CData,
    Comment,
    Declaration,
    Doctype,
    NavigableString,
    ProcessingInstruction,
    Tag,
)

#: Nodes that are not content, yet `decode()` writes them out verbatim.
#: Sites keep commented-out ad code in there - without this the whole
#: <!--<script src="...ad.js"></script>--> ended up inside the EPUB.
NON_CONTENT_NODES = (Comment, CData, ProcessingInstruction, Declaration, Doctype)

ALLOWED_TAGS: set[str] = {
    "a", "b", "blockquote", "br", "code", "div", "em", "figcaption", "figure",
    "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "li", "ol", "p", "pre",
    "s", "small", "span", "strong", "sub", "sup", "table", "tbody", "td", "tfoot",
    "th", "thead", "tr", "u", "ul",
}

#: Removed together with their content (unlike tags outside the allowlist,
#: which are "unwrapped" - the text stays, the markup goes).
DROP_TAGS: set[str] = {
    "script", "style", "iframe", "noscript", "form", "input", "button", "select",
    "textarea", "svg", "canvas", "video", "audio", "object", "embed", "ins",
}

ALLOWED_ATTRS: dict[str, set[str]] = {
    "a": {"href", "title"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
    "*": {"id"},
}

_HIDDEN_RE = re.compile(
    r"(display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0)", re.I
)
_CSS_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")
#: Simple selectors only - we are not pretending to be a CSS engine.
_SIMPLE_SELECTOR_RE = re.compile(r"^[.#]?[\w-]+$")


def strip_css_hidden(soup: BeautifulSoup | Tag) -> None:
    """Removes elements hidden by a <style> block in the document.

    Some sites (RoyalRoad among them) inject decoy paragraphs into the content
    that are hidden by a CSS rule - invisible in a browser, visible in an EPUB.
    Modifies the tree in place.
    """
    hidden_selectors: list[str] = []
    for style_tag in soup.find_all("style"):
        css = style_tag.get_text()
        for raw_selectors, declarations in _CSS_RULE_RE.findall(css):
            if not _HIDDEN_RE.search(declarations):
                continue
            for selector in raw_selectors.split(","):
                selector = selector.strip()
                if _SIMPLE_SELECTOR_RE.match(selector):
                    hidden_selectors.append(selector)

    for selector in hidden_selectors:
        try:
            for element in soup.select(selector):
                element.decompose()
        except Exception:  # noqa: BLE001 - the selector may be exotic
            continue


def _promote_br_breaks_to_paragraphs(soup: BeautifulSoup | Tag) -> None:
    """Turns "text<br><br>text" into "<p>text</p><p>text</p>".

    Some sites separate paragraphs with a pair of <br> instead of wrapping
    each one in <p> - readable in a browser, but with no paragraph margin
    to apply in an EPUB. This finds runs of 2+ consecutive <br> inside a
    container and splits the container's children into separate <p> tags
    at those points.
    """
    for container in soup.find_all(["div", "body", "[document]"]):
        children = list(container.children)
        has_double_break = False
        run = 0
        for child in children:
            if isinstance(child, Tag) and child.name == "br":
                run += 1
                if run >= 2:
                    has_double_break = True
                    break
            elif isinstance(child, NavigableString) and not child.strip():
                continue  # whitespace between <br> tags doesn't break the run
            else:
                run = 0
        if not has_double_break:
            continue

        new_children: list[list] = [[]]
        run = 0
        for child in children:
            if isinstance(child, Tag) and child.name == "br":
                run += 1
                if run >= 2:
                    new_children.append([])
                    run = 0
                    continue
            elif not (isinstance(child, NavigableString) and not child.strip()):
                run = 0
            new_children[-1].append(child)

        container.clear()
        for group in new_children:
            if not any(
                (isinstance(c, Tag)) or (isinstance(c, NavigableString) and c.strip())
                for c in group
            ):
                continue
            p = soup.new_tag("p")
            for c in group:
                p.append(c)
            container.append(p)
def sanitize_html(
    html: str | Tag,
    *,
    base_url: str | None = None,
    keep_images: bool = False,
) -> str:
    """Returns an XHTML fragment ready to drop into an EPUB chapter."""
    if isinstance(html, Tag):
        # Copy by re-parsing so we don't destroy the caller's tree.
        fragment = BeautifulSoup(str(html), "html.parser")
    else:
        fragment = BeautifulSoup(html, "html.parser")

    strip_css_hidden(fragment)
    _promote_br_breaks_to_paragraphs(fragment)

    for node in fragment.find_all(string=lambda s: isinstance(s, NON_CONTENT_NODES)):
        node.extract()

    for tag in fragment.find_all(list(DROP_TAGS)):
        tag.decompose()

    for tag in list(fragment.find_all(True)):
        if not tag.parent:  # already removed along with its parent
            continue

        if _is_hidden(tag):
            tag.decompose()
            continue

        if tag.name == "img" and not keep_images:
            tag.decompose()
            continue

        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()
            continue

        allowed = ALLOWED_ATTRS.get(tag.name, set()) | ALLOWED_ATTRS["*"]
        for attr in list(tag.attrs):
            if attr not in allowed:
                del tag[attr]

        if base_url:
            if tag.name == "a" and tag.get("href"):
                tag["href"] = urljoin(base_url, tag["href"])
            elif tag.name == "img" and tag.get("src"):
                tag["src"] = urljoin(base_url, tag["src"])

    _drop_empty_blocks(fragment)
    return fragment.decode().strip()


def html_to_text(html: str | Tag, *, limit: int | None = None) -> str:
    """Flattened text - for metadata descriptions and the frontend preview."""
    soup = html if isinstance(html, Tag) else BeautifulSoup(html, "html.parser")
    text = " ".join(soup.get_text(" ", strip=True).split())
    if limit and len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


def _is_hidden(tag: Tag) -> bool:
    if tag.has_attr("hidden"):
        return True
    style = tag.get("style")
    return bool(style and _HIDDEN_RE.search(style))


def _drop_empty_blocks(soup: BeautifulSoup) -> None:
    """Removes empty <p>/<div>/<span> left behind by the cleaning pass."""
    for tag in soup.find_all(["p", "div", "span"]):
        if tag.find(["img", "br", "hr", "table"]):
            continue
        if not tag.get_text(strip=True):
            tag.decompose()

    # Leading/trailing <br> adds nothing.
    for tag in soup.find_all("br"):
        siblings = [
            s for s in tag.parent.children
            if not (isinstance(s, NavigableString) and not s.strip())
        ]
        if siblings and siblings[0] is tag:
            tag.decompose()
