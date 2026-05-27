"""
memory_decay.py
Background memory maintenance.
Decays importance scores of unaccessed memories.
Prunes memories below threshold that are not protected.
Run once per session on startup.
"""

import json
import logging
from datetime import date
from pathlib import Path

from memory.memory_manager import get_collection

log = logging.getLogger("memory_decay")

DECAY_RATE          = 0.05    # importance lost per 7-day idle period
PRUNE_THRESHOLD     = 0.10    # importance below this → eligible for pruning
PRUNE_MIN_AGE_DAYS  = 30      # memory must be at least 30 days old to be pruned
MAX_COLLECTION_SIZE = 10_000  # force-prune lowest-importance when exceeded

DECAY_COLLECTIONS   = ("episodes", "knowledge", "hayeong_memory")

DECAY_LOG = Path(__file__).parent / "chromadb" / "decay_log.json"


def _days_since(date_str: str) -> int:
    try:
        return (date.today() - date.fromisoformat(date_str)).days
    except Exception:
        return 0


def _load_decay_log() -> dict:
    if DECAY_LOG.exists():
        try:
            return json.loads(DECAY_LOG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_decay_log(data: dict):
    DECAY_LOG.parent.mkdir(parents=True, exist_ok=True)
    DECAY_LOG.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_decay_cycle() -> dict:
    """
    Main entry point. Decays and prunes eligible memories.
    Returns summary: {"decayed": N, "pruned": N, "protected_skipped": N, "errors": N}
    """
    summary   = {"decayed": 0, "pruned": 0, "protected_skipped": 0, "errors": 0}
    decay_log = _load_decay_log()
    today     = date.today().isoformat()

    for collection_name in DECAY_COLLECTIONS:
        try:
            col = get_collection(collection_name)
            if col.count() == 0:
                continue

            results = col.get(include=["metadatas"])
            if not results["ids"]:
                continue

            to_decay = []   # (uid, meta, new_importance)
            to_prune = []   # uid

            for uid, meta in zip(results["ids"], results["metadatas"]):
                if meta.get("protected", False):
                    summary["protected_skipped"] += 1
                    continue

                importance    = float(meta.get("importance", 0.3))
                last_accessed = meta.get("last_accessed", meta.get("date", today))
                memory_date   = meta.get("date", meta.get("date_learned", today))
                days_idle     = _days_since(last_accessed)
                memory_age    = _days_since(memory_date)

                decay_periods = days_idle // 7
                if decay_periods > 0:
                    new_importance = max(0.0, importance - (DECAY_RATE * decay_periods))
                    if new_importance != importance:
                        to_decay.append((uid, meta, new_importance))

                if importance < PRUNE_THRESHOLD and memory_age >= PRUNE_MIN_AGE_DAYS:
                    to_prune.append(uid)

            # Apply decay
            for uid, meta, new_importance in to_decay:
                meta["importance"] = new_importance
                try:
                    col.update(ids=[uid], metadatas=[meta])
                    summary["decayed"] += 1
                except Exception:
                    summary["errors"] += 1

            # Prune — skip entries that were just decayed (they may now be above threshold)
            prune_set = set(to_prune) - {uid for uid, _, _ in to_decay}

            # Force-prune if collection is oversized
            if col.count() > MAX_COLLECTION_SIZE:
                all_results = col.get(include=["metadatas"])
                candidates = sorted(
                    [
                        (uid, float(meta.get("importance", 0.3)))
                        for uid, meta in zip(all_results["ids"], all_results["metadatas"])
                        if not meta.get("protected", False)
                    ],
                    key=lambda x: x[1],
                )
                excess = col.count() - MAX_COLLECTION_SIZE
                prune_set.update(uid for uid, _ in candidates[:excess])

            if prune_set:
                col.delete(ids=list(prune_set))
                summary["pruned"] += len(prune_set)

        except Exception as e:
            log.warning(f"Decay cycle error in '{collection_name}': {e}")
            summary["errors"] += 1

    # Expire working memories past their expiry date
    try:
        working_col = get_collection("working")
        if working_col.count() > 0:
            results     = working_col.get(include=["metadatas"])
            expired_ids = [
                uid for uid, meta in zip(results["ids"], results["metadatas"])
                if meta.get("expires_at", "9999-99-99") < today
            ]
            if expired_ids:
                working_col.delete(ids=expired_ids)
                summary["pruned"] += len(expired_ids)
    except Exception as e:
        log.warning(f"Working memory expiry error: {e}")

    decay_log[today] = summary
    _save_decay_log(decay_log)
    log.info(f"Decay cycle: {summary}")
    return summary
