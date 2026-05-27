"""
long_term_memory.py — backward-compatibility shim.
All calls delegate to the new memory system (memory_manager, memory_writer, memory_retriever).
Existing code that imports from this module continues to work unchanged.
New code should import from memory.memory_manager / memory_retriever / memory_writer directly.
"""

from memory.memory_manager import remember, recall, memory_stats, get_collection

# ─────────────────────────────────────────────
# CATEGORY CONSTANTS — preserved for existing callers
# ─────────────────────────────────────────────
CATEGORY_CONVERSATION = "conversation"
CATEGORY_FACT         = "fact"
CATEGORY_EMOTION      = "emotion"
CATEGORY_MINECRAFT    = "minecraft"
CATEGORY_PREFERENCE   = "preference"


def recall_for_prompt(query: str, n_results: int = 5) -> str:
    """Retrieve and format memories for prompt injection."""
    try:
        from memory.memory_retriever import recall_for_prompt as _rfp
        return _rfp(query, n_results)
    except Exception:
        return ""


def categorize(text: str) -> str:
    """Guess the best category for a piece of text."""
    text_lower = text.lower()

    fact_keywords    = ["my name is", "i am", "i work", "i live", "i have", "i'm from",
                        "my favorite", "i was born", "my job", "i study", "i play"]
    pref_keywords    = ["i love", "i hate", "i like", "i don't like", "i prefer",
                        "my favorite", "i enjoy", "i can't stand", "i really like"]
    emotion_keywords = ["i feel", "i'm sad", "i'm happy", "stressed", "anxious",
                        "excited", "scared", "angry", "lonely", "proud", "hurts"]
    mc_keywords      = ["[mc]", "minecraft", "creeper", "diamond", "respawn", "inventory"]

    if any(k in text_lower for k in mc_keywords):
        return CATEGORY_MINECRAFT
    if any(k in text_lower for k in emotion_keywords):
        return CATEGORY_EMOTION
    if any(k in text_lower for k in pref_keywords):
        return CATEGORY_PREFERENCE
    if any(k in text_lower for k in fact_keywords):
        return CATEGORY_FACT
    return CATEGORY_CONVERSATION


def import_from_memory_json(memory_json_path: str = "memory.json"):
    """
    One-time import of existing memory.json into ChromaDB.
    Safe to run multiple times — each entry gets a fresh UUID.
    """
    import json
    import os
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

    print(f"Imported {imported} memories from {memory_json_path} into ChromaDB")
    return imported
