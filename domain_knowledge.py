"""
domain_knowledge.py
Per-domain abstracted knowledge store for the reasoning LLM.

Backed by JSON files in hayeong_knowledge/, one per domain.
Thread-safe via filelock (same pattern as state_manager.py).

Write path: reasoning LLM (14b) writes via reasoning_loop.py.
Read path:  both LLMs inject it into prompts.

EPISODIC (ChromaDB): specific events — "James mined coal at Y16 on Tuesday"
DOMAIN   (this):     abstracted knowledge — "Coal ore spawns most between Y0 and Y16"
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

try:
    from filelock import FileLock
    _FILELOCK_AVAILABLE = True
except ImportError:
    _FILELOCK_AVAILABLE = False

BASE_DIR      = Path(__file__).parent
KNOWLEDGE_DIR = BASE_DIR / "hayeong_knowledge"
KNOWLEDGE_DIR.mkdir(exist_ok=True)

KNOWN_DOMAINS = [
    "minecraft", "blender", "image_gen",
    "music_gen", "coding", "james", "general",
]


# ─────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────

def _domain_path(domain: str) -> Path:
    return KNOWLEDGE_DIR / f"{domain}.json"


def _lock(domain: str):
    if _FILELOCK_AVAILABLE:
        return FileLock(str(KNOWLEDGE_DIR / f"{domain}.lock"), timeout=3)
    import contextlib
    return contextlib.nullcontext()


def _read(domain: str) -> dict:
    path = _domain_path(domain)
    if not path.exists():
        return {"domain": domain, "version": 1, "last_updated": "", "knowledge": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"domain": domain, "version": 1, "last_updated": "", "knowledge": []}


def _write(domain: str, data: dict):
    data["last_updated"] = datetime.now().isoformat()
    _domain_path(domain).write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────

def get_knowledge(domain: str, category: str = None, limit: int = 20) -> list:
    """Load knowledge for a domain. Optionally filter by category. Returns sorted by confidence desc."""
    with _lock(domain):
        data = _read(domain)
    entries = data.get("knowledge", [])
    if category:
        entries = [e for e in entries if e.get("category") == category]
    return sorted(entries, key=lambda e: e.get("confidence", 0), reverse=True)[:limit]


def add_knowledge(domain: str, content: str, category: str,
                  source: str, confidence: float = 0.6) -> str:
    """Add a new knowledge entry. Returns the new entry's ID."""
    entry_id = f"{domain[:4]}_{uuid.uuid4().hex[:6]}"
    entry = {
        "id":                  entry_id,
        "category":            category,
        "content":             content,
        "confidence":          min(1.0, max(0.0, confidence)),
        "source":              source,
        "last_reinforced":     datetime.now().isoformat(),
        "reinforcement_count": 1,
        "status":              "active",
    }
    with _lock(domain):
        data = _read(domain)
        data["knowledge"].append(entry)
        _write(domain, data)
    return entry_id


def reinforce_knowledge(domain: str, entry_id: str, confidence_delta: float = 0.05):
    """Called when existing knowledge is confirmed by experience. Raises confidence."""
    with _lock(domain):
        data = _read(domain)
        for entry in data["knowledge"]:
            if entry["id"] == entry_id:
                entry["confidence"]          = min(1.0, entry.get("confidence", 0.6) + confidence_delta)
                entry["reinforcement_count"] = entry.get("reinforcement_count", 1) + 1
                entry["last_reinforced"]     = datetime.now().isoformat()
                if entry.get("status") == "uncertain":
                    entry["status"] = "active"
                break
        _write(domain, data)


def contradict_knowledge(domain: str, entry_id: str, confidence_delta: float = 0.1):
    """Called when existing knowledge is contradicted. Lowers confidence.
    Below 0.2 the entry is marked 'uncertain' — never hard-deleted."""
    with _lock(domain):
        data = _read(domain)
        for entry in data["knowledge"]:
            if entry["id"] == entry_id:
                entry["confidence"] = max(0.0, entry.get("confidence", 0.6) - confidence_delta)
                if entry["confidence"] < 0.2:
                    entry["status"] = "uncertain"
                break
        _write(domain, data)


def update_knowledge(domain: str, entry_id: str, new_content: str):
    """Update the text content of an existing knowledge entry."""
    with _lock(domain):
        data = _read(domain)
        for entry in data["knowledge"]:
            if entry["id"] == entry_id:
                entry["content"]         = new_content
                entry["last_reinforced"] = datetime.now().isoformat()
                break
        _write(domain, data)


def format_for_prompt(domain: str, category: str = None, limit: int = 10) -> str:
    """Format domain knowledge for injection into an LLM prompt.
    Only includes entries with confidence >= 0.5. Sorted by confidence desc."""
    entries = get_knowledge(domain, category=category, limit=limit * 3)
    entries = [
        e for e in entries
        if e.get("confidence", 0) >= 0.5 and e.get("status", "active") == "active"
    ][:limit]
    if not entries:
        return ""
    lines = [f"HAYEONG'S {domain.upper()} KNOWLEDGE:"]
    for e in entries:
        conf = e.get("confidence", 0)
        conf_label = "high" if conf >= 0.75 else "medium"
        lines.append(f"[{e.get('category', 'general')}] {e['content']} (confidence: {conf_label})")
    return "\n".join(lines)


def search_knowledge(domain: str, query: str, limit: int = 5) -> list:
    """Simple keyword search across knowledge content for a domain."""
    entries = get_knowledge(domain, limit=1000)
    query_words = [w for w in query.lower().split() if len(w) > 2]
    scored = []
    for e in entries:
        content_lower = e.get("content", "").lower()
        score = sum(1 for w in query_words if w in content_lower)
        if score > 0:
            scored.append((score, e))
    scored.sort(key=lambda x: (-x[0], -x[1].get("confidence", 0)))
    return [e for _, e in scored[:limit]]


def get_all_domains() -> list:
    """Return list of all domains that have knowledge files."""
    return [p.stem for p in KNOWLEDGE_DIR.glob("*.json")]
