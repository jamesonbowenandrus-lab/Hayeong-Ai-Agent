"""
memory_writer.py
Routes memory writes to the correct collection.
Scores importance at write time — never at retrieval time.
"""

import uuid
from datetime import datetime, date, timedelta

from memory.memory_manager import get_collection


# ─────────────────────────────────────────────
# IMPORTANCE SCORING
# Score 0.0–1.0 based on content signals at write time.
# High importance = survives decay longer, retrieved preferentially.
# ─────────────────────────────────────────────

_HIGH_SIGNALS = [
    "my name", "i am", "i was born", "my family", "my dad", "my mom",
    "my son", "my daughter", "i love you", "i miss", "i'm scared",
    "i'm proud", "i'm really happy", "that meant a lot", "i appreciate",
    "this is important", "never forget", "remember this",
    "always", "never", "i want you to", "please remember",
    "my favorite", "i hate", "i can't stand",
    "we finished", "we built", "we completed", "achieved",
]

_LOW_SIGNALS = [
    "ok", "sure", "got it", "okay", "yeah", "yep", "uh huh",
    "thanks", "thank you", "sounds good", "alright",
    "let me know", "no problem",
]


def _score_importance(content: str, emotional_weight: float = 0.0,
                      speaker: str = "unknown") -> float:
    """Score importance 0.0–1.0 at write time."""
    text  = content.lower()
    score = 0.3  # baseline

    word_count = len(content.split())
    if word_count < 4:
        score -= 0.15
    elif word_count > 20:
        score += 0.10

    for signal in _HIGH_SIGNALS:
        if signal in text:
            score += 0.15
            break

    text_stripped = text.strip()
    for signal in _LOW_SIGNALS:
        if text_stripped == signal or text_stripped.startswith(signal + " "):
            score -= 0.20
            break

    # Emotional weight contributes 20% of final score
    score = score * 0.8 + emotional_weight * 0.2

    # James's words slightly more important (it's his memory)
    if speaker == "james":
        score += 0.05

    return max(0.0, min(1.0, round(score, 3)))


def _uid() -> str:
    return uuid.uuid4().hex


def _category_to_collection(category: str) -> str:
    return {
        "conversation": "episodes",
        "emotion":      "episodes",
        "minecraft":    "episodes",
        "fact":         "knowledge",
        "preference":   "relationships",
    }.get(category, "episodes")


# ─────────────────────────────────────────────
# PUBLIC WRITE FUNCTIONS
# ─────────────────────────────────────────────

def write_memory(content: str, category: str = "conversation",
                 metadata: dict = None, speaker: str = None,
                 emotional_weight: float = 0.0):
    """
    Primary write entry point. Routes based on category.
    Called by memory_manager.remember() for backward compatibility.
    """
    if not content or len(content.split()) < 3:
        return  # filter noise

    metadata   = metadata or {}
    speaker    = speaker or "unknown"
    col_name   = _category_to_collection(category)
    importance = float(metadata.get("importance", _score_importance(content, emotional_weight, speaker)))

    col  = get_collection(col_name)
    meta = {
        "timestamp":       datetime.now().isoformat(),
        "date":            date.today().isoformat(),
        "speaker":         speaker,
        "topic":           str(metadata.get("topic", "general")),
        "emotional_weight": float(emotional_weight),
        "importance":      importance,
        "protected":       bool(metadata.get("protected", importance >= 0.8)),
        "last_accessed":   date.today().isoformat(),
        "access_count":    0,
        "consolidated":    bool(metadata.get("consolidated", False)),
        "source_count":    int(metadata.get("source_count", 1)),
    }
    col.add(documents=[content], metadatas=[meta], ids=[_uid()])


def write_knowledge(content: str, domain: str = "general",
                    source: str = "hayeong", importance: float = 0.5,
                    protected: bool = False):
    """Write a fact or domain knowledge entry."""
    if not content or not content.strip():
        return

    col  = get_collection("knowledge")
    meta = {
        "domain":        domain,
        "source":        source,
        "date_learned":  date.today().isoformat(),
        "importance":    float(importance),
        "protected":     bool(protected),
        "last_accessed": date.today().isoformat(),
        "access_count":  0,
        "verified":      True,
    }
    col.add(documents=[content], metadatas=[meta], ids=[_uid()])


def write_relationship(content: str, person: str = "james",
                       pattern_type: str = "behavior",
                       confidence: float = 0.7, importance: float = 0.7):
    """Write a relationship pattern or observation."""
    if not content or not content.strip():
        return

    col   = get_collection("relationships")
    today = date.today().isoformat()
    meta  = {
        "person":            person,
        "pattern_type":      pattern_type,
        "confidence":        float(confidence),
        "first_observed":    today,
        "last_observed":     today,
        "observation_count": 1,
        "importance":        float(importance),
        "protected":         True,  # relationship memories are protected by default
    }
    col.add(documents=[content], metadatas=[meta], ids=[_uid()])


def write_working(content: str, task_id: str, task_type: str = "general",
                  status: str = "active", importance: float = 0.5,
                  expire_days: int = 14):
    """Write or update a working memory entry. Uses task_id as the record key."""
    if not content or not content.strip():
        return

    col     = get_collection("working")
    today   = date.today()
    expires = (today + timedelta(days=expire_days)).isoformat()
    meta    = {
        "task_id":      task_id,
        "task_type":    task_type,
        "status":       status,
        "created_at":   today.isoformat(),
        "last_updated": today.isoformat(),
        "expires_at":   expires,
        "importance":   float(importance),
        "protected":    False,
    }
    # Overwrite existing entry with same task_id
    try:
        col.delete(ids=[task_id])
    except Exception:
        pass
    col.add(documents=[content], metadatas=[meta], ids=[task_id])
