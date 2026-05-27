"""
memory_retriever.py
Retrieves memories from the correct collections.
Updates access tracking on every retrieval.
Formats results for prompt injection.
"""

from datetime import date

from memory.memory_manager import get_collection

MIN_RELEVANCE      = 0.35   # cosine similarity threshold — below this, not returned
MAX_PER_COLLECTION = 4      # max results per collection in multi-collection queries


def _update_access(collection_name: str, ids: list):
    """Mark retrieved memories as accessed — used by decay system."""
    if not ids:
        return
    col = get_collection(collection_name)
    try:
        results = col.get(ids=ids, include=["metadatas"])
        if not results or not results.get("metadatas"):
            return
        for i, meta in enumerate(results["metadatas"]):
            meta["last_accessed"] = date.today().isoformat()
            meta["access_count"]  = int(meta.get("access_count", 0)) + 1
            col.update(ids=[ids[i]], metadatas=[meta])
    except Exception:
        pass  # access tracking failure is non-fatal


def _query_collection(collection_name: str, query: str,
                      n_results: int = 5, where: dict = None) -> list:
    """Query one collection and return formatted results."""
    col = get_collection(collection_name)
    if col.count() == 0:
        return []

    try:
        results = col.query(
            query_texts=[query],
            n_results=min(n_results, col.count()),
            where=where if where else None,
        )
    except Exception:
        return []

    if not results.get("documents") or not results["documents"][0]:
        return []

    memories       = []
    ids_to_update  = []

    for doc, meta, dist, uid in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
        results["ids"][0],
    ):
        relevance = 1.0 - dist
        if relevance < MIN_RELEVANCE:
            continue

        importance      = float(meta.get("importance", 0.3))
        boosted         = relevance * (1.0 + importance * 0.15)

        memories.append({
            "content":    doc,
            "collection": collection_name,
            "relevance":  round(boosted, 3),
            "importance": importance,
            "metadata":   meta,
            "id":         uid,
        })
        ids_to_update.append(uid)

    if ids_to_update:
        _update_access(collection_name, ids_to_update)

    return sorted(memories, key=lambda x: x["relevance"], reverse=True)


# ─────────────────────────────────────────────
# PUBLIC RECALL FUNCTIONS
# ─────────────────────────────────────────────

def recall_episodes(query: str, n_results: int = 5,
                    since_date: str = None, topic: str = None) -> list:
    """Recall episodic memories — what happened."""
    where = {}
    if since_date:
        where["date"] = {"$gte": since_date}
    if topic:
        where["topic"] = topic
    return _query_collection("episodes", query, n_results, where or None)


def recall_knowledge(query: str, n_results: int = 4, domain: str = None) -> list:
    """Recall knowledge facts."""
    where = {"domain": domain} if domain else None
    return _query_collection("knowledge", query, n_results, where)


def recall_relationships(query: str, person: str = "james",
                         n_results: int = 3) -> list:
    """Recall relationship patterns."""
    where = {"person": person} if person else None
    return _query_collection("relationships", query, n_results, where)


def recall_working(task_type: str = None) -> list:
    """Recall active working memory entries."""
    col = get_collection("working")
    if col.count() == 0:
        return []
    try:
        where   = {"status": "active"}
        if task_type:
            where["task_type"] = task_type
        results = col.get(where=where, include=["documents", "metadatas"])
        today   = date.today().isoformat()
        memories = []
        for doc, meta, uid in zip(
            results["documents"], results["metadatas"], results["ids"]
        ):
            if meta.get("expires_at", "9999-99-99") < today:
                continue
            memories.append({"content": doc, "metadata": meta, "id": uid})
        return memories
    except Exception:
        return []


def recall_all(query: str, n_results: int = 5,
               category_filter: str = None, since_date: str = None) -> list:
    """
    Multi-collection recall. Queries all collections and deduplicates.
    Also queries legacy hayeong_memory collection as fallback for older data.
    """
    all_memories = []

    all_memories.extend(recall_episodes(query, MAX_PER_COLLECTION, since_date))
    all_memories.extend(recall_knowledge(query, 2))
    all_memories.extend(recall_relationships(query, n_results=2))

    # Legacy fallback — query old collection if it has data
    legacy = _query_collection("hayeong_memory", query, 3)
    all_memories.extend(legacy)

    # Deduplicate by first 80 chars of content
    seen   = set()
    unique = []
    for m in all_memories:
        key = m["content"][:80]
        if key not in seen:
            seen.add(key)
            unique.append(m)

    unique.sort(key=lambda x: x["relevance"], reverse=True)
    return unique[:n_results]


def recall_for_prompt(query: str, n_results: int = 5) -> str:
    """
    Retrieve and format memories for prompt injection.
    Called by system_prompt_builder.py (and hayeong_core.py).
    Returns empty string if no relevant memories found.
    """
    memories = recall_all(query=query, n_results=n_results)
    if not memories:
        return ""

    lines = ["[RELEVANT MEMORIES]"]
    for m in memories:
        meta     = m.get("metadata", {})
        date_str = meta.get("date", meta.get("date_learned", "unknown date"))
        speaker  = meta.get("speaker", "")
        prefix   = f"[{date_str}]"
        if speaker and speaker not in ("unknown", "event"):
            prefix += f" {speaker.capitalize()}:"
        lines.append(f"  {prefix} {m['content']}")
    lines.append("[END MEMORIES]")

    return "\n".join(lines)
