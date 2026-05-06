"""
review_logs.py — Review conversation logs and annotate them for fine-tuning.
Run: python tools/review_logs.py 2026-04-30
"""

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
date     = sys.argv[1] if len(sys.argv) > 1 else None

if date is None:
    from datetime import date as _date
    date = str(_date.today())

log_file = BASE_DIR / "logs" / "conversations" / f"{date}.jsonl"

if not log_file.exists():
    print(f"No log found for {date}")
    sys.exit(1)

entries = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line]
updated = []

print(f"\nReviewing {len(entries)} exchanges from {date}\n")

for i, entry in enumerate(entries):
    print(f"--- Exchange {i+1}/{len(entries)} ---")
    print(f"You:     {entry['james']}")
    print(f"Hayeong: {entry['hayeong']}")
    if entry.get("task_assigned"):
        print(f"Task:    {entry['task_assigned']}")
    print(f"Outcome: {entry['outcome']}")

    rating = input("Rate (g=good, b=bad, c=corrected, s=skip, q=quit): ").strip().lower()

    if rating == "q":
        updated.extend(entries[i:])
        break
    elif rating == "s":
        updated.append(entry)
    elif rating in ("g", "b", "c"):
        entry["outcome"] = {"g": "good", "b": "bad", "c": "corrected"}[rating]
        if rating in ("b", "c"):
            entry["notes"] = input("Notes (what should she have said/done?): ").strip()
        updated.append(entry)
    else:
        updated.append(entry)
    print()

with open(log_file, "w", encoding="utf-8") as f:
    for entry in updated:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

good    = sum(1 for e in updated if e["outcome"] == "good")
bad     = sum(1 for e in updated if e["outcome"] == "bad")
pending = sum(1 for e in updated if e["outcome"] == "pending")
print(f"Done. {good} good, {bad} bad, {pending} pending.")
