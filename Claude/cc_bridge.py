"""
Claude/cc_bridge.py

Claude Code uses this script to communicate with Hayeong.
Sends a single message, waits for her response, returns it.

Usage:
    python Claude/cc_bridge.py --message "Create a UV sphere in Blender and export as GLB"
    python Claude/cc_bridge.py --message "..." --timeout 120 --source "claude_code"

Output:
    Prints Hayeong's response to stdout.
    Exits 0 on success, 1 on timeout or error.

The script uses the same HTTP endpoint as the dashboard (POST /api/send).
Hayeong cannot distinguish this from a dashboard message except by the
source tag written to session metadata.
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# ── Configuration ────────────────────────────────────────────────────
HAYEONG_BASE_URL  = "http://localhost:8080"
SEND_ENDPOINT     = f"{HAYEONG_BASE_URL}/api/send"
STATE_FILE        = Path(__file__).parent.parent / "Brain" / "state" / "core.json"
DEFAULT_TIMEOUT   = 90     # seconds to wait for a response
POLL_INTERVAL     = 2      # seconds between state polls
DEFAULT_SOURCE    = "claude_code"

# ── Argument parsing ─────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Send a message to Hayeong and get her response.")
parser.add_argument("--message",  required=True,  help="Message to send to Hayeong")
parser.add_argument("--timeout",  type=int, default=DEFAULT_TIMEOUT, help="Max seconds to wait")
parser.add_argument("--source",   default=DEFAULT_SOURCE, help="Source label for session log")
args = parser.parse_args()

# ── Read current presence_output timestamp (baseline) ────────────────
def _read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[bridge] Could not read state: {e}", file=sys.stderr)
        return {}

def _get_expressed_at(state: dict) -> str:
    return state.get("presence_output", {}).get("expressed_at", "")

def _get_response_text(state: dict) -> str:
    return state.get("presence_output", {}).get("for_james", "")

# ── Send message ─────────────────────────────────────────────────────
baseline_state      = _read_state()
baseline_expressed  = _get_expressed_at(baseline_state)

print(f"[bridge] Sending message to Hayeong...", file=sys.stderr)
print(f"[bridge] Source: {args.source}", file=sys.stderr)

try:
    resp = requests.post(
        SEND_ENDPOINT,
        json={"message": args.message},
        timeout=10,
    )
    if resp.status_code != 200:
        print(f"[bridge] HTTP error {resp.status_code}: {resp.text}", file=sys.stderr)
        sys.exit(1)
except requests.exceptions.ConnectionError:
    print(f"[bridge] Could not reach Hayeong at {SEND_ENDPOINT}.", file=sys.stderr)
    print(f"[bridge] Is the dashboard server running? (python dashboard/dashboard_server.py)", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"[bridge] Send failed: {e}", file=sys.stderr)
    sys.exit(1)

print(f"[bridge] Message sent. Waiting for response (timeout: {args.timeout}s)...", file=sys.stderr)

# ── Poll for response ─────────────────────────────────────────────────
sent_at   = datetime.now()
response  = None

while True:
    elapsed = (datetime.now() - sent_at).total_seconds()
    if elapsed > args.timeout:
        print(f"[bridge] Timeout after {args.timeout}s — no response received.", file=sys.stderr)
        sys.exit(1)

    time.sleep(POLL_INTERVAL)
    current_state     = _read_state()
    current_expressed = _get_expressed_at(current_state)

    if current_expressed and current_expressed != baseline_expressed:
        response = _get_response_text(current_state)
        latency  = (datetime.now() - sent_at).total_seconds()
        print(f"[bridge] Response received in {latency:.1f}s", file=sys.stderr)
        break

# ── Output ────────────────────────────────────────────────────────────
print(response or "")
sys.exit(0)
