# migrate_memory.py
# Run this ONCE to import Hayeong's existing memory.json into ChromaDB.
# Safe to run again — duplicates are handled automatically.
#
# Usage:
#   python migrate_memory.py

from long_term_memory import import_from_memory_json, memory_stats

print("Migrating memory.json → ChromaDB...\n")
count = import_from_memory_json("memory.json")
stats = memory_stats()
print(f"\nChromaDB now contains {stats['total_memories']} total memories.")
print("Migration complete — Hayeong's history is now searchable.")