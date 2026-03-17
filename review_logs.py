# review_logs.py
# Tool for reviewing recorded sessions and labeling good/bad actions.
# Run this after a recording session to rate Hayeong's decisions.
#
# Usage:
#   python review_logs.py                    — review today's minecraft log
#   python review_logs.py logs/james_2026-02-23_14-30.jsonl  — review specific file

import json
import os
import sys
import glob

def review_file(path):
    with open(path, "r") as f:
        lines = [json.loads(l) for l in f if l.strip()]

    print(f"\n📋 Reviewing: {path}")
    print(f"   {len(lines)} entries\n")

    rated   = 0
    skipped = 0

    for i, entry in enumerate(lines):
        # Skip snapshots unless they have an action — focus on decision points
        if entry.get("event") == "snapshot" and not entry.get("action"):
            continue
        if entry.get("quality") is not None:
            continue  # already rated

        print(f"\n--- Entry {i+1}/{len(lines)} ---")
        print(f"Event:    {entry.get('event_type') or entry.get('event')}")
        print(f"Session:  {entry.get('session', 'general')}")

        state = entry.get("game_state") or entry.get("james_state") or {}
        if state:
            print(f"Health:   {state.get('health', '?')}  Food: {state.get('food', '?')}")
            print(f"Held:     {state.get('held_item', '?')}")
            print(f"Blocks:   {', '.join(state.get('nearby_blocks', []))}")
            mobs = state.get("nearby_entities") or state.get("nearby_mobs") or []
            if mobs:
                print(f"Entities: {mobs}")

        extra = entry.get("extra", {})
        if extra:
            print(f"Extra:    {extra}")

        action = entry.get("action")
        if action:
            print(f"Action:   {action}")

        print("\nRate this: [g]ood  [b]ad  [s]kip  [q]uit  [n]ote")
        choice = input("> ").strip().lower()

        if choice == "q":
            break
        elif choice == "g":
            lines[i]["quality"] = "good"
            rated += 1
        elif choice == "b":
            lines[i]["quality"] = "bad"
            rated += 1
            note = input("What should she have done instead? (enter to skip): ").strip()
            if note:
                lines[i]["correct_action_description"] = note
        elif choice == "n":
            note = input("Note: ").strip()
            lines[i]["notes"] = note
            skipped += 1
        else:
            skipped += 1

    # Save back
    with open(path, "w") as f:
        for entry in lines:
            f.write(json.dumps(entry) + "\n")

    good = sum(1 for e in lines if e.get("quality") == "good")
    bad  = sum(1 for e in lines if e.get("quality") == "bad")
    print(f"\n✅ Done. Good: {good}  Bad: {bad}  Unrated: {len(lines)-good-bad}")
    print(f"Saved to: {path}")

def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        # Find most recent log
        files = sorted(glob.glob("logs/minecraft_*.jsonl") + glob.glob("logs/james_*.jsonl"))
        if not files:
            print("No log files found in logs/ folder")
            return
        path = files[-1]

    review_file(path)

if __name__ == "__main__":
    main()
