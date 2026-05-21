# chroma_db/

This folder is Hayeong's long-term vector memory store, powered by ChromaDB.

## What Lives Here

At runtime, ChromaDB creates and manages:
- `chroma.sqlite3` — the main database file
- `index/` — HNSW vector index files
- Various `.bin` files for embedding storage

These files are **excluded from the repository** because they contain
private data — every meaningful conversation, personal fact, emotional
moment, and learned preference stored as semantic vector embeddings.

## Why The Folder Is Here

The folder exists in the repo so that:
- The memory architecture is visible and documented
- New setups know exactly where the database should live
- Claude Code and Hayeong herself can reason about where memory is stored

## What Creates It

`Memory/long_term_memory.py` initializes ChromaDB on first use:

```python
_client = chromadb.PersistentClient(path="chroma_db")
```

The database is created automatically the first time Hayeong runs.
No manual setup is needed.

## What Gets Stored Here

Memories are tagged by category:
- `conversation` — general exchanges with Jameson
- `fact` — things Jameson has shared about himself
- `emotion` — emotionally significant moments
- `minecraft` — in-game events and interactions
- `preference` — likes, dislikes, interests

## Retrieval

Memories are retrieved by semantic similarity — Hayeong queries what's
relevant to the current moment, not a keyword search. See
`Memory/long_term_memory.py` for the full implementation.
