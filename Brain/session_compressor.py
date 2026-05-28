"""
session_compressor.py
Compresses older conversation buffer entries into a compact summary.

The LLM decides what matters — that is a Brain function, not a mechanical one.
Runs on a 2-minute background cycle. Never blocks presence or task loops.
Archives compressed blocks to ChromaDB episodes before trimming the live buffer.
"""

import time
import threading
import requests
from datetime import datetime
from typing import List, Dict

from brain.config import PRESENCE_URL, PRESENCE_MODEL
from brain.context_manager import (
    set_session_summary,
    get_session_summary,
    get_compressible_block,
    should_compress,
)

_compression_lock = threading.Lock()
_is_compressing   = False

COMPRESS_SYSTEM = """You are helping maintain a lean conversation context.
Summarize the provided conversation exchanges into 3-5 compact sentences.
Capture: what was discussed, what was decided, any important facts or commitments.
Write in past tense. Be specific about decisions made.
Do not include pleasantries or small talk.
Return ONLY the summary — no preamble, no explanation."""


def _call_llm_for_summary(exchanges: List[Dict]) -> str:
    """Ask the LLM to summarize a block of exchanges."""
    formatted = "\n".join(
        f"{'James' if e['role'] == 'james' else 'Hayeong'}: {e['content']}"
        for e in exchanges
    )
    try:
        resp = requests.post(PRESENCE_URL, json={
            "model":    PRESENCE_MODEL,
            "messages": [
                {"role": "system", "content": COMPRESS_SYSTEM},
                {"role": "user",   "content": formatted},
            ],
            "stream":     False,
            "keep_alive": -1,
            "options":    {"num_ctx": 4096},
        }, timeout=45)
        return resp.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        print(f"[session_compressor] LLM summary failed: {e}")
        return ""


def _archive_to_chromadb(exchanges: List[Dict], summary: str) -> None:
    """Write the compressed block to ChromaDB episodes collection."""
    try:
        from memory.memory_writer import write_memory
        write_memory(
            content=f"[Session summary] {summary}",
            category="conversation",  # routes to episodes collection
            metadata={
                "topic":        "session_compression",
                "source_count": len(exchanges),
                "importance":   0.55,
            },
            speaker="hayeong",
        )
    except Exception as e:
        print(f"[session_compressor] ChromaDB archive failed: {e}")


def run_compression_if_needed() -> bool:
    """
    Check if compression is needed and run it synchronously.
    Returns True if compression ran, False otherwise.
    Uses a lock to prevent concurrent compression runs.
    """
    global _is_compressing

    if _is_compressing:
        return False

    try:
        from brain.conversation_buffer import get_recent, trim_to_recent
        entries = get_recent(n=20)

        if not should_compress(len(entries)):
            return False

        compressible = get_compressible_block(entries)
        if not compressible:
            return False

        with _compression_lock:
            _is_compressing = True

        print(f"[session_compressor] Compressing {len(compressible)} exchanges...")
        summary = _call_llm_for_summary(compressible)

        if not summary:
            print("[session_compressor] Summary empty — skipping.")
            return False

        existing = get_session_summary()
        combined = f"{existing}\n\n{summary}" if existing else summary

        set_session_summary(combined)
        _archive_to_chromadb(compressible, summary)
        trim_to_recent(n=6)

        print(f"[session_compressor] Done. Summary now {len(combined)} chars.")
        return True

    except Exception as e:
        print(f"[session_compressor] Compression error: {e}")
        return False
    finally:
        _is_compressing = False


def start_compression_background_thread() -> None:
    """Start a daemon thread that checks for compression need every 2 minutes."""
    def _loop():
        while True:
            try:
                time.sleep(120)
                run_compression_if_needed()
            except Exception as e:
                print(f"[session_compressor] Background thread error: {e}")

    t = threading.Thread(target=_loop, daemon=True, name="session_compressor")
    t.start()
    print("   Session compressor started.")
