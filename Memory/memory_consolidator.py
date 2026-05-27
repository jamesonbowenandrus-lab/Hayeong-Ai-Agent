"""
memory_consolidator.py
Background consolidation. Finds clusters of similar episodic memories
and compresses them into single, richer consolidated entries.
Prevents the collection from growing forever with redundant observations.
Run weekly — not every session.
"""

import json
import logging
from datetime import date
from pathlib import Path

from memory.memory_manager import get_collection

log = logging.getLogger("memory_consolidator")

CONSOLIDATION_LOG    = Path(__file__).parent / "chromadb" / "consolidation_log.json"
LAST_CONSOLIDATION   = Path(__file__).parent / "chromadb" / "last_consolidation.json"
MIN_CLUSTER_SIZE     = 4      # minimum similar memories needed to consolidate
SIMILARITY_THRESHOLD = 0.85   # cosine similarity required to cluster
MIN_AGE_DAYS         = 14     # only consolidate memories at least 14 days old
CONSOLIDATION_PERIOD = 7      # days between consolidation runs


def _days_since(date_str: str) -> int:
    try:
        return (date.today() - date.fromisoformat(date_str)).days
    except Exception:
        return 0


def should_consolidate() -> bool:
    """Return True if it's been at least CONSOLIDATION_PERIOD days since last run."""
    if not LAST_CONSOLIDATION.exists():
        return True
    try:
        data = json.loads(LAST_CONSOLIDATION.read_text(encoding="utf-8"))
        last = date.fromisoformat(data.get("date", "2000-01-01"))
        return (date.today() - last).days >= CONSOLIDATION_PERIOD
    except Exception:
        return True


def _mark_consolidated():
    LAST_CONSOLIDATION.parent.mkdir(parents=True, exist_ok=True)
    LAST_CONSOLIDATION.write_text(
        json.dumps({"date": date.today().isoformat()}),
        encoding="utf-8",
    )


def run_consolidation_cycle() -> dict:
    """
    Main entry point. Finds and consolidates redundant episodic memories.
    Returns summary: {"clusters_found": N, "memories_consolidated": N, "errors": N}
    """
    summary = {"clusters_found": 0, "memories_consolidated": 0, "errors": 0}

    try:
        col = get_collection("episodes")
        if col.count() < MIN_CLUSTER_SIZE * 2:
            _mark_consolidated()
            return summary

        results = col.get(include=["documents", "metadatas"])
        if not results["ids"]:
            _mark_consolidated()
            return summary

        today = date.today().isoformat()

        candidates = [
            (uid, doc, meta)
            for uid, doc, meta in zip(
                results["ids"], results["documents"], results["metadatas"]
            )
            if (
                not meta.get("consolidated", False)
                and _days_since(meta.get("date", today)) >= MIN_AGE_DAYS
            )
        ]

        if len(candidates) < MIN_CLUSTER_SIZE:
            _mark_consolidated()
            return summary

        processed_ids = set()
        consolidations = []

        for uid, doc, meta in candidates:
            if uid in processed_ids:
                continue
            try:
                similar = col.query(
                    query_texts=[doc],
                    n_results=min(20, col.count()),
                )
                cluster_ids  = []
                cluster_docs = []

                for s_doc, s_meta, s_dist, s_id in zip(
                    similar["documents"][0],
                    similar["metadatas"][0],
                    similar["distances"][0],
                    similar["ids"][0],
                ):
                    similarity = 1.0 - s_dist
                    if (
                        similarity >= SIMILARITY_THRESHOLD
                        and s_id not in processed_ids
                        and not s_meta.get("consolidated", False)
                        and _days_since(s_meta.get("date", today)) >= MIN_AGE_DAYS
                    ):
                        cluster_ids.append(s_id)
                        cluster_docs.append(s_doc)

                if len(cluster_ids) >= MIN_CLUSTER_SIZE:
                    consolidations.append((cluster_ids, cluster_docs, meta))
                    processed_ids.update(cluster_ids)
                    summary["clusters_found"] += 1

            except Exception as e:
                summary["errors"] += 1
                log.warning(f"Cluster search error: {e}")

        # Process each cluster
        for cluster_ids, cluster_docs, rep_meta in consolidations:
            try:
                from memory.memory_writer import write_memory

                count   = len(cluster_docs)
                samples = cluster_docs[:3]
                tail    = f" (and {count - 1} similar entries)" if count > 1 else ""

                consolidated_text = (
                    f"[Consolidated — {count} similar observations] "
                    f"{samples[0][:100]}..."
                    + (f" Also: {samples[1][:60]}..." if len(samples) > 1 else "")
                    + tail
                )

                original_importance    = float(rep_meta.get("importance", 0.3))
                consolidated_importance = min(0.9, original_importance + 0.2)

                write_memory(
                    content=consolidated_text,
                    category="conversation",
                    metadata={
                        "topic":        rep_meta.get("topic", "general"),
                        "consolidated": True,
                        "source_count": count,
                        "importance":   consolidated_importance,
                        "protected":    consolidated_importance >= 0.7,
                    },
                    speaker=rep_meta.get("speaker", "unknown"),
                    emotional_weight=float(rep_meta.get("emotional_weight", 0.0)),
                )

                col.delete(ids=cluster_ids)
                summary["memories_consolidated"] += count

            except Exception as e:
                summary["errors"] += 1
                log.warning(f"Consolidation write error: {e}")

    except Exception as e:
        summary["errors"] += 1
        log.error(f"Consolidation cycle failed: {e}")

    _mark_consolidated()
    log.info(f"Consolidation: {summary}")
    return summary
