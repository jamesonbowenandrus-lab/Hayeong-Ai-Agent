"""
Toolbox/finetune_curator/finetune_curator.py

Reviews conversation logs and tags high-authenticity moments
as fine-tuning training data candidates.

Called via registry:
    module:   toolbox.finetune_curator.finetune_curator
    function: run

Params:
    operation    (str) — curate_recent | curate_all | export_dataset | status
    days_back    (int) — how many days of logs to curate (default 7)
    min_quality  (str) — high | medium (filter for export)
    export_format (str) — jsonl | alpaca (default jsonl)
"""

import json
from pathlib import Path
from datetime import datetime, timedelta

ROOT_DIR     = Path(__file__).parent.parent.parent
CONV_LOG_DIR = ROOT_DIR / "Logs" / "conversations"
CURATED_DIR  = ROOT_DIR / "Toolbox" / "finetune_curator" / "curated"
MANIFEST     = ROOT_DIR / "Toolbox" / "finetune_curator" / "dataset_manifest.json"
CURATION_LOG = ROOT_DIR / "Toolbox" / "finetune_curator" / "curation_log.json"
DATASET_DIR  = ROOT_DIR / "Logs" / "finetune_datasets"


def run(description: str, params: dict) -> str:
    try:
        operation = params.get("operation", "status").lower()
        if operation == "curate_recent":
            days = int(params.get("days_back", 7))
            return _curate(days_back=days)
        elif operation == "curate_all":
            return _curate(days_back=None)
        elif operation == "export_dataset":
            min_q  = params.get("min_quality", "high")
            fmt    = params.get("export_format", "jsonl")
            return _export(min_quality=min_q, export_format=fmt)
        elif operation == "status":
            return _status()
        else:
            return f"Unknown operation '{operation}'. Use: curate_recent, curate_all, export_dataset, status"
    except Exception as e:
        return f"finetune_curator error: {e}"


def _load_logs(days_back) -> list:
    if not CONV_LOG_DIR.exists():
        return []
    entries = []
    cutoff  = (datetime.now() - timedelta(days=days_back)).date() if days_back else None
    for log_file in sorted(CONV_LOG_DIR.glob("*.jsonl")):
        try:
            file_date_str = log_file.stem
            file_date = datetime.strptime(file_date_str, "%Y-%m-%d").date()
            if cutoff and file_date < cutoff:
                continue
        except Exception:
            pass
        try:
            for line in log_file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entries.append(json.loads(line))
        except Exception:
            pass
    return entries


def _score_exchange(entry: dict) -> dict:
    james   = entry.get("james", "").strip()
    hayeong = entry.get("hayeong", "").strip()

    if not james or not hayeong:
        return {"total": 0, "skip": True}

    authenticity      = 5
    quality           = 5
    representativeness = 5

    if len(hayeong) > 100:
        quality += 1
    if len(hayeong) > 300:
        quality += 1
    if any(w in hayeong.lower() for w in ["i think", "i'm not sure", "honestly", "actually"]):
        authenticity += 2
    if any(w in hayeong.lower() for w in ["great!", "absolutely!", "certainly!"]):
        authenticity -= 2
    if "?" in james and len(james) > 20:
        representativeness += 1
    if entry.get("task_assigned") and entry.get("task_assigned") != "none":
        representativeness += 1

    total = authenticity + quality + representativeness

    if total >= 24:
        tier = "high"
    elif total >= 18:
        tier = "medium"
    else:
        tier = "review"

    return {
        "authenticity":       authenticity,
        "quality":            quality,
        "representativeness": representativeness,
        "total":              total,
        "tier":               tier,
        "skip":               False,
    }


def _curate(days_back) -> str:
    entries = _load_logs(days_back)
    if not entries:
        return "No conversation logs found to curate."

    CURATED_DIR.mkdir(parents=True, exist_ok=True)
    (CURATED_DIR / "high").mkdir(exist_ok=True)
    (CURATED_DIR / "medium").mkdir(exist_ok=True)
    (CURATED_DIR / "review").mkdir(exist_ok=True)

    manifest = _load_manifest()
    counts   = {"high": 0, "medium": 0, "review": 0, "skipped": 0}
    new_entries = []

    for entry in entries:
        score = _score_exchange(entry)
        if score["skip"]:
            counts["skipped"] += 1
            continue

        tier = score["tier"]
        ts   = entry.get("timestamp", datetime.now().isoformat())
        slug = ts.replace(":", "").replace("-", "").replace("T", "_")[:15]

        example = {
            "messages": [
                {"role": "user",      "content": entry.get("james", "")},
                {"role": "assistant", "content": entry.get("hayeong", "")},
            ],
            "metadata": {
                "authenticity":       score["authenticity"],
                "quality":            score["quality"],
                "representativeness": score["representativeness"],
                "total_score":        score["total"],
                "tier":               tier,
                "curated_date":       datetime.now().isoformat(),
                "source_timestamp":   ts,
            }
        }

        out_file = CURATED_DIR / tier / f"{slug}.json"
        out_file.write_text(json.dumps(example, indent=2, ensure_ascii=False), encoding="utf-8")

        manifest[slug] = {"tier": tier, "score": score["total"], "file": str(out_file)}
        new_entries.append({"tier": tier, "score": score["total"]})
        counts[tier] += 1

    _save_manifest(manifest)
    _append_curation_log(days_back, counts)

    return (
        f"Curation complete: {counts['high']} high, "
        f"{counts['medium']} medium, {counts['review']} review, "
        f"{counts['skipped']} skipped."
    )


def _export(min_quality: str, export_format: str) -> str:
    manifest = _load_manifest()
    tier_order = {"high": 3, "medium": 2, "review": 1}
    min_tier   = tier_order.get(min_quality, 3)

    examples = []
    for slug, meta in manifest.items():
        if tier_order.get(meta.get("tier", "review"), 1) >= min_tier:
            try:
                f = Path(meta["file"])
                if f.exists():
                    examples.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                pass

    if not examples:
        return f"No examples found at quality tier '{min_quality}' or above."

    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = DATASET_DIR / f"{ts}_{export_format}.jsonl"

    with open(out_path, "w", encoding="utf-8") as f:
        for ex in examples:
            if export_format == "alpaca":
                alpaca = {
                    "instruction": ex["messages"][0]["content"],
                    "input":       "",
                    "output":      ex["messages"][1]["content"],
                }
                f.write(json.dumps(alpaca, ensure_ascii=False) + "\n")
            else:
                f.write(json.dumps(ex["messages"], ensure_ascii=False) + "\n")

    return f"Exported {len(examples)} examples to {out_path}"


def _status() -> str:
    manifest = _load_manifest()
    counts   = {"high": 0, "medium": 0, "review": 0}
    for meta in manifest.values():
        tier = meta.get("tier", "review")
        counts[tier] = counts.get(tier, 0) + 1
    total = sum(counts.values())
    return (
        f"Curated dataset: {total} total examples — "
        f"{counts['high']} high, {counts['medium']} medium, {counts['review']} review."
    )


def _load_manifest() -> dict:
    if not MANIFEST.exists():
        return {}
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_manifest(manifest: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def _append_curation_log(days_back, counts: dict) -> None:
    CURATION_LOG.parent.mkdir(parents=True, exist_ok=True)
    try:
        log = json.loads(CURATION_LOG.read_text(encoding="utf-8")) if CURATION_LOG.exists() else []
    except Exception:
        log = []
    log.append({
        "timestamp": datetime.now().isoformat(),
        "days_back": days_back,
        "counts":    counts,
    })
    CURATION_LOG.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")