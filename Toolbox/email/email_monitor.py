"""
email_monitor.py
────────────────
Passive email monitoring for Hayeong using IMAP IDLE.

Instead of polling every N minutes, this keeps a persistent connection
to Gmail and receives push notifications the instant a new email arrives.
Same mechanism your phone uses — zero wasted calls between messages.

WHAT THIS DOES:
  - Opens one persistent IMAP IDLE connection to hayeong.agent@gmail.com
  - Gmail pushes a notification the moment a new email arrives
  - Each new email is classified by importance using Qwen 14b
    (based on sender, subject, content vs. Hayeong's current context)
  - Important emails are surfaced naturally in conversation
  - All emails (important or not) are logged to a searchable local index
  - Search function lets Hayeong find any email by keyword, sender, date, topic

IMPORTANCE LEVELS:
  urgent    → surfaces immediately, interrupts if needed
  important → surfaces at next natural conversation opening
  normal    → logged silently, available for search
  noise     → logged silently, never surfaced proactively

USAGE (from main.py):
  from email_monitor import EmailMonitor
  monitor = EmailMonitor(on_important=hayeong_surface_email)
  monitor.start()  # non-blocking, runs in background thread

SEARCH (from main.py or context_router):
  results = monitor.search("landlord")
  results = monitor.search("from:james subject:research")
  results = monitor.search("last week")

STANDALONE TEST:
  python email_monitor.py
"""

import email
import imaplib
import json
import os
import re
import socket
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from dotenv import load_dotenv

load_dotenv()

BASE_DIR         = Path(__file__).parent
EMAIL_LOG_PATH   = BASE_DIR / "logs" / "email_inbox_log.json"
EMAIL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

HAYEONG_EMAIL    = os.getenv("HAYEONG_EMAIL_ADDRESS", "hayeong.agent@gmail.com")
EMAIL_PASSWORD   = os.getenv("HAYEONG_EMAIL_PASSWORD", "").replace(" ", "")
JAMES_EMAIL      = os.getenv("JAMES_EMAIL", "")

GMAIL_IMAP_HOST  = "imap.gmail.com"
GMAIL_IMAP_PORT  = 993

# IDLE keepalive — Gmail drops connections after ~29 min
# Ping every 20 minutes to keep the connection alive
IDLE_KEEPALIVE_SECONDS = 20 * 60

# Max emails to store in the local log
MAX_LOG_ENTRIES  = 500

# Ollama config for classification
OLLAMA_URL       = "http://localhost:11435/api/chat"
CLASSIFY_MODEL   = "deepseek-r1:latest"


# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[EmailMonitor {ts}] {msg}")

def _log_quiet(msg: str):
    """Log to file only — for routine reconnect/keepalive noise that clutters the terminal."""
    pass   # Currently no-op; add file logging here later if needed


# ─────────────────────────────────────────────
# EMAIL LOG (local searchable index)
# ─────────────────────────────────────────────

def _load_log() -> list:
    if EMAIL_LOG_PATH.exists():
        try:
            with open(EMAIL_LOG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_log(entries: list):
    # Keep only the most recent MAX_LOG_ENTRIES
    if len(entries) > MAX_LOG_ENTRIES:
        entries = entries[-MAX_LOG_ENTRIES:]
    try:
        with open(EMAIL_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
    except Exception as e:
        _log(f"⚠️  Failed to save log: {e}")


def _append_to_log(entry: dict):
    entries = _load_log()
    # Deduplicate by uid
    existing_uids = {e.get("uid") for e in entries}
    if entry.get("uid") in existing_uids:
        return
    entries.append(entry)
    _save_log(entries)


# ─────────────────────────────────────────────
# EMAIL PARSER
# ─────────────────────────────────────────────

def _parse_email(raw_bytes: bytes, uid: str) -> dict:
    """Parse raw email bytes into a clean dict."""
    msg  = email.message_from_bytes(raw_bytes)
    body = ""

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                try:
                    body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                    break
                except Exception:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode("utf-8", errors="replace")
        except Exception:
            body = str(msg.get_payload())

    return {
        "uid":       uid,
        "from":      msg.get("From", "").strip(),
        "subject":   msg.get("Subject", "").strip(),
        "date":      msg.get("Date", "").strip(),
        "body":      body.strip()[:3000],
        "received":  datetime.now().isoformat(),
        "importance": "normal",   # will be updated after classification
        "surfaced":  False,
    }


# ─────────────────────────────────────────────
# IMPORTANCE CLASSIFIER
# Uses 14b with conversation context to judge each email.
# Falls back to keyword rules if Ollama is unreachable.
# ─────────────────────────────────────────────

def _classify_importance(entry: dict, context_summary: str = "") -> str:
    """
    Classify an email's importance as: urgent | important | normal | noise

    context_summary: brief description of what Hayeong and James are
    currently working on / focused on. Injected to help 14b judge relevance.
    """
    import requests

    sender  = entry.get("from", "")
    subject = entry.get("subject", "")
    body    = entry.get("body", "")[:500]  # first 500 chars is enough

    prompt = (
        f"You are classifying an email for Hayeong, an AI companion.\n"
        f"James's current context: {context_summary or 'general daily life'}\n\n"
        f"Email:\n"
        f"  From: {sender}\n"
        f"  Subject: {subject}\n"
        f"  Body preview: {body}\n\n"
        f"Classify the importance of this email for Hayeong to surface to James.\n"
        f"Reply with ONLY one word:\n"
        f"  urgent    = needs James's attention immediately (time-sensitive, from someone he knows)\n"
        f"  important = worth surfacing soon (meaningful content, relevant to current context)\n"
        f"  normal    = informational, no action needed, log silently\n"
        f"  noise     = spam, marketing, automated, irrelevant\n"
        f"\nOne word only:"
    )

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": CLASSIFY_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.0},
            },
            timeout=15,
        )
        result = resp.json()["message"]["content"].strip().lower()
        if result in ("urgent", "important", "normal", "noise"):
            return result
        # If model returned something unexpected, default to normal
        return "normal"

    except Exception as e:
        _log(f"Classification failed ({e}) — using keyword fallback")
        return _classify_keywords(sender, subject, body)


def _classify_keywords(sender: str, subject: str, body: str) -> str:
    """Fast keyword fallback when Ollama is unreachable."""
    s = (sender + " " + subject + " " + body).lower()

    # Noise patterns
    noise_signals = [
        "unsubscribe", "marketing", "newsletter", "no-reply",
        "noreply", "donotreply", "promotions", "deal of the day",
        "% off", "limited time offer", "click here to", "verify your account",
    ]
    if any(n in s for n in noise_signals):
        return "noise"

    # Urgent patterns
    urgent_signals = [
        "urgent", "asap", "immediately", "time sensitive",
        "action required", "account suspended", "payment failed",
    ]
    if any(u in s for u in urgent_signals):
        return "urgent"

    # Important — from known contacts
    if JAMES_EMAIL and JAMES_EMAIL.split("@")[0].lower() in sender.lower():
        return "important"

    return "normal"


# ─────────────────────────────────────────────
# IMAP IDLE CONNECTION
# ─────────────────────────────────────────────

class EmailMonitor:
    """
    Passive email monitor using IMAP IDLE.

    Usage:
        monitor = EmailMonitor(on_important=callback)
        monitor.start()  # non-blocking

    The on_important callback receives a dict:
        {
          "from": "...",
          "subject": "...",
          "body": "...",
          "importance": "urgent"|"important",
          "surface_text": "Hey, you got an email from ..."
        }
    """

    def __init__(
        self,
        on_important: Optional[Callable] = None,
        get_context: Optional[Callable]  = None,
    ):
        """
        on_important: called when an important/urgent email arrives.
                      Receives the email dict. Use to surface in conversation.
        get_context:  called before classification to get current context summary.
                      Should return a short string describing what James is working on.
        """
        self.on_important = on_important
        self.get_context  = get_context
        self._thread      = None
        self._stop_event  = threading.Event()
        self._conn        = None
        self._lock        = threading.Lock()

    def start(self):
        """Start the monitor in a background daemon thread."""
        if not EMAIL_PASSWORD:
            _log("⚠️  No email password — monitor inactive. Set HAYEONG_EMAIL_PASSWORD in .env")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="EmailMonitor",
        )
        self._thread.start()
        _log("✅ Email monitor started (IMAP IDLE)")

    def stop(self):
        """Signal the monitor to stop."""
        self._stop_event.set()
        with self._lock:
            if self._conn:
                try:
                    self._conn.logout()
                except Exception:
                    pass
        _log("Email monitor stopped")

    # ─────────────────────────────────────────
    # MAIN LOOP
    # ─────────────────────────────────────────

    def _run_loop(self):
        """Outer reconnect loop — handles connection drops gracefully."""
        backoff = 5
        while not self._stop_event.is_set():
            try:
                self._connect_and_idle()
                backoff = 5  # reset on clean exit
            except Exception as e:
                _log_quiet(f"connection error: {e} — reconnecting in {backoff}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, 120)  # exponential backoff, max 2 min

    def _connect_and_idle(self):
        """Connect to Gmail, select inbox, run IDLE loop."""
        _log("Connecting to Gmail IMAP...")

        conn = imaplib.IMAP4_SSL(GMAIL_IMAP_HOST, GMAIL_IMAP_PORT)
        conn.login(HAYEONG_EMAIL, EMAIL_PASSWORD)
        conn.select("INBOX")

        with self._lock:
            self._conn = conn

        _log("✅ Connected — entering IDLE mode")

        # Process any unread emails that arrived while we were offline
        self._fetch_unread(conn)

        # IDLE loop
        while not self._stop_event.is_set():
            try:
                # Send IDLE command
                tag = conn._new_tag().decode()
                conn.send(f"{tag} IDLE\r\n".encode())

                # Wait for server response or keepalive timeout
                # Set socket timeout to keepalive interval
                conn.socket().settimeout(IDLE_KEEPALIVE_SECONDS + 30)

                new_mail = False
                while not self._stop_event.is_set():
                    try:
                        line = conn.readline().decode("utf-8", errors="replace").strip()
                        if not line:
                            continue
                        # Only log meaningful IDLE events, not routine server continuations
                        if "EXISTS" in line or "RECENT" in line or "OK" in line:
                            if "EXISTS" in line or "RECENT" in line:
                                _log(f"IDLE: {line}")   # new mail — worth seeing

                        # New message notification
                        if "EXISTS" in line or "RECENT" in line:
                            new_mail = True

                        # Server said OK — IDLE ended normally
                        if line.startswith(f"{tag} OK"):
                            break

                        # Keepalive — server sent continuation
                        # (+ idling or similar)

                    except socket.timeout:
                        # Keepalive timeout — send DONE then re-IDLE (routine, not an error)
                        _log_quiet("keepalive timeout — re-entering IDLE")
                        break
                    except Exception as e:
                        _log_quiet(f"IDLE read error: {e}")
                        raise

                # End IDLE
                try:
                    conn.send(b"DONE\r\n")
                    conn.readline()  # consume server OK response
                except Exception:
                    pass

                # If new mail arrived, fetch it
                if new_mail:
                    self._fetch_unread(conn)

            except imaplib.IMAP4.abort as e:
                _log_quiet(f"IMAP abort: {e}")
                raise
            except Exception as e:
                _log_quiet(f"IDLE loop error: {e}")
                raise

        with self._lock:
            self._conn = None
        try:
            conn.logout()
        except Exception:
            pass

    # ─────────────────────────────────────────
    # FETCH & PROCESS NEW EMAILS
    # ─────────────────────────────────────────

    def _fetch_unread(self, conn):
        """Fetch all unread messages, classify, log, surface if needed."""
        try:
            _, data = conn.search(None, "UNSEEN")
            uids = data[0].split()
            if not uids:
                return

            _log(f"{len(uids)} unread email(s) found")

            # Load existing log UIDs to avoid reprocessing
            existing = {e.get("uid") for e in _load_log()}

            for uid_bytes in uids:
                uid = uid_bytes.decode()
                if uid in existing:
                    continue

                try:
                    _, msg_data = conn.fetch(uid_bytes, "(RFC822)")
                    raw = msg_data[0][1]
                    entry = _parse_email(raw, uid)

                    # Classify importance
                    context = ""
                    if self.get_context:
                        try:
                            context = self.get_context()
                        except Exception:
                            pass

                    importance = _classify_importance(entry, context)
                    entry["importance"] = importance

                    # Build surface text
                    sender_name = entry["from"].split("<")[0].strip() or entry["from"]
                    subject     = entry["subject"] or "(no subject)"
                    entry["surface_text"] = self._build_surface_text(
                        importance, sender_name, subject, entry["body"]
                    )

                    # Log it
                    _append_to_log(entry)
                    _log(f"[{importance.upper()}] From: {sender_name} | {subject}")

                    # Surface if important/urgent
                    if importance in ("important", "urgent") and self.on_important:
                        try:
                            self.on_important(entry)
                            # Mark as surfaced
                            entry["surfaced"] = True
                        except Exception as e:
                            _log(f"on_important callback error: {e}")

                except Exception as e:
                    _log(f"Failed to process email {uid}: {e}")

        except Exception as e:
            _log(f"_fetch_unread error: {e}")

    def _build_surface_text(
        self, importance: str, sender: str, subject: str, body: str
    ) -> str:
        """Build a natural sentence Hayeong can say to surface the email."""
        body_preview = body[:150].replace("\n", " ").strip()

        if importance == "urgent":
            return (
                f"Hey, you've got something that looks urgent from {sender} — "
                f'subject is "{subject}". Want me to read it?'
            )
        else:
            return (
                f'You got an email from {sender} — "{subject}". '
                f"Sounds like it might be worth a look. Want me to read it?"
            )

    # ─────────────────────────────────────────
    # SEARCH
    # ─────────────────────────────────────────

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        """
        Search the local email log by keyword, sender, subject, date.

        Supports natural language queries:
          "from james"        → filter by sender containing "james"
          "subject research"  → filter by subject
          "last week"         → filter by date range
          "threadripper"      → full text search across all fields
          "urgent"            → filter by importance level

        Returns list of matching email dicts, most recent first.
        """
        entries = _load_log()
        if not entries:
            return []

        q = query.lower().strip()
        results = []

        # Parse structured filters
        sender_filter  = None
        subject_filter = None
        date_filter    = None
        importance_filter = None
        keyword        = q

        # "from X"
        m = re.search(r"\bfrom[:\s]+(\S+)", q)
        if m:
            sender_filter = m.group(1)
            keyword = keyword.replace(m.group(0), "").strip()

        # "subject X"
        m = re.search(r"\bsubject[:\s]+(.+?)(?:\s+from|\s+last|\s+this|$)", q)
        if m:
            subject_filter = m.group(1).strip()
            keyword = keyword.replace(m.group(0), "").strip()

        # Date filters
        now = datetime.now()
        if "today" in q:
            date_filter = now.replace(hour=0, minute=0, second=0, microsecond=0)
            keyword = keyword.replace("today", "").strip()
        elif "yesterday" in q:
            date_filter = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0)
            keyword = keyword.replace("yesterday", "").strip()
        elif "last week" in q:
            date_filter = now - timedelta(days=7)
            keyword = keyword.replace("last week", "").strip()
        elif "this week" in q:
            date_filter = now - timedelta(days=now.weekday())
            keyword = keyword.replace("this week", "").strip()

        # Importance filter
        for level in ("urgent", "important", "normal", "noise"):
            if level in q:
                importance_filter = level
                keyword = keyword.replace(level, "").strip()
                break

        keyword = keyword.strip()

        for entry in reversed(entries):  # most recent first
            # Sender filter
            if sender_filter and sender_filter not in entry.get("from", "").lower():
                continue

            # Subject filter
            if subject_filter and subject_filter not in entry.get("subject", "").lower():
                continue

            # Importance filter
            if importance_filter and entry.get("importance") != importance_filter:
                continue

            # Date filter
            if date_filter:
                try:
                    received = datetime.fromisoformat(entry.get("received", ""))
                    if received < date_filter:
                        continue
                except Exception:
                    pass

            # Keyword search across all text fields
            if keyword:
                searchable = " ".join([
                    entry.get("from", ""),
                    entry.get("subject", ""),
                    entry.get("body", ""),
                ]).lower()
                if keyword not in searchable:
                    continue

            results.append(entry)
            if len(results) >= max_results:
                break

        return results

    def get_recent(self, n: int = 5) -> list[dict]:
        """Return the N most recent emails regardless of importance."""
        entries = _load_log()
        return list(reversed(entries[-n:])) if entries else []

    def get_unsurfaced_important(self) -> list[dict]:
        """Return important/urgent emails that haven't been surfaced yet."""
        entries = _load_log()
        return [
            e for e in reversed(entries)
            if e.get("importance") in ("important", "urgent")
            and not e.get("surfaced", False)
        ]


# ─────────────────────────────────────────────
# CONTEXT ROUTER INTEGRATION
# Format search results for Hayeong to synthesize
# ─────────────────────────────────────────────

def format_email_results(results: list[dict], query: str) -> str:
    """
    Format email search results as context for Hayeong to synthesize.
    Same pattern as web search context injection.
    """
    if not results:
        return (
            f"[EMAIL SEARCH — 0 results for: {query!r}]\n"
            "No emails found matching that search. Tell James what you searched for "
            "and suggest trying different keywords."
        )

    lines = [f"[EMAIL SEARCH RESULTS for: {query!r}]", ""]

    for i, e in enumerate(results, 1):
        sender  = e.get("from", "unknown").split("<")[0].strip()
        subject = e.get("subject", "(no subject)")
        date    = e.get("date",    "unknown date")
        body    = e.get("body",    "")[:400]
        imp     = e.get("importance", "normal")

        lines.append(f"{i}. From: {sender}")
        lines.append(f"   Subject: {subject}")
        lines.append(f"   Date: {date}  |  Importance: {imp}")
        if body:
            lines.append(f"   Preview: {body[:200]}")
        lines.append("")

    lines.append(
        "Summarize these email results naturally in your own voice. "
        "Don't list every field — tell James what he needs to know. "
        "If one email is clearly most relevant, lead with that one."
    )

    return "\n".join(lines)


# ─────────────────────────────────────────────
# STANDALONE TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("EmailMonitor — Standalone Test")
    print("=" * 60)

    if not EMAIL_PASSWORD:
        print("❌ HAYEONG_EMAIL_PASSWORD not set in .env")
        print("   Add it and try again.")
        exit(1)

    print(f"Account:  {HAYEONG_EMAIL}")
    print(f"Ollama:   {CLASSIFY_MODEL}")
    print()

    def _on_important(entry):
        print(f"\n🔔 IMPORTANT EMAIL:")
        print(f"   From:    {entry['from']}")
        print(f"   Subject: {entry['subject']}")
        print(f"   Level:   {entry['importance']}")
        print(f"   Surface: {entry['surface_text']}")

    monitor = EmailMonitor(on_important=_on_important)
    monitor.start()

    print("Monitor running. Press Ctrl+C to stop.")
    print("Send an email to", HAYEONG_EMAIL, "to test.")
    print()

    try:
        while True:
            time.sleep(10)
            cmd = ""
            # Non-blocking input check not needed for test — just let it run
    except KeyboardInterrupt:
        monitor.stop()
        print("\nDone.")
