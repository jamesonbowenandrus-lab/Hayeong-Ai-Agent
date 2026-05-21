"""
web_search_tool.py
──────────────────
Standard run() wrapper around WebSearch for Hayeong's tool registry.
The WebSearch class stays untouched — this file is the bridge.

Params accepted:
    query       (str)  — search query. Falls back to description if absent.
    mode        (str)  — "search" | "news" | "read" | "fetch"
                         search: standard web search (default)
                         news:   news-specific search
                         read:   search + fetch full text of top result
                         fetch:  fetch a specific URL (requires 'url' param)
    max_results (int)  — number of search results. default 5
    fetch_top   (int)  — pages to fetch full text for. default 1. 0 = snippets only
    url         (str)  — required when mode is "fetch"
"""

from pathlib import Path
import sys

# Make sure web_search.py is importable from the same folder
_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from web_search import WebSearch

# Single shared instance — initialised once at import time
_searcher = WebSearch()


def run(description: str, params: dict) -> str:
    """
    Standard tool contract entry point.
    Returns [SUCCESS], [ERROR], or [PARTIAL] prefixed strings.
    Never raises.
    """
    try:
        if not _searcher.is_available():
            return (
                "[ERROR] WebSearch: duckduckgo-search package not installed. "
                "Run: pip install duckduckgo-search"
            )

        mode        = str(params.get("mode", "search")).lower().strip()
        query       = str(params.get("query", description)).strip()
        max_results = int(params.get("max_results", 5))
        fetch_top   = int(params.get("fetch_top", 1))

        # ── Fetch a specific URL directly ──────────────────────────────
        if mode == "fetch":
            url = str(params.get("url", "")).strip()
            if not url:
                return "[ERROR] WebSearch: mode 'fetch' requires a 'url' param"
            text = _searcher.fetch_page(url)
            if not text:
                return f"[ERROR] WebSearch: could not fetch page — {url}"
            preview = text[:300].replace("\n", " ")
            return (
                f"[SUCCESS] WebSearch fetched {len(text)} chars from {url} — "
                f"preview: {preview}..."
            )

        # ── News search ────────────────────────────────────────────────
        if mode == "news":
            results = _searcher.news(query, max_results=max_results)
            if not results:
                return f"[PARTIAL] WebSearch news: no results for '{query}'"
            formatted = _searcher.format_for_context(query, {"results": results, "full_text": {}})
            return f"[SUCCESS] WebSearch news ({len(results)} results) — {formatted}"

        # ── Standard search or search+read (default) ───────────────────
        data = _searcher.search_and_read(
            query,
            max_results=max_results,
            fetch_top=fetch_top if mode == "read" else fetch_top,
        )

        results   = data.get("results", [])
        full_text = data.get("full_text", {})

        if not results:
            return f"[PARTIAL] WebSearch: no results found for '{query}'"

        quality   = _searcher.assess_content_quality(query, data)
        formatted = _searcher.format_for_context(query, data)

        confidence = quality.get("confidence", "unknown")
        n_results  = len(results)
        n_fetched  = len(full_text)

        return (
            f"[SUCCESS] WebSearch '{query}' — {n_results} results, "
            f"{n_fetched} page(s) fetched, confidence {confidence} — "
            f"{formatted}"
        )

    except Exception as e:
        return f"[ERROR] WebSearch: {type(e).__name__}: {e}"
