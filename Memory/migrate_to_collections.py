"""
migrate_to_collections.py
One-time migration from hayeong_memory to the four new collections.

Run manually:
    python Memory/migrate_to_collections.py

Safe to run multiple times — each migrated memory gets a fresh UUID,
so re-running adds duplicates. Check memory_stats() first.
"""

import sys
from pathlib import Path

# Ensure memory/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from memory.memory_manager import get_collection, memory_stats
from memory.memory_writer import write_memory, write_knowledge, write_relationship


def migrate():
    print("Memory stats before migration:")
    print(memory_stats())
    print()

    try:
        old_col = get_collection("hayeong_memory")
        total   = old_col.count()
    except Exception as e:
        print(f"Could not access hayeong_memory collection: {e}")
        return

    if total == 0:
        print("hayeong_memory is empty — nothing to migrate.")
        return

    print(f"Migrating {total} memories from hayeong_memory...")
    results  = old_col.get(include=["documents", "metadatas"])
    migrated = 0
    skipped  = 0

    for doc, meta in zip(results["documents"], results["metadatas"]):
        if not doc or not doc.strip():
            skipped += 1
            continue

        category = meta.get("category", "conversation")
        speaker  = meta.get("speaker", "unknown")

        try:
            if category == "fact":
                write_knowledge(
                    content=doc,
                    domain=meta.get("topic", "general"),
                    source=speaker,
                )
            elif category == "preference":
                write_relationship(
                    content=doc,
                    person="james",
                    pattern_type="preference",
                )
            else:
                write_memory(
                    content=doc,
                    category=category,
                    speaker=speaker,
                    metadata={"topic": meta.get("topic", "general")},
                )
            migrated += 1
        except Exception as e:
            print(f"  [SKIP] Could not migrate entry: {e}")
            skipped += 1

    print(f"Migration complete — {migrated} migrated, {skipped} skipped.")
    print("The original hayeong_memory collection is untouched.")
    print()
    print("Memory stats after migration:")
    print(memory_stats())


if __name__ == "__main__":
    migrate()
