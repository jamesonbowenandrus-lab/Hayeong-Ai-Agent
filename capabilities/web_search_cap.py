# capabilities/web_search_cap.py
# Web search capability — migrated out of main.py.
#
# Handles: web_search action from context_router
# Supports: conversational delivery and document delivery modes

from capability_loader import result

ACTIONS = ["web_search"]

# ─────────────────────────────────────────────
# LAZY IMPORT
# Keep heavy imports out of module load time.
# ─────────────────────────────────────────────

_searcher = None

def _get_searcher():
    global _searcher
    if _searcher is None:
        try:
            from web_search import WebSearch
            _searcher = WebSearch()
        except ImportError:
            pass
    return _searcher


# ─────────────────────────────────────────────
# HANDLER
# ─────────────────────────────────────────────

def handle(action: str, user_input: str, context: dict) -> dict:
    searcher = _get_searcher()
    if searcher is None or not searcher.is_available():
        return result(
            success=False,
            speak="I don't have web search available right now.",
        )

    decision   = context.get("decision", {})
    memory     = context.get("memory", [])
    logger     = context.get("logger")
    email      = context.get("email")          # EmailBridge instance or None
    email_addr = context.get("email_address")  # James's address or None

    # ── Determine query ──
    query = decision.get("query") or WebSearch.extract_query(
        user_input, recent_memory=memory[-6:]
    )
    delivery = decision.get("delivery", "conversational")
    is_news  = any(
        kw in user_input.lower()
        for kw in ["latest news", "news about", "what's in the news",
                   "recent news", "breaking news"]
    )

    # ── Speak ack ──
    if delivery == "document":
        speak_text = "Sure, let me pull that together. I'll have the full breakdown for you shortly."
    else:
        speak_text = "Let me look that up."

    # ── Run search ──
    try:
        if is_news:
            data = {
                "query":    query,
                "results":  searcher.news(query, max_results=5),
                "full_text": {},
            }
        else:
            max_r = 6 if delivery == "document" else 4
            data  = searcher.search_and_read(
                query,
                max_results=max_r,
                fetch_top=2 if delivery == "document" else 1,
            )
    except Exception as e:
        return result(
            success=False,
            speak="I ran into a problem with the search.",
            data={"error": str(e)},
        )

    n_results = len(data.get("results", []))

    # ── Log ──
    if logger:
        try:
            logger.log_capability_used(
                "web_search", action="search", outcome="success",
                details={"query": query, "results": n_results, "delivery": delivery},
            )
        except Exception:
            pass

    # ── Document delivery ──
    if delivery == "document" and n_results > 0:
        constraints = context.get("constraints", [])
        doc_content = searcher.format_as_document(
            query, data, topic=query, constraints=constraints
        )
        doc_path  = searcher.save_document(doc_content, topic=query)
        emailed   = False

        if email and email_addr:
            try:
                import os
                with open(doc_path, "r", encoding="utf-8") as f:
                    doc_text = f.read()
                ok = email.send(
                    to=email_addr,
                    subject=f"Research: {query}",
                    body=doc_text,
                )
                emailed = bool(ok) if isinstance(ok, bool) else ok.get("success", False)
            except Exception:
                pass

        doc_note = (
            f"You emailed James the full research document for '{query}'. "
            if emailed else
            f"You saved the full research document to: {doc_path}. "
        )
        response_ctx = (
            searcher.format_for_context(query, data) +
            f"\n\n[DOCUMENT NOTE]: {doc_note}"
            "Give James your brief personal take on the most interesting findings "
            "in 2-4 sentences, then mention you've sent/saved the full breakdown."
        )
        return result(
            success=True,
            response=response_ctx,
            speak=speak_text,
            data={"query": query, "n_results": n_results,
                  "doc_path": doc_path, "emailed": emailed},
        )

    # ── Conversational delivery ──
    response_ctx = searcher.format_for_context(query, data)
    return result(
        success=True,
        response=response_ctx,
        speak=speak_text,
        data={"query": query, "n_results": n_results},
    )
