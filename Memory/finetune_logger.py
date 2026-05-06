"""
finetune_logger.py
Append-only fine-tuning logs for conversation turns and reasoning decisions.

Quality flags ("good" / "bad") can be added to the most recent entry.
These are the highest-value training examples — they directly encode
what Hayeong should and shouldn't do.

Usage:
    from finetune_logger import conversation_logger, reasoning_logger

    conversation_logger.log_turn(user, assistant, model, mood)
    conversation_logger.flag_last_turn("good")   # James said "that was perfect"

    reasoning_logger.log_reasoning(domain, context, decision, result)
    reasoning_logger.flag_last_turn("bad")
"""

import json
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

CONVERSATION_LOG = LOG_DIR / "finetune_log.jsonl"
REASONING_LOG    = LOG_DIR / "reasoning_log.jsonl"


class FineTuneLogger:
    def __init__(self, log_path: Path):
        self._path = log_path
        self._last_entry: dict | None = None

    def log_turn(self, user: str, assistant: str, model: str, mood: str):
        """Log one conversation turn (7b communication layer)."""
        entry = {
            "timestamp":    datetime.now().isoformat(),
            "user":         user,
            "assistant":    assistant,
            "model":        model,
            "mood":         mood,
            "quality_flag": None,
        }
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._last_entry = entry

    def log_reasoning(self, domain: str, context: str, decision: dict, result: str):
        """Log one reasoning decision (14b reasoning layer)."""
        entry = {
            "timestamp":    datetime.now().isoformat(),
            "domain":       domain,
            "context":      context[:800],
            "decision":     decision,
            "result":       result,
            "quality_flag": None,
        }
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._last_entry = entry

    def flag_last_turn(self, flag: str):
        """Update the quality_flag on the most recently logged entry.
        flag: 'good' | 'bad'
        Rewrites the last line of the log file in place."""
        if self._last_entry is None:
            return
        self._last_entry["quality_flag"] = flag
        try:
            text  = self._path.read_text(encoding="utf-8")
            lines = text.rstrip("\n").split("\n")
            if lines:
                lines[-1] = json.dumps(self._last_entry, ensure_ascii=False)
                self._path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception:
            pass


# Module-level instances — import these directly
conversation_logger = FineTuneLogger(CONVERSATION_LOG)
reasoning_logger    = FineTuneLogger(REASONING_LOG)
