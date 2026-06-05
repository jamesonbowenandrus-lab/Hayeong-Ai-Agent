#!/usr/bin/env python3
"""
Tools/review/conversation_review.py
Command-line tool for reviewing and tagging Hayeong conversation exchanges.
Fine-tuning data curation — never modifies source logs.

Usage:
    python Tools/review/conversation_review.py           # review mode
    python Tools/review/conversation_review.py --export  # export fine-tuning file
    python Tools/review/conversation_review.py --stats   # show review statistics
"""

import sys
import os
import json
import argparse
import datetime
from pathlib import Path

# Root is two levels up from Tools/review/
_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from brain.config import CONV_LOG_DIR, BRAIN_DIR, TOOLS_DIR

REVIEW_DIR    = Path(TOOLS_DIR) / "review"
STATE_FILE    = REVIEW_DIR / "review_state.json"
REVIEWED_FILE = REVIEW_DIR / "reviewed_exchanges.jsonl"
EXPORT_FILE   = REVIEW_DIR / "finetune_export.jsonl"
CONV_DIR      = Path(CONV_LOG_DIR)
CONST_PATH    = Path(BRAIN_DIR) / "identity_constitutional.json"

_DEFAULT_STATE = {
    "reviewed_sessions": [],
    "last_export_at":    None,
    "total_reviewed":    0,
    "total_gold":        0,
    "total_correct":     0,
    "total_discarded":   0,
}

SEP_WIDE   = "=" * 60
SEP_NARROW = "-" * 60


# ── State I/O ─────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if not STATE_FILE.exists():
        return dict(_DEFAULT_STATE)
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return dict(_DEFAULT_STATE)


def save_state(state: dict) -> None:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ── Conversation log loading ───────────────────────────────────────────────────

def load_all_exchanges() -> dict:
    """
    Read all JSONL files in the conversations directory.
    Returns {session_id: [exchanges sorted by timestamp]}.
    Skips malformed lines with a warning.
    """
    if not CONV_DIR.exists():
        return {}

    sessions = {}
    for log_file in sorted(CONV_DIR.glob("*.jsonl")):
        try:
            with open(log_file, encoding="utf-8") as f:
                for lineno, raw in enumerate(f, 1):
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        entry = json.loads(raw)
                        sid   = entry.get("session_id", "")
                        if not sid:
                            continue
                        sessions.setdefault(sid, []).append(entry)
                    except json.JSONDecodeError:
                        print(f"Warning: malformed JSON in {log_file.name}:{lineno} — skipping")
        except Exception as e:
            print(f"Warning: could not read {log_file.name}: {e}")

    for sid in sessions:
        sessions[sid].sort(key=lambda x: x.get("timestamp", ""))
    return sessions


# ── Reviewed-exchange tracking ────────────────────────────────────────────────

def load_tagged_keys() -> set:
    """Return set of (session_id, timestamp) for exchanges already tagged."""
    keys = set()
    if not REVIEWED_FILE.exists():
        return keys
    try:
        with open(REVIEWED_FILE, encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                    keys.add((entry["session_id"], entry["timestamp"]))
                except Exception:
                    pass
    except Exception:
        pass
    return keys


def append_reviewed(entry: dict) -> None:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    with open(REVIEWED_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── Constitutional identity ───────────────────────────────────────────────────

def load_constitutional() -> str:
    if not CONST_PATH.exists():
        return ""
    try:
        return CONST_PATH.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Error reading constitutional identity: {e}")
        return ""


# ── Terminal helpers ──────────────────────────────────────────────────────────

def _wrap(text: str, width: int = 80, indent: str = "") -> str:
    """Wrap text at word boundaries."""
    words  = text.split()
    lines  = []
    cur    = indent
    for word in words:
        if cur == indent:
            cur += word
        elif len(cur) + 1 + len(word) <= width:
            cur += " " + word
        else:
            lines.append(cur)
            cur = indent + word
    if cur.strip():
        lines.append(cur)
    return "\n".join(lines)


def print_session_header(session_id: str, date_str: str,
                          total: int, pending: int) -> None:
    label = f"SESSION: {session_id}  |  Date: {date_str}  |  {total} exchanges"
    if pending < total:
        label += f"  ({pending} pending)"
    print()
    print(SEP_WIDE)
    print(label)
    print(SEP_WIDE)


def print_exchange(exchange: dict, index: int, total: int) -> None:
    james   = exchange.get("james",   "").strip()
    hayeong = exchange.get("hayeong", "").strip()
    ts      = exchange.get("timestamp", "")[:19]

    print()
    print(SEP_NARROW)
    print(f"Exchange {index} of {total}  |  {ts}")
    print(SEP_NARROW)
    print(f"James:   {james}")
    print()
    print(_wrap(hayeong, width=78, indent="         ").replace("         ", "Hayeong: ", 1))
    print()


def read_multiline() -> str:
    """Collect lines until the user submits a blank line. Returns stripped text."""
    lines = []
    while True:
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            break
        if line == "" and lines:
            break
        lines.append(line)
    return "\n".join(lines).strip()


# ── Review mode ───────────────────────────────────────────────────────────────

def run_review() -> None:
    if not CONV_DIR.exists():
        print(f"Conversations directory not found: {CONV_DIR}")
        print("Nothing to review.")
        return

    state        = load_state()
    reviewed_set = set(state.get("reviewed_sessions", []))
    all_sessions = load_all_exchanges()

    if not all_sessions:
        print("No conversation logs found.")
        return

    def _session_start(sid: str) -> str:
        exs = all_sessions.get(sid, [])
        return exs[0].get("timestamp", "") if exs else ""

    pending_sessions = [
        sid for sid in sorted(all_sessions, key=_session_start)
        if sid not in reviewed_set
    ]

    if not pending_sessions:
        print()
        print(SEP_WIDE)
        print("All sessions have been reviewed. Nothing left to tag.")
        print(f"Total: {len(all_sessions)} sessions  |  Reviewed: {len(reviewed_set)}")
        print(SEP_WIDE)
        return

    tagged_keys  = load_tagged_keys()
    run_gold     = 0
    run_correct  = 0
    run_discard  = 0
    run_total    = 0
    quit_flag    = False

    for session_id in pending_sessions:
        if quit_flag:
            break

        exchanges = all_sessions[session_id]
        pending   = [
            ex for ex in exchanges
            if (ex.get("session_id", ""), ex.get("timestamp", "")) not in tagged_keys
        ]
        date_str = (exchanges[0].get("timestamp", "") or "")[:10]

        if not pending:
            # Everything tagged in a previous run — mark reviewed now
            if session_id not in reviewed_set:
                reviewed_set.add(session_id)
                state.setdefault("reviewed_sessions", []).append(session_id)
            continue

        print_session_header(session_id, date_str, len(exchanges), len(pending))

        s_gold = s_correct = s_discard = s_skip = 0

        for idx, exchange in enumerate(pending, 1):
            print_exchange(exchange, idx, len(pending))
            print("Tag this exchange:")
            print("  [g] gold     — authentic, keep as-is")
            print("  [c] correct  — good moment, needs better response")
            print("  [d] discard  — bot-like, off-brand, exclude entirely")
            print("  [s] skip     — unsure, skip for now (will appear again)")
            print("  [q] quit     — save progress and exit")
            print()

            while True:
                try:
                    choice = input("> ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    choice = "q"
                if choice in ("g", "c", "d", "s", "q"):
                    break
                print("Enter g, c, d, s, or q.")

            if choice == "q":
                quit_flag = True
                break

            if choice == "s":
                s_skip += 1
                continue

            corrected = None
            if choice == "c":
                print()
                print("Write the response Hayeong should have given.")
                print("Press Enter on a blank line when done.")
                print()
                corrected = read_multiline()
                if not corrected:
                    print("(Empty — treating as skip)")
                    s_skip += 1
                    continue

            tag_name = {"g": "gold", "c": "correct", "d": "discard"}[choice]
            record   = {
                "session_id":         exchange.get("session_id",  ""),
                "timestamp":          exchange.get("timestamp",   ""),
                "tag":                tag_name,
                "james":              exchange.get("james",       ""),
                "hayeong":            exchange.get("hayeong",     ""),
                "corrected_response": corrected,
                "reviewed_at":        datetime.datetime.now().isoformat(),
            }
            append_reviewed(record)
            tagged_keys.add((record["session_id"], record["timestamp"]))

            if choice == "g":
                s_gold   += 1
                run_gold += 1
            elif choice == "c":
                s_correct   += 1
                run_correct += 1
            elif choice == "d":
                s_discard   += 1
                run_discard += 1

            run_total += 1

        # Post-session summary (only when not quit mid-session)
        if not quit_flag:
            print()
            print(SEP_NARROW)
            print(f"Session {session_id} done.")
            print(f"  Gold: {s_gold}  |  Corrected: {s_correct}  |  "
                  f"Discarded: {s_discard}  |  Skipped: {s_skip}")

            all_tagged = all(
                (ex.get("session_id", ""), ex.get("timestamp", "")) in tagged_keys
                for ex in exchanges
            )
            if all_tagged and session_id not in reviewed_set:
                reviewed_set.add(session_id)
                state.setdefault("reviewed_sessions", []).append(session_id)
                print("  Session fully reviewed.")
            print(SEP_NARROW)

    # Persist updated state
    state["reviewed_sessions"] = list(reviewed_set)
    state["total_gold"]        = state.get("total_gold",      0) + run_gold
    state["total_correct"]     = state.get("total_correct",   0) + run_correct
    state["total_discarded"]   = state.get("total_discarded", 0) + run_discard
    state["total_reviewed"]    = state.get("total_reviewed",  0) + run_total
    save_state(state)

    print()
    print(SEP_WIDE)
    print(f"Done.  Tagged this run: {run_total}")
    print(f"  Gold: {run_gold}  |  Corrected: {run_correct}  |  Discarded: {run_discard}")
    print(SEP_WIDE)


# ── Export mode ───────────────────────────────────────────────────────────────

def run_export() -> None:
    if not REVIEWED_FILE.exists():
        print("No reviewed exchanges found. Run review mode first.")
        return

    constitutional_text = load_constitutional()
    if not constitutional_text:
        print(f"Error: constitutional identity not found at {CONST_PATH}")
        print("Export requires Brain/identity_constitutional.json.")
        return

    gold_count    = 0
    correct_count = 0
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    with open(REVIEWED_FILE, encoding="utf-8") as src, \
         open(EXPORT_FILE,   "w", encoding="utf-8") as dst:

        for raw in src:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue

            tag = entry.get("tag", "")

            if tag == "gold":
                record = {
                    "messages": [
                        {"role": "system",    "content": constitutional_text},
                        {"role": "user",      "content": entry.get("james",   "")},
                        {"role": "assistant", "content": entry.get("hayeong", "")},
                    ],
                    "tag":            "gold",
                    "source_session": entry.get("session_id", ""),
                    "timestamp":      entry.get("timestamp",  ""),
                }
                dst.write(json.dumps(record, ensure_ascii=False) + "\n")
                gold_count += 1

            elif tag == "correct":
                corrected = entry.get("corrected_response", "")
                if not corrected:
                    continue
                record = {
                    "messages": [
                        {"role": "system",    "content": constitutional_text},
                        {"role": "user",      "content": entry.get("james",  "")},
                        {"role": "assistant", "content": corrected},
                    ],
                    "tag":               "corrected",
                    "original_response": entry.get("hayeong", ""),
                    "source_session":    entry.get("session_id", ""),
                    "timestamp":         entry.get("timestamp",  ""),
                }
                dst.write(json.dumps(record, ensure_ascii=False) + "\n")
                correct_count += 1
            # discard: never exported

    state                   = load_state()
    state["last_export_at"] = datetime.datetime.now().isoformat()
    save_state(state)

    total = gold_count + correct_count
    print()
    print("Export complete.")
    print(f"  Gold examples:        {gold_count}")
    print(f"  Corrected examples:   {correct_count}")
    print(f"  Total training pairs: {total}")
    print(f"  Output: {EXPORT_FILE}")


# ── Stats mode ────────────────────────────────────────────────────────────────

def run_stats() -> None:
    state        = load_state()
    all_sessions = load_all_exchanges()

    total_sessions    = len(all_sessions)
    reviewed_sessions = len(state.get("reviewed_sessions", []))
    unreviewed        = total_sessions - reviewed_sessions

    gold_count = correct_count = discard_count = 0
    if REVIEWED_FILE.exists():
        try:
            with open(REVIEWED_FILE, encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        entry = json.loads(raw)
                        tag   = entry.get("tag", "")
                        if tag == "gold":
                            gold_count += 1
                        elif tag == "correct":
                            correct_count += 1
                        elif tag == "discard":
                            discard_count += 1
                    except Exception:
                        pass
        except Exception:
            pass

    total_reviewed = gold_count + correct_count + discard_count
    training_pairs = gold_count + correct_count
    last_export    = state.get("last_export_at") or "never"

    print()
    print(SEP_WIDE)
    print("HAYEONG FINE-TUNING DATA STATS")
    print(SEP_WIDE)
    print(f"Sessions reviewed:    {reviewed_sessions} of {total_sessions}")
    print(f"Exchanges reviewed:   {total_reviewed}")
    print(f"  Gold:               {gold_count}")
    print(f"  Corrected:          {correct_count}")
    print(f"  Discarded:          {discard_count}")
    print()
    print(f"Training pairs ready: {training_pairs}")
    print(f"Last export:          {last_export}")
    print()
    print(f"Unreviewed sessions:  {unreviewed}")
    print(SEP_WIDE)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hayeong conversation review and fine-tuning export tool"
    )
    parser.add_argument("--export", action="store_true", help="Export fine-tuning JSONL")
    parser.add_argument("--stats",  action="store_true", help="Show review statistics")
    args = parser.parse_args()

    if args.export:
        run_export()
    elif args.stats:
        run_stats()
    else:
        run_review()


if __name__ == "__main__":
    main()
