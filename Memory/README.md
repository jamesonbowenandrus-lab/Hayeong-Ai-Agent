# Memory

Hayeong's episodic memory, relationship data, and personal knowledge.

## Structure

```
Memory/
  chromadb/         Active ChromaDB vector store (private — not tracked)
  chroma_db/        Orphaned placeholder — do not use (see note below)
  relationships/    Relationship memory files (private — not tracked)
  james/            Personal documents from James to Hayeong (private — not tracked)
  backups/          Periodic state snapshots (private — not tracked)
```

## Active Database

`Memory/chromadb/` is the active ChromaDB instance.
Managed by `memory/memory_manager.py`, `memory_decay.py`, `memory_consolidator.py`.
Path set in `memory_manager.py`: `Path(__file__).parent / "chromadb"`

## Orphaned Folder Note

`Memory/chroma_db/` (with underscore) is an orphaned placeholder from an earlier
path configuration used in April 2026 backup files. It contains only `.gitkeep`
and this note. The active code does not reference it.
Do not put data here. Do not delete it until a deliberate cleanup pass confirms
all references are resolved.

## Privacy

All memory data files are private and excluded from the public repository.
The Python files managing this layer are public to demonstrate the architecture.
Personal data is backed up to a private repository.
