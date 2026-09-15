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


def _heading_level(stripped_line: str) -> int | None:
    """Level of an ATX heading (1-6), or None if the line isn't one."""
    if not stripped_line.startswith("#"):
        return None
    hashes = len(stripped_line) - len(stripped_line.lstrip("#"))
    rest = stripped_line[hashes:]
    if hashes > 6 or (rest and not rest[0].isspace()):
        return None  # e.g. a "#" inside a code comment like "#!/bin/bash", not a heading
    return hashes


def extract_section(markdown: str, heading: str) -> str:
    """Keeps one Markdown section (an ATX `heading` up to the next heading
    of equal-or-shallower level). Falls back to the full input if `heading`
    isn't found — same graceful-degradation pattern as extract_os_section.
    Ignores lines inside fenced code blocks, so a shell comment like
    `# Use bash` in an example snippet is never mistaken for a heading."""
    lines = markdown.splitlines()
    start = None
    level = None
    in_code_fence = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        line_level = _heading_level(stripped)
        if line_level is None:
            continue
        text = stripped.lstrip("#").strip()
        if text.lower() == heading.lower():
            start = i
            level = line_level
            break
    if start is None:
        return markdown

    end = len(lines)
    in_code_fence = False
    for j in range(start + 1, len(lines)):
        stripped = lines[j].strip()
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        j_level = _heading_level(stripped)
        if j_level is not None and j_level <= level:
            end = j
            break
    return "\n".join(lines[start:end]).strip()


def extract_os_section(markdown: str, os_key: str) -> str:
    """Keeps only blocks tagged `{: .steps .<os_key>-only}`; a marker labels the block before it."""
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
