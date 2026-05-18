# HANDOFF — web_search tool
*For: Hayeong to implement via handoff_reader*
*Layer: Vision — this is how Hayeong sees the world beyond her local machine*

---

## What This Tool Does

Gives Hayeong the ability to search the web and fetch page content.
Two operations: `search` (get a list of results) and `fetch` (get the text of a page).
Uses DuckDuckGo for search (no API key needed) and requests for page fetching.

---

FILE: Toolbox/web_search/web_search.py
```python
"""
Toolbox/web_search/web_search.py

Vision layer tool — Hayeong's window to the world beyond local hardware.
Searches the web and fetches page content.

Operations:
    search  — query DuckDuckGo, return top results as structured text
    fetch   — retrieve and clean the text content of a URL

Params:
    operation  (str) — "search" or "fetch"
    query      (str) — search terms (operation=search)
    url        (str) — page to fetch (operation=fetch)
    max_results(int) — how many results to return (default 5, max 10)

Returns:
    str — results as plain text, never raises
"""

import re
import urllib.parse
import urllib.request
from pathlib import Path


def run(description: str, params: dict) -> str:
    operation = params.get("operation", "search").strip().lower()
    try:
        if operation == "search":
            return _search(params)
        elif operation == "fetch":
            return _fetch(params)
        else:
            return f"[web_search] Unknown operation: '{operation}'. Use 'search' or 'fetch'."
    except Exception as e:
        return f"[web_search] Error: {e}"


# ── Search ────────────────────────────────────────────────────────────

def _search(params: dict) -> str:
    query = params.get("query", "").strip()
    if not query:
        return "[web_search] No query provided."

    max_results = min(int(params.get("max_results", 5)), 10)

    encoded = urllib.parse.quote_plus(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded}"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    results = _parse_ddg_results(html, max_results)

    if not results:
        return f"[web_search] No results found for: {query}"

    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}")
        lines.append(f"   {r['url']}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet']}")
        lines.append("")

    return "\n".join(lines).strip()


def _parse_ddg_results(html: str, max_results: int) -> list:
    results = []

    # Extract result blocks
    blocks = re.findall(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        html, re.DOTALL
    )
    snippets = re.findall(
        r'class="result__snippet"[^>]*>(.*?)</a>',
        html, re.DOTALL
    )

    for i, (href, title_html) in enumerate(blocks[:max_results]):
        title = _strip_tags(title_html).strip()
        url   = _clean_url(href)
        snip  = _strip_tags(snippets[i]).strip() if i < len(snippets) else ""
        if title and url:
            results.append({"title": title, "url": url, "snippet": snip})

    return results


# ── Fetch ─────────────────────────────────────────────────────────────

def _fetch(params: dict) -> str:
    url = params.get("url", "").strip()
    if not url:
        return "[web_search] No URL provided."

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()

    # Detect encoding
    encoding = "utf-8"
    content_type = resp.headers.get("Content-Type", "")
    charset_match = re.search(r"charset=([^\s;]+)", content_type)
    if charset_match:
        encoding = charset_match.group(1).strip()

    html = raw.decode(encoding, errors="replace")
    text = _extract_text(html)

    # Truncate to a reasonable size for LLM context
    max_chars = 4000
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[... content truncated at {max_chars} chars]"

    return f"Content from: {url}\n\n{text}"


def _extract_text(html: str) -> str:
    # Remove script and style blocks entirely
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove all remaining tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Decode common HTML entities
    entities = {
        "&amp;": "&", "&lt;": "<", "&gt;": ">",
        "&quot;": '"', "&#39;": "'", "&nbsp;": " ",
    }
    for ent, char in entities.items():
        text = text.replace(ent, char)
    # Collapse whitespace
    text = re.sub(r"\s{2,}", "\n", text)
    return text.strip()


# ── Helpers ───────────────────────────────────────────────────────────

def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def _clean_url(href: str) -> str:
    # DuckDuckGo wraps URLs — extract the real one
    if "uddg=" in href:
        match = re.search(r"uddg=([^&]+)", href)
        if match:
            return urllib.parse.unquote(match.group(1))
    return href
```

FILE: Toolbox/web_search/__init__.py
```python
```

FILE: Toolbox/web_search/README.md
```
# Toolbox/web_search

Vision layer tool. Hayeong's window to the world beyond local hardware.

## Operations

### search
Query DuckDuckGo and return top results.

Params:
  operation  : "search"
  query      : search terms
  max_results: how many results (default 5, max 10)

Example:
  operation=search, query=python asyncio tutorial, max_results=5

### fetch
Retrieve and clean the text content of a URL.

Params:
  operation: "fetch"
  url      : full URL to fetch

Example:
  operation=fetch, url=https://docs.python.org/3/library/asyncio.html

## Notes
- No API key required — uses DuckDuckGo HTML interface
- Fetch truncates at 4000 chars to fit LLM context
- All errors return a string — never crashes main
```
