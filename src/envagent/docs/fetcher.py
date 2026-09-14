"""Fetch and clean official documentation pages.

Tries a page's markdown variant first (many modern docs sites, e.g.
Flutter's, serve one at `<url>.md` — confirmed by fetching the real page
before building this), which needs no HTML parsing at all. Falls back to
basic HTML extraction for sites that don't offer that.
"""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from envagent.docs import cache

_TIMEOUT = 10.0
_HEADERS = {"User-Agent": "Mozilla/5.0 (envagent doc fetcher)"}

_OS_SECTION_MARKER = re.compile(r"\{:\s*\.steps\s+\.(\w+)-only\}")


def _try_markdown_variant(url: str) -> str | None:
    md_url = url if url.endswith(".md") else url.rstrip("/") + ".md"
    try:
        response = httpx.get(md_url, timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    content_type = response.headers.get("content-type", "")
    if "html" in content_type.lower():
        return None  # redirected back to an HTML page, not a real markdown doc
    return response.text


def _fetch_html_extracted(url: str) -> str:
    response = httpx.get(url, timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup
    return main.get_text("\n", strip=True)


def fetch_doc(url: str) -> str:
    """Fetch a doc page's content, using the local cache when fresh."""
    cached = cache.get(url)
    if cached is not None:
        return cached
    content = _try_markdown_variant(url) or _fetch_html_extracted(url)
    cache.put(url, content)
    return content


def extract_os_section(markdown: str, os_key: str) -> str:
    """Extracts just the OS-relevant content from a doc page that tags
    OS-specific blocks with a `{: .steps .<os>-only}` marker: each marker
    retroactively labels the block of text immediately *before* it (the
    Jekyll attribute-list convention — confirmed against the real
    structure, not assumed). Content after the very last marker is
    untagged/shared and always kept.

    Known limitation: the text preceding the *first* marker is labeled by
    that first marker's OS (e.g. shared framing like "choose your OS"
    ends up bundled with whichever OS is listed first in the doc) — a
    minor cosmetic loss for other OSes, not a correctness issue: the
    actual OS-specific commands are still captured exactly.
    """
    matches = list(_OS_SECTION_MARKER.finditer(markdown))
    if not matches:
        return markdown

    parts = []
    block_start = 0
    for m in matches:
        if m.group(1) == os_key:
            parts.append(markdown[block_start : m.start()])
        block_start = m.end()
    parts.append(markdown[block_start:])  # after the last marker — shared
    return "\n\n".join(part.strip() for part in parts if part.strip())
