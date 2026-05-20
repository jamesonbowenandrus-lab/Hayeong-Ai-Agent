"""
domain_knowledge.py
Stores what Hayeong learns about each domain over time.
The reasoning LLM writes entries here after completing tasks.
Imported by reasoning_loop.py as: from domain_knowledge import ...
"""
import json
import uuid
from datetime import datetime
from pathlib import Path

KNOWLEDGE_FILE = Path(__file__).parent / "state" / "domain_knowledge.json"


def _load() -> dict:
    try:
        return json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict):
    KNOWLEDGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    KNOWLEDGE_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def get_all_domains() -> list:
    return list(_load().keys())


def get_knowledge(domain: str) -> list:
    return _load().get(domain, [])


def add_knowledge(
    domain: str,
    content: str,
    category: str = "general",
    source: str = "learned",
    confidence: float = 0.6,
):
    """Add a knowledge entry. Called by reasoning_loop after completed tasks."""
    data = _load()
    if domain not in data:
        data[domain] = []
    data[domain].append({
        "id":         f"kw_{uuid.uuid4().hex[:6]}",
        "content":    content,
        "category":   category,
        "source":     source,
        "confidence": round(float(confidence), 3),
        "reinforced": 0,
        "added_at":   datetime.now().isoformat(),
    })
    _save(data)


def reinforce_knowledge(domain: str, entry_id: str):
    """Increase confidence of an entry by ID."""
    data = _load()
    for entry in data.get(domain, []):
        if entry.get("id") == entry_id:
            entry["reinforced"] = entry.get("reinforced", 0) + 1
            entry["confidence"] = min(1.0, entry.get("confidence", 0.6) + 0.05)
            break
    _save(data)


def contradict_knowledge(domain: str, entry_id: str):
    """Reduce confidence of an entry by ID."""
    data = _load()
    for entry in data.get(domain, []):
        if entry.get("id") == entry_id:
            entry["confidence"] = max(0.0, entry.get("confidence", 0.6) - 0.3)
            break
    _save(data)


def format_for_prompt(domain: str, limit: int = 10) -> str:
    """Format top-confidence entries for LLM context injection."""
    entries = get_knowledge(domain)
    if not entries:
        return ""
    top = sorted(entries, key=lambda e: e.get("confidence", 0), reverse=True)[:limit]
    lines = [f"- {e['content']} (confidence: {e['confidence']:.2f})" for e in top]
    return f"Known facts about {domain}:\n" + "\n".join(lines)
