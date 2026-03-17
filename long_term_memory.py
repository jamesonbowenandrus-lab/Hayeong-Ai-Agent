# long_term_memory.py
# Hayeong's long-term memory system using ChromaDB.
# Stores every meaningful exchange as a semantic vector.
# Retrieves the most relevant past memories for any current moment.
#
# This sits UNDER memory.json — that handles recent session context,
# ChromaDB handles everything she's ever known about you.

import chromadb
import hashlib
import json
import os
from datetime import datetime

# -------------------------
# Config
# -------------------------
CHROMA_DIR    = "chroma_db"          # where the database lives on disk
COLLECTION    = "hayeong_memory"     # name of the memory collection
MAX_RESULTS   = 5                    # how many relevant memories to retrieve
MIN_RELEVANCE = 0.3                  # similarity threshold (0-1, lower = more inclusive)

# Memory categories — used to tag what kind of memory this is
CATEGORY_CONVERSATION = "conversation"   # general chat
CATEGORY_FACT         = "fact"           # something James told her about himself
CATEGORY_EMOTION      = "emotion"        # emotional moment or significant feeling
CATEGORY_MINECRAFT    = "minecraft"      # in-game events and interactions
CATEGORY_PREFERENCE   = "preference"     # likes, dislikes, interests

# -------------------------
# Initialize ChromaDB
# -------------------------
_client     = None
_collection = None

def get_collection():
    global _client, _collection
    if _collection is not None:
        return _collection

    os.makedirs(CHROMA_DIR, exist_ok=True)
    _client     = chromadb.PersistentClient(path=CHROMA_DIR)
    _collection = _client.get_or_create_collection(
        name=COLLECTION,
        metadata={"hnsw:space": "cosine"}  # cosine similarity for semantic search
    )
    return _collection

# -------------------------
# Store a memory
# -------------------------
def remember(
    content: str,
    category: str = CATEGORY_CONVERSATION,
    metadata: dict = None,
    speaker: str = None,
):
    """
    Store a memory in ChromaDB.

    content  — the text to remember (what was said or what happened)
    category — type of memory (conversation, fact, emotion, minecraft, preference)
    metadata — any extra context (mood, location, topic, etc.)
    speaker  — "james" or "hayeong" or None for events
    """
    if not content or not content.strip():
        return

    col = get_collection()

    # Build metadata dict
    meta = {
        "timestamp":  datetime.now().isoformat(),
        "category":   category,
        "speaker":    speaker or "unknown",
        "date":       datetime.now().strftime("%Y-%m-%d"),
    }
    if metadata:
        # ChromaDB only accepts str/int/float/bool values
        for k, v in metadata.items():
            if isinstance(v, (str, int, float, bool)):
                meta[k] = v

    # Generate a stable ID from content + timestamp so duplicates are avoided
    uid = hashlib.md5((content + meta["timestamp"]).encode()).hexdigest()

    col.add(
        documents=[content],
        metadatas=[meta],
        ids=[uid],
    )
    return uid

# -------------------------
# Retrieve relevant memories
# -------------------------
def recall(
    query: str,
    n_results: int = MAX_RESULTS,
    category: str = None,
    since_date: str = None,
) -> list[dict]:
    """
    Find memories most relevant to the current query.

    query      — what we're looking for (current message or situation)
    n_results  — how many memories to return
    category   — filter by category if needed
    since_date — only return memories after this date (YYYY-MM-DD)

    Returns list of dicts: {content, category, speaker, timestamp, relevance}
    """
    col = get_collection()

    # Check if collection has anything
    if col.count() == 0:
        return []

    # Build filter
    where = {}
    if category:
        where["category"] = category
    if since_date:
        where["date"] = {"$gte": since_date}

    try:
        results = col.query(
            query_texts=[query],
            n_results=min(n_results, col.count()),
            where=where if where else None,
        )
    except Exception as e:
        print(f"⚠️ Memory recall error: {e}")
        return []

    memories = []
    if not results["documents"] or not results["documents"][0]:
        return []

    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        relevance = 1 - dist  # convert distance to similarity score
        if relevance >= MIN_RELEVANCE:
            memories.append({
                "content":   doc,
                "category":  meta.get("category", "unknown"),
                "speaker":   meta.get("speaker", "unknown"),
                "timestamp": meta.get("timestamp", ""),
                "date":      meta.get("date", ""),
                "relevance": round(relevance, 3),
            })

    # Sort by relevance descending
    memories.sort(key=lambda x: x["relevance"], reverse=True)
    return memories

# -------------------------
# Format memories for prompt injection
# -------------------------
def recall_for_prompt(query: str, n_results: int = MAX_RESULTS) -> str:
    """
    Retrieve relevant memories and format them for injection into a prompt.
    Returns empty string if no relevant memories found.
    """
    memories = recall(query, n_results=n_results)
    if not memories:
        return ""

    lines = ["RELEVANT MEMORIES (from past conversations):"]
    for m in memories:
        date = m["date"] or "unknown date"
        speaker = m["speaker"].capitalize()
        lines.append(f"  [{date}] {speaker}: {m['content']}")

    return "\n".join(lines)

# -------------------------
# Import existing memory.json into ChromaDB
# -------------------------
def import_from_memory_json(memory_json_path: str = "memory.json"):
    """
    One-time import of existing memory.json into ChromaDB.
    Safe to run multiple times — duplicates are handled by ID hashing.
    """
    if not os.path.exists(memory_json_path):
        print(f"No memory.json found at {memory_json_path}")
        return 0

    with open(memory_json_path, "r", encoding="utf-8") as f:
        entries = json.load(f)

    imported = 0
    for entry in entries:
        role    = entry.get("role", "unknown")
        content = entry.get("content", "").strip()
        if not content:
            continue

        speaker  = "james" if role == "user" else "hayeong"
        category = CATEGORY_MINECRAFT if content.startswith("[MC]") else CATEGORY_CONVERSATION

        remember(content, category=category, speaker=speaker)
        imported += 1

    print(f"✅ Imported {imported} memories from memory.json into ChromaDB")
    return imported

# -------------------------
# Smart categorizer
# Detects what kind of memory something is based on content
# -------------------------
def categorize(text: str) -> str:
    """Guess the best category for a piece of text."""
    text_lower = text.lower()

    fact_keywords = ["my name is", "i am", "i work", "i live", "i have", "i'm from",
                     "my favorite", "i was born", "my job", "i study", "i play"]
    pref_keywords = ["i love", "i hate", "i like", "i don't like", "i prefer",
                     "my favorite", "i enjoy", "i can't stand", "i really like"]
    emotion_keywords = ["i feel", "i'm sad", "i'm happy", "stressed", "anxious",
                        "excited", "scared", "angry", "lonely", "proud", "hurts"]
    mc_keywords = ["[mc]", "minecraft", "creeper", "diamond", "respawn", "inventory"]

    if any(k in text_lower for k in mc_keywords):
        return CATEGORY_MINECRAFT
    if any(k in text_lower for k in emotion_keywords):
        return CATEGORY_EMOTION
    if any(k in text_lower for k in pref_keywords):
        return CATEGORY_PREFERENCE
    if any(k in text_lower for k in fact_keywords):
        return CATEGORY_FACT
    return CATEGORY_CONVERSATION

# -------------------------
# Stats
# -------------------------
def memory_stats() -> dict:
    """Return basic stats about what's stored."""
    col = get_collection()
    total = col.count()
    return {"total_memories": total, "db_path": CHROMA_DIR}

# -------------------------
# Quick test
# -------------------------
if __name__ == "__main__":
    print("Testing ChromaDB long-term memory...\n")

    # Store some test memories
    remember("James told me his favorite game is Minecraft", category=CATEGORY_PREFERENCE, speaker="hayeong")
    remember("James said he's been stressed about work lately", category=CATEGORY_EMOTION, speaker="james")
    remember("We found a dungeon together at coordinates 120, 45, -330", category=CATEGORY_MINECRAFT, speaker="hayeong")
    remember("James mentioned he works in IT", category=CATEGORY_FACT, speaker="james")
    remember("James said he doesn't like spicy food", category=CATEGORY_PREFERENCE, speaker="james")

    print("Stored 5 test memories.\n")

    # Test retrieval
    query = "what does James like to do"
    print(f"Query: '{query}'")
    results = recall(query)
    for r in results:
        print(f"  [{r['relevance']}] {r['content']}")

    print()
    query2 = "how is James feeling"
    print(f"Query: '{query2}'")
    results2 = recall(query2)
    for r in results2:
        print(f"  [{r['relevance']}] {r['content']}")

    print(f"\nStats: {memory_stats()}")
    print("\n✅ ChromaDB memory system working correctly")
