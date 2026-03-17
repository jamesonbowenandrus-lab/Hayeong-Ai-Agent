"""
web_search.py
─────────────
Hayeong's web search capability. Lets her look things up, read articles,
check current events, and answer questions that need live information.

DESIGN PHILOSOPHY:
  - Search results are context, not responses. They get injected into
    Hayeong's conversation so she synthesizes them in her own voice.
  - Fetch page content when snippets aren't enough — she can actually read.
  - Fail gracefully. If search is down, she says so and moves on.
  - No API keys. DuckDuckGo is free and works well enough.

CAPABILITIES:
  - search(query)           → list of {title, url, snippet}
  - fetch_page(url)         → clean text from a webpage
  - search_and_read(query)  → search + auto-fetches top result for rich answers
  - news(query)             → news-specific search results
  - format_for_context()    → formats results for injection into Hayeong's prompt

USAGE (from main.py):
  from web_search import WebSearch
  searcher = WebSearch()

  # Simple search — inject results as context, let Hayeong synthesize
  context = searcher.search_and_read("latest AMD GPU news")
  # → pass context into system_prompt for this turn

TRIGGERS (intent detection):
  "search for", "look up", "google", "find out about", "what's the latest",
  "news about", "what is", "who is", "how much does", "is X still"

INSTALL:
  pip install duckduckgo-search
"""

import re
import time
import requests
from pathlib import Path
from datetime import datetime
from html.parser import HTMLParser
from typing import Optional

# ─────────────────────────────────────────────
# DEPENDENCY CHECK
# Supports both the old package name (duckduckgo_search) and the
# new one (ddgs) — handles the rename transparently.
# ─────────────────────────────────────────────

def _check_ddgs() -> bool:
    try:
        from ddgs import DDGS  # noqa  (new package name)
        return True
    except ImportError:
        pass
    try:
        from duckduckgo_search import DDGS  # noqa  (old package name)
        return True
    except ImportError:
        pass
    return False

def _get_ddgs():
    """Returns the DDGS class from whichever package is installed."""
    try:
        from ddgs import DDGS
        return DDGS
    except ImportError:
        from duckduckgo_search import DDGS
        return DDGS

DDGS_AVAILABLE = _check_ddgs()

OLLAMA_URL      = "http://localhost:11434/api/chat"
QUERY_MODEL     = "qwen2.5:7b"   # Fast model for query extraction only


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

BASE_DIR    = Path(__file__).parent
LOG_DIR     = BASE_DIR / "logs"
LOG_FILE    = LOG_DIR  / "web_search.log"
LOG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_MAX_RESULTS  = 5
DEFAULT_FETCH_CHARS  = 4000   # Max characters to extract from a fetched page
REQUEST_TIMEOUT      = 10     # Seconds before giving up on a page fetch
SEARCH_TIMEOUT       = 8      # Seconds before giving up on a search


# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

def _log(msg: str):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(f"[WebSearch] {msg}")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ─────────────────────────────────────────────
# HTML TEXT EXTRACTOR
# Pulls readable text from HTML without needing BeautifulSoup.
# ─────────────────────────────────────────────

class _TextExtractor(HTMLParser):
    """Strips HTML tags and returns clean readable text."""

    _SKIP_TAGS = {"script", "style", "nav", "header", "footer",
                  "aside", "noscript", "iframe", "svg", "form"}

    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            stripped = data.strip()
            if stripped:
                self.chunks.append(stripped)

    def get_text(self, max_chars: int = DEFAULT_FETCH_CHARS) -> str:
        raw = " ".join(self.chunks)
        # Collapse whitespace
        raw = re.sub(r"\s{2,}", " ", raw)
        return raw[:max_chars]


def _extract_text_from_html(html: str, max_chars: int = DEFAULT_FETCH_CHARS) -> str:
    """Extract readable text from raw HTML."""
    extractor = _TextExtractor()
    try:
        extractor.feed(html)
        return extractor.get_text(max_chars)
    except Exception:
        # Fallback: strip all tags with regex
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s{2,}", " ", text)
        return text[:max_chars]


# ─────────────────────────────────────────────
# MAIN CLASS
# ─────────────────────────────────────────────

class WebSearch:
    """
    Hayeong's web search interface.
    Create one instance at startup and share it.

    All methods return clean data — no Ollama calls in here.
    Synthesis happens through Hayeong's normal conversation system.
    """

    def __init__(self):
        if not DDGS_AVAILABLE:
            print("⚠️  [WebSearch] duckduckgo-search not installed.")
            print("   Run: pip install duckduckgo-search")
        else:
            _log("WebSearch ready.")

    def is_available(self) -> bool:
        return DDGS_AVAILABLE

    # ─────────────────────────────────────────────
    # SEARCH
    # ─────────────────────────────────────────────

    def search(self, query: str, max_results: int = DEFAULT_MAX_RESULTS) -> list[dict]:
        """
        Search DuckDuckGo and return results.
        Each result: {title, url, snippet}
        Returns [] on failure.
        """
        if not DDGS_AVAILABLE:
            return []

        _log(f"Searching: {query!r}")
        try:
            DDGS = _get_ddgs()
            with DDGS() as ddgs:
                raw = list(ddgs.text(
                    query=query,
                    max_results=max_results,
                    safesearch="moderate",
                ))

            results = [
                {
                    "title":   r.get("title", ""),
                    "url":     r.get("href",  ""),
                    "snippet": r.get("body",  ""),
                }
                for r in raw
            ]
            _log(f"Found {len(results)} results for {query!r}")
            return results

        except Exception as e:
            _log(f"Search error: {e}")
            return []

    def news(self, query: str, max_results: int = DEFAULT_MAX_RESULTS) -> list[dict]:
        """
        Search DuckDuckGo News specifically.
        Each result: {title, url, snippet, source, date}
        """
        if not DDGS_AVAILABLE:
            return []

        _log(f"News search: {query!r}")
        try:
            DDGS = _get_ddgs()
            with DDGS() as ddgs:
                raw = list(ddgs.news(
                    query=query,
                    max_results=max_results,
                ))

            results = [
                {
                    "title":   r.get("title",  ""),
                    "url":     r.get("url",    ""),
                    "snippet": r.get("body",   ""),
                    "source":  r.get("source", ""),
                    "date":    r.get("date",   ""),
                }
                for r in raw
            ]
            _log(f"Found {len(results)} news results for {query!r}")
            return results

        except Exception as e:
            _log(f"News search error: {e}")
            return []

    # ─────────────────────────────────────────────
    # PAGE FETCH
    # ─────────────────────────────────────────────

    def fetch_page(self, url: str, max_chars: int = DEFAULT_FETCH_CHARS) -> str:
        """
        Fetch a webpage and return its readable text content.
        Good for reading a full article rather than just the snippet.
        Returns empty string on failure.
        """
        _log(f"Fetching: {url}")
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
            }
            resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()

            text = _extract_text_from_html(resp.text, max_chars)
            _log(f"Fetched {len(text)} chars from {url}")
            return text

        except Exception as e:
            _log(f"Fetch error ({url}): {e}")
            return ""

    # ─────────────────────────────────────────────
    # COMBINED SEARCH + READ
    # ─────────────────────────────────────────────

    def search_and_read(self, query: str, max_results: int = 4,
                         fetch_top: int = 1) -> dict:
        """
        Search, then fetch the top result(s) for full content.
        If a page returns a 403 or empty body, tries the next result
        rather than giving up — so snippets-only is a last resort,
        not the default failure mode.

        Returns:
            {
                "query":   original query,
                "results": [{title, url, snippet}, ...],
                "full_text": {url: text, ...}  ← for fetched pages
            }

        fetch_top=0 → snippets only (fast)
        fetch_top=1 → fetch the most relevant result (default)
        fetch_top=2 → fetch top two (slower, richer)
        """
        results = self.search(query, max_results=max_results)

        full_text = {}
        if fetch_top > 0 and results:
            # Try up to fetch_top successes, but attempt up to all results
            # so a 403 on result 1 doesn't mean we skip everything
            successes = 0
            for r in results:
                if successes >= fetch_top:
                    break
                url  = r["url"]
                text = self.fetch_page(url)
                if text:
                    full_text[url] = text
                    successes += 1
                else:
                    _log(f"Skipping {url} (empty or blocked), trying next result")

        return {
            "query":     query,
            "results":   results,
            "full_text": full_text,
        }

    # ─────────────────────────────────────────────
    # CONTEXT FORMATTER
    # Formats search data for injection into Hayeong's system prompt.
    # She synthesizes this in her own voice — not a template response.
    # ─────────────────────────────────────────────

    def format_for_context(self, query: str, data: dict,
                           max_snippet_chars: int = 300) -> str:
        """
        Format search results as a context block to prepend to Hayeong's
        system prompt for a single turn.

        Usage in main.py:
            context = searcher.format_for_context(user_input, data)
            system_prompt = context + "\\n\\n" + system_prompt
            # Then call stream_response_and_speak as normal
        """
        results  = data.get("results",   [])
        pages    = data.get("full_text", {})

        if not results:
            return (
                f"[WEB SEARCH — 0 results for: {query!r}]\n"
                "The web search returned no results for this query. "
                "Tell James that search came up empty, mention what you searched for, "
                "and answer from your training knowledge if you can — but be clear "
                "you're doing so. Suggest rephrasing if the query seems off."
            )

        lines = [f"[WEB SEARCH RESULTS for: {query!r}]", ""]

        for i, r in enumerate(results, 1):
            title   = r.get("title",   "").strip()
            url     = r.get("url",     "").strip()
            snippet = r.get("snippet", "").strip()[:max_snippet_chars]
            source  = r.get("source",  "")
            date    = r.get("date",    "")

            meta = " | ".join(x for x in [source, date] if x)
            lines.append(f"{i}. {title}")
            if meta:
                lines.append(f"   [{meta}]")
            lines.append(f"   {url}")
            if snippet:
                lines.append(f"   {snippet}")

            # Include full page text for fetched pages (truncated)
            if url in pages:
                page_text = pages[url][:1500]
                lines.append(f"\n   [Full article excerpt]:\n   {page_text}\n")

            lines.append("")

        lines.append(
            "IMPORTANT: Base your answer on the search results above. "
            "Do NOT answer from your training data if the results cover the topic — "
            "the results are more current and accurate than what you were trained on. "
            "Synthesize the results naturally in your own voice, like you looked it up yourself. "
            "Cite sources briefly where it adds credibility (e.g. 'according to Tom's Hardware...'). "
            "If the results genuinely don't answer the question, say so and explain what you found instead."
        )

        return "\n".join(lines)

    # ─────────────────────────────────────────────
    # LLM QUERY EXTRACTOR
    # Uses a small fast model to pull the actual search query out of
    # whatever James said, however he said it.
    # Falls back to regex clean_query() if Ollama is unavailable.
    # ─────────────────────────────────────────────

    @staticmethod
    def extract_query(user_input: str, recent_memory: list = None) -> str:
        """
        Extract a clean, searchable query from natural language.
        Accepts optional recent_memory to resolve vague references like
        "did you get that?" or "can you look that up?" where the actual
        topic lives in the previous conversation turn.

        Falls back to regex clean_query() if Ollama is unavailable.
        """
        # Build conversation context snippet for the LLM
        context_lines = []
        if recent_memory:
            for m in recent_memory[-4:]:
                role = "James" if m["role"] == "user" else "Hayeong"
                snippet = m.get("content", "")[:200]
                context_lines.append(f"  {role}: {snippet}")
        context_block = (
            "Recent conversation:\n" + "\n".join(context_lines) + "\n\n"
            if context_lines else ""
        )

        try:
            resp = requests.post(
                OLLAMA_URL,
                json={
                    "model": QUERY_MODEL,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Extract the search query from the user's message. "
                                "Use the recent conversation to resolve vague references "
                                "like 'that', 'it', 'the information', 'those specs', etc. "
                                "Return ONLY the search query — no explanation, no punctuation, "
                                "no preamble. Just the keywords to search for.\n"
                                "Examples:\n"
                                "  'can you search for AMD RX 9070 XT release date' → 'AMD RX 9070 XT release date'\n"
                                "  'hey look up the specs for my GPU, I have a 7900 XTX' → 'AMD RX 7900 XTX specs'\n"
                                "  'what is the latest news on ComfyUI updates' → 'ComfyUI updates latest news'\n"
                                "  'find out how much the RTX 5090 costs' → 'RTX 5090 price'\n"
                                "  [context: discussed Threadripper CPUs] 'did you gather the information?' → 'AMD Threadripper CPU specs 2024'\n"
                                "  [context: discussed Minecraft mods] 'can you look that up?' → 'best Minecraft mods 2024'\n"
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"{context_block}Current message: {user_input}",
                        },
                    ],
                    "stream": False,
                    "options": {"temperature": 0.0},
                },
                timeout=12,
            )
            query = resp.json()["message"]["content"].strip().strip('"').strip("'")
            if 2 <= len(query.split()) <= 12 and len(query) < 150:
                _log(f"LLM extracted query: {query!r} (from: {user_input[:60]!r})")
                return query
        except Exception as e:
            _log(f"LLM query extraction failed ({e}) — using regex fallback")

        return WebSearch.clean_query(user_input)

    # ─────────────────────────────────────────────
    # QUERY CLEANER
    # Strips conversational framing before searching
    # ─────────────────────────────────────────────

    @staticmethod
    def clean_query(user_input: str) -> str:
        """
        Strip conversational framing so the actual search query is clean.
        "search for the best AMD GPU right now" → "best AMD GPU right now"
        "what's the latest news on RTX 5090"   → "RTX 5090 latest news"
        "look up DuckDuckGo API"                → "DuckDuckGo API"
        """
        strip_phrases = [
            r"(?i)^(search for|look up|google|find out about|find|search)\s+",
            r"(?i)^(what'?s the latest (on|about|for|with))\s+",
            r"(?i)^(what'?s the current|what is the current)\s+",
            r"(?i)^(news about|latest news (on|about))\s+",
            r"(?i)^(can you (search|look up|find|check))\s+",
            r"(?i)^(hey hayeong[,:]?\s+)",
            r"(?i)^(hayeong[,:]?\s+)",
        ]
        q = user_input.strip()
        for pattern in strip_phrases:
            q = re.sub(pattern, "", q).strip()
        return q or user_input.strip()


# ─────────────────────────────────────────────
# STANDALONE TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("WebSearch — Standalone Test")
    print("=" * 60)

    if not DDGS_AVAILABLE:
        print("❌ duckduckgo-search not installed.")
        print("   Run: pip install duckduckgo-search")
        exit(1)

    searcher = WebSearch()

    query = input("\nEnter a search query (or press Enter for default): ").strip()
    if not query:
        query = "AMD RX 9070 XT release date and performance"

    print(f"\n🔍 Searching: {query!r}")
    print("─" * 40)

    data = searcher.search_and_read(query, max_results=4, fetch_top=1)

    print(f"\nFound {len(data['results'])} results.")
    print(f"Fetched full text for {len(data['full_text'])} page(s).")
    print("\n── FORMATTED CONTEXT (what Hayeong sees) ──\n")
    context = searcher.format_for_context(query, data)
    print(context)

    print("\n── QUERY CLEANER TEST ──")
    test_inputs = [
        "search for the best AMD GPU right now",
        "look up DuckDuckGo Python library",
        "what's the latest on the RTX 5090",
        "news about AMD RX 9070 XT",
        "hey hayeong, can you find out about ComfyUI updates",
    ]
    for t in test_inputs:
        cleaned = WebSearch.clean_query(t)
        print(f"  '{t}'\n    → '{cleaned}'")
