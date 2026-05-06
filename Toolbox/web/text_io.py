# text_io.py
# Text interface — separate process, always-available fallback.
#
# Reads James's typed input, writes it to the brain's input queue,
# polls the output queue for responses, and prints them.
#
# This process should essentially never crash — it's just terminal I/O.
# If the brain crashes, text_io.py stays alive so James can see status
# and restart the brain without losing the terminal window.
#
# Usage:
#   python text_io.py
#
# Started automatically by start_hayeong.bat in its own window.

import sys
import time
import datetime

try:
    from hayeong_state import push_input, pop_output, set_interface_status, get_status
    _STATE_AVAILABLE = True
except ImportError:
    print("[text_io] ERROR: hayeong_state.py not found. Cannot connect to brain.")
    sys.exit(1)


POLL_INTERVAL  = 0.1   # seconds between output queue checks
RESPONSE_TIMEOUT = 60  # seconds to wait for a response before giving up


def _wait_for_response(msg_id: str) -> str | None:
    """Poll output queue until a response for msg_id arrives or timeout."""
    deadline = time.time() + RESPONSE_TIMEOUT
    while time.time() < deadline:
        resp = pop_output()
        if resp:
            if resp.get("reply_to") == msg_id:
                return resp["content"]
            # Response for a different message — drain stale entries
        time.sleep(POLL_INTERVAL)
    return None


def run():
    set_interface_status("text", "running")
    print("[text_io] Text interface running. Type to talk to Hayeong.")
    print("[text_io] Type 'status' to check brain status. Ctrl+C to exit.")
    print()

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[text_io] Text interface stopped.")
            set_interface_status("text", "down")
            break

        if not user_input:
            continue

        if user_input.lower() == "status":
            s = get_status()
            print(f"[status] brain={s['brain']} | interfaces={s['interfaces']} "
                  f"| input_q={s['input_len']} | output_q={s['output_len']}")
            continue

        # Write to brain input queue
        msg_id = push_input(user_input, source="text")
        print(f"Hayeong: ", end="", flush=True)

        response = _wait_for_response(msg_id)
        if response:
            print(response)
        else:
            print(f"[text_io] No response after {RESPONSE_TIMEOUT}s — "
                  f"brain may be busy or down. Check brain window.")
        print()


if __name__ == "__main__":
    run()
