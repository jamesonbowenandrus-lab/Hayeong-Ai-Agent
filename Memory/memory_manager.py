"""
memory_manager.py
Central interface for all of Hayeong's memory operations.
Replaces long_term_memory.py — same function signatures for backward compatibility.

Architecture note:
    get_client() / get_collection() are defined here.
    memory_writer and memory_retriever import from here.
    To avoid circular imports, remember() and recall() use lazy imports
    inside the function body rather than module-level imports.
"""

import chromadb
from pathlib import Path
from datetime import date

CHROMA_DIR = Path(__file__).parent / "chromadb"

_client = None


def get_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return _client


def get_collection(name: str):
    return get_client().get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


def memory_stats() -> dict:
    """Return counts across all collections."""
    client = get_client()
    stats = {}
    for name in ("episodes", "knowledge", "relationships", "working", "hayeong_memory"):
        try:
            col = client.get_collection(name)
            stats[name] = col.count()
        except Exception:
            stats[name] = 0
    return stats


# ─────────────────────────────────────────────
# BACKWARD-COMPATIBLE API
# Existing callers of remember() / recall() continue to work.
# Lazy imports inside functions avoid circular dependencies.
# ─────────────────────────────────────────────

def remember(content: str, category: str = "conversation",
             metadata: dict = None, speaker: str = None):
    """Backward-compatible write — routes to correct collection via memory_writer."""
    try:
        from memory.memory_writer import write_memory
        write_memory(
            content=content,
            category=category,
            metadata=metadata or {},
            speaker=speaker,
        )
    except Exception as e:
        print(f"[memory_manager] remember() failed: {e}")


def recall(query: str, n_results: int = 5,
           category: str = None, since_date: str = None) -> list:
    """Backward-compatible read — queries all collections via memory_retriever."""
    try:
        from memory.memory_retriever import recall_all
        return recall_all(
            query=query,
            n_results=n_results,
            category_filter=category,
            since_date=since_date,
        )
    except Exception as e:
        print(f"[memory_manager] recall() failed: {e}")
        return []
