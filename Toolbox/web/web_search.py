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

OLLAMA_URL      = "http://localhost:11435/api/chat"
QUERY_MODEL     = "llama3.2:latest"   # Query extraction — comm model, always loaded


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
            "CRITICAL SYNTHESIS INSTRUCTIONS — read carefully before responding:\n"
            "1. Write in flowing conversational prose. Do NOT list results one by one. "
            "Do NOT write 'Here is what I found' or 'Here's a quick overview' or any report-style opener. "
            "Just talk, like you looked it up yourself and are telling James what you found.\n"
            "2. Weave the information together into one natural response. If multiple sources agree, "
            "say so in a sentence. If they differ, mention that. Never summarize each source separately.\n"
            "3. Use the search results as your primary source — they are more current than your training. "
            "Cite a source briefly only when it genuinely adds credibility "
            "(e.g. 'Tom's Hardware notes that...'). Don't cite everything.\n"
            "4. Stay in Hayeong's voice throughout — direct, warm, not robotic. "
            "This is a conversation, not a report.\n"
            "5. If the results don't answer the question well, say so plainly and tell James what you found instead."
        )

        return "\n".join(lines)

    def assess_content_quality(self, query: str, data: dict) -> dict:
        """
        Assess whether the fetched search data is actually useful for the query.

        Returns:
        {
            "has_useful_data": bool,
            "confidence": "high" | "medium" | "low" | "none",
            "usable_sources": int,   # sources with real content
            "total_content_chars": int,
            "issues": [str],         # list of problems found
            "recommendation": str    # what to do next
        }
        """
        results   = data.get("results",   [])
        pages     = data.get("full_text", {})
        issues    = []

        # Count sources that have real content
        usable = 0
        total_chars = 0

        # Login wall / paywall patterns that indicate blocked content
        block_phrases = [
            "create your free account", "sign in to continue", "subscribe to read",
            "create an account", "log in to access", "members only",
            "create your account today", "free member", "premium article",
            "please enable javascript", "javascript is required",
        ]

        for r in results:
            url     = r.get("url", "")
            snippet = r.get("snippet", "").strip()

            if url in pages:
                page_text = pages[url].lower()
                total_chars += len(pages[url])

                # Check if it's a login wall
                block_count = sum(1 for p in block_phrases if p in page_text)
                if block_count >= 2:
                    issues.append(f"Login wall detected: {url[:60]}")
                elif len(pages[url]) < 200:
                    issues.append(f"Nearly empty page: {url[:60]}")
                else:
                    usable += 1
            elif snippet and len(snippet) > 80:
                # Snippet only — counts as partial
                usable += 0.5
                total_chars += len(snippet)

        # Also check if query terms appear in the content
        query_words = [w.lower() for w in query.split() if len(w) > 3]
        content_blob = " ".join(
            pages.get(r["url"], r.get("snippet", "")).lower()
            for r in results
        )
        matched_terms = sum(1 for w in query_words if w in content_blob)
        term_coverage = matched_terms / max(len(query_words), 1)

        if term_coverage < 0.3:
            issues.append(f"Low topic relevance — only {matched_terms}/{len(query_words)} query terms found in content")

        # Determine overall confidence
        if usable >= 2 and term_coverage >= 0.5 and total_chars >= 1000:
            confidence = "high"
            has_useful = True
            recommendation = "proceed"
        elif usable >= 1 and term_coverage >= 0.3 and total_chars >= 400:
            confidence = "medium"
            has_useful = True
            recommendation = "proceed_with_caveats"
        elif total_chars >= 200:
            confidence = "low"
            has_useful = False
            recommendation = "try_alternate_queries"
        else:
            confidence = "none"
            has_useful = False
            recommendation = "no_data"

        return {
            "has_useful_data":      has_useful,
            "confidence":           confidence,
            "usable_sources":       int(usable),
            "total_content_chars":  total_chars,
            "issues":               issues,
            "recommendation":       recommendation,
        }

    def format_as_document(self, query: str, data: dict, topic: str = "",
                           model: str = "deepseek-r1:latest",
                           constraints: list = None) -> str:
        """
        Generate a proper synthesized research document using the LLM.

        Unlike the old version which just dumped raw source text, this:
        1. Assesses whether the fetched data is actually useful
        2. If yes — asks the LLM to write a real report FROM the sources
        3. If no  — honestly states what was found and what's missing,
                    includes the sources for James to check manually

        The result is a document James can actually read and use —
        not a source dump.
        """
        from datetime import datetime
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        title    = topic or query

        # ── Step 1: Quality check ──
        quality = self.assess_content_quality(query, data)
        results = data.get("results", [])
        pages   = data.get("full_text", {})

        header = [
            f"# {title}",
            f"*Research compiled by Hayeong — {date_str}*",
            f"*Data confidence: {quality['confidence'].upper()} "
            f"({quality['usable_sources']} usable source(s) found)*",
            "",
            "---",
            "",
        ]

        # ── Step 2: If data is too thin — honest report ──
        if not quality["has_useful_data"]:
            lines = header + [
                "## Research Status: Insufficient Data",
                "",
                "I searched for this topic but didn't find enough usable content "
                "to write a proper comparison. Here's what I ran into:",
                "",
            ]
            for issue in quality["issues"]:
                lines.append(f"- {issue}")
            lines += [
                "",
                "### What I did find (raw sources for your review):",
                "",
            ]
            for r in results:
                lines.append(f"- [{r.get('title','(no title)')}]({r.get('url','')})")
                snip = r.get("snippet", "").strip()
                if snip:
                    lines.append(f"  > {snip[:200]}")
            lines += [
                "",
                "---",
                "",
                "### Suggested next steps:",
                "",
                "- Try searching Reddit (reddit.com) for community comparisons",
                f"- Search: `{query} reddit`",
                f"- Search: `{query} wiki`",
                "- The official game wiki or fandom site may have better data",
            ]
            return "\n".join(lines)

        # ── Step 3: Good data — ask LLM to write the real report ──
        # Build a raw data block for the LLM to work from
        raw_data_lines = []
        for i, r in enumerate(results, 1):
            url     = r.get("url",     "")
            title_r = r.get("title",   "")
            snippet = r.get("snippet", "")
            raw_data_lines.append(f"\n[Source {i}] {title_r}\nURL: {url}")
            if url in pages:
                raw_data_lines.append(f"Content:\n{pages[url][:2500]}")
            elif snippet:
                raw_data_lines.append(f"Snippet: {snippet[:400]}")

        raw_data = "\n".join(raw_data_lines)

        synthesis_prompt = f"""You are Hayeong, writing a research document for James.

Topic: {title}
Original request: {query}
{f'''
EXPLICIT CONSTRAINTS — James stated these requirements. You MUST follow them exactly.
Before finalizing your report, re-read this list and remove anything that violates these constraints:
{chr(10).join(f"  - {c}" for c in constraints)}

If you cannot find content that fits within these constraints, say so clearly rather than including
content that violates them.
''' if constraints else ''}
Here is the raw source data you gathered from the web:

{raw_data}

---

Write a proper research report James can actually use. Follow these rules carefully:

CONTENT:
1. Summarize what each subject is — what it does, where it fits, why it matters
2. Compare them directly: similarities, differences, strengths, weaknesses
3. Give a clear recommendation — which is better, for what purpose, and why
4. If the data is genuinely missing something important, say so ONCE in a brief note at the end — not repeatedly throughout the report

WRITING STYLE — this is critical:
- Write like a knowledgeable person talking to a friend, not like a formal report generator
- Be direct and confident. If you found something useful, state it clearly.
- Do NOT use phrases like "it is implied", "it can be assumed", "based on limited information"
- Do NOT repeat the same caveat or gap more than once — mention it once and move on
- Do NOT pad with filler sentences like "further research would be needed" or "players should explore"
- If you can make a recommendation, make it. Don't hedge every sentence.
- Keep it tight — say what needs to be said, nothing more

FORMAT:
- Clean markdown with headers
- Do NOT list sources one by one — synthesize the information
- Do NOT include a Sources section — that will be appended separately"""

        try:
            resp = requests.post(
                OLLAMA_URL,
                json={
                    "model":   model,
                    "messages": [{"role": "user", "content": synthesis_prompt}],
                    "stream":  False,
                    "options": {"temperature": 0.3},
                },
                timeout=120,
            )
            synthesized = resp.json()["message"]["content"].strip()
            # Strip any Sources section the LLM may have added — we append our own below.
            # This fixes the duplicate sources bug where sources appeared twice in documents.
            synthesized = re.sub(r'\n##\s*Sources.*$', '', synthesized,
                                 flags=re.DOTALL | re.IGNORECASE).strip()
            _log(f"Document synthesized by {model} — {len(synthesized)} chars")
        except Exception as e:
            _log(f"LLM synthesis failed: {e} — falling back to raw format")
            # Fallback: at least give usable snippets
            synthesized = "LLM synthesis failed. Raw source data below.\n\n"
            for r in results:
                synthesized += f"### {r.get('title','')}\n{r.get('snippet','')}\n\n"

        # ── Step 4: Assemble final document ──
        source_refs = "\n".join(
            f"- [{r.get('title','(no title)')}]({r.get('url','')})"
            for r in results
        )

        footer = [
            "",
            "---",
            "",
            "## Sources",
            "",
            source_refs,
            "",
            f"*Generated by Hayeong — {date_str}*",
            f"*Confidence: {quality['confidence'].upper()} | "
            f"Usable sources: {quality['usable_sources']}*",
        ]

        return "\n".join(header) + synthesized + "\n".join(footer)

    def save_document(self, content: str, topic: str, save_dir: str = None) -> str:
        """
        Save a formatted document to disk. Returns the file path.
        Default save location: H:/hayeong/documents/
        """
        import re
        from datetime import datetime

        if save_dir is None:
            save_dir = str(BASE_DIR / "documents")

        Path(save_dir).mkdir(parents=True, exist_ok=True)

        # Clean topic for filename
        safe_topic = re.sub(r"[^\w\s-]", "", topic).strip()
        safe_topic = re.sub(r"\s+", "_", safe_topic)[:50]
        date_str   = datetime.now().strftime("%Y%m%d_%H%M")
        filename   = f"{safe_topic}_{date_str}.md"
        filepath   = str(Path(save_dir) / filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        _log(f"Document saved: {filepath}")
        return filepath


    # Uses a small fast model to pull the actual search query out of
    # whatever James said, however he said it.
    # Falls back to regex clean_query() if Ollama is unavailable.
    # ─────────────────────────────────────────────

    @staticmethod
    def _try_extract_with_model(model: str, user_input: str, context_block: str) -> "str | None":
        """
        Attempt query extraction with a specific model.
        Returns the extracted query string, or None if it failed or produced garbage.
        """
        try:
            resp = requests.post(
                OLLAMA_URL,
                json={
                    "model": model,
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
                                "  'i want a good list of cases that fit a Threadripper and 4 GPUs' → 'workstation cases Threadripper 4 GPU support'\n"
                                "  [context: discussed Threadripper CPUs] 'did you gather the information?' → 'AMD Threadripper CPU specs'\n"
                                "  [context: discussed Minecraft mods] 'can you look that up?' → 'best Minecraft mods'\n"
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
            # Sanity check — must be a reasonable length query, not the full input
            if 2 <= len(query.split()) <= 12 and len(query) < 150:
                return query
            return None
        except Exception:
            return None

    @staticmethod
    def extract_query(user_input: str, recent_memory: list = None) -> str:
        """
        Extract a clean, searchable query from natural language.
        Accepts optional recent_memory to resolve vague references like
        "did you get that?" or "can you look that up?" where the actual
        topic lives in the previous conversation turn.

        Fallback chain:
          1. Qwen 7b (primary — fast, context-aware when loaded)
          2. llama3.2 (secondary — always loaded as Hayeong's fallback model)
          3. clean_query() regex (last resort — dumb but never fails)
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

        # ── Tier 1: Qwen 7b ──
        query = WebSearch._try_extract_with_model(QUERY_MODEL, user_input, context_block)
        if query:
            _log(f"LLM extracted query [{QUERY_MODEL}]: {query!r} (from: {user_input[:60]!r})")
            return query

        _log(f"Qwen 7b extraction failed — trying llama3.2 fallback")

        # ── Tier 2: llama3.2 ──
        query = WebSearch._try_extract_with_model("llama3.2:latest", user_input, context_block)
        if query:
            _log(f"LLM extracted query [llama3.2 fallback]: {query!r} (from: {user_input[:60]!r})")
            return query

        _log(f"llama3.2 extraction also failed — using regex fallback")

        # ── Tier 3: regex clean_query ──
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

        For long rambling inputs where LLM extraction failed, this also
        applies heuristics to pull the actual topic out of the sentence.
        """
        strip_phrases = [
            r"(?i)^(search for|look up|google|find out about|find|search)\s+",
            r"(?i)^(what'?s the latest (on|about|for|with))\s+",
            r"(?i)^(what'?s the current|what is the current)\s+",
            r"(?i)^(news about|latest news (on|about))\s+",
            r"(?i)^(can you (search|look up|find|check|look some up|list))\s+",
            r"(?i)^(hey hayeong[,:]?\s+)",
            r"(?i)^(hayeong[,:]?\s+)",
            # Strip common filler openers
            r"(?i)^(i (want|need|would like|was wondering if you could|was hoping))\s+",
            r"(?i)^(can you (help me|give me|show me|tell me|find me))\s+",
            r"(?i)^(some information (on|about|for)\s+)",
            r"(?i)^(a (good )?(list|set) of\s+)",
            r"(?i)^(information (on|about)\s+)",
        ]
        q = user_input.strip()
        for pattern in strip_phrases:
            q = re.sub(pattern, "", q, flags=re.IGNORECASE).strip()

        # If the result is still very long (LLM extraction failed and regex
        # didn't clean it enough), apply a harder heuristic:
        # find the first meaningful noun phrase after stripping filler words.
        if len(q.split()) > 15:
            # Strip trailing "can you look some up for me" style closers
            q = re.sub(r"(?i)[,.]?\s*(can you look (some|them|it)? ?(up|into) (for me)?\.?)?\s*$", "", q).strip()
            q = re.sub(r"(?i)\s*(for me|please|real quick|right now|right away)\s*[,.]?", "", q).strip()
            # If still long, truncate to first 12 meaningful words
            words = q.split()
            if len(words) > 12:
                q = " ".join(words[:12])

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