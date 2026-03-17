# email_bridge.py
# Shared email module for Hayeong and any future agents.
#
# Handles sending and reading from hayeong.agent@gmail.com
# Each agent identifies itself via a subject prefix:
#   [Hayeong] Task completed: fix discord voice
#   [Kai]     Daily summary ready
#
# Gmail requires an App Password (not your regular password):
#   Google Account → Security → 2-Step Verification → App Passwords
#   Create one named "Hayeong" → add to .env as HAYEONG_EMAIL_PASSWORD
#
# .env entries needed:
#   HAYEONG_EMAIL_ADDRESS=hayeong.agent@gmail.com
#   HAYEONG_EMAIL_PASSWORD=xxxx xxxx xxxx xxxx   ← App Password, spaces ok
#   JAMES_EMAIL=your.personal@email.com          ← where she sends to you
#
# Usage:
#   from email_bridge import EmailBridge
#   email = EmailBridge(agent_name="Hayeong")
#   email.send("Task completed", "I finished wiring the task manager.")
#   email.send_file("Here's your log", "/path/to/file.txt")
#   inbox = email.check_inbox(unread_only=True)

import os
import re
import json
import smtplib
import imaplib
import email
import datetime
import mimetypes
from email.mime.multipart import MIMEMultipart
from email.mime.text      import MIMEText
from email.mime.base      import MIMEBase
from email.mime.application import MIMEApplication
from email              import encoders
from pathlib            import Path
from dotenv             import load_dotenv

load_dotenv()

BASE_DIR      = Path(__file__).parent
EMAIL_LOG_PATH = BASE_DIR / "logs" / "email_log.json"
EMAIL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587
GMAIL_IMAP_HOST = "imap.gmail.com"
GMAIL_IMAP_PORT = 993

HAYEONG_EMAIL   = os.getenv("HAYEONG_EMAIL_ADDRESS", "hayeong.agent@gmail.com")
EMAIL_PASSWORD  = os.getenv("HAYEONG_EMAIL_PASSWORD", "").replace(" ", "")
JAMES_EMAIL     = os.getenv("JAMES_EMAIL", "")

# Gmail alias format — shows which agent sent it in the From field
# e.g. hayeong.agent+hayeong@gmail.com or hayeong.agent+kai@gmail.com
def _sender_alias(agent_name: str) -> str:
    base = HAYEONG_EMAIL.replace("@", f"+{agent_name.lower()}@")
    return base


# ─────────────────────────────────────────────
# EMAIL BRIDGE
# ─────────────────────────────────────────────

class EmailBridge:
    """
    Email interface for an AI agent.

    agent_name: "Hayeong" | "Kai" | whatever the agent calls itself.
                Used in subject prefix and From alias.
    """

    def __init__(self, agent_name: str = "Hayeong"):
        self.agent_name   = agent_name
        self.from_address = HAYEONG_EMAIL          # actual sending address
        self.from_alias   = _sender_alias(agent_name)  # cosmetic alias
        self.to_address   = JAMES_EMAIL
        self._check_config()

    def _check_config(self):
        if not EMAIL_PASSWORD:
            print(
                "⚠️  [EmailBridge] HAYEONG_EMAIL_PASSWORD not set in .env\n"
                "   Generate an App Password at:\n"
                "   Google Account → Security → 2-Step Verification → App Passwords"
            )
        if not JAMES_EMAIL:
            print("⚠️  [EmailBridge] JAMES_EMAIL not set in .env — sending disabled")

    # ─────────────────────────────────────────
    # SEND — plain text
    # ─────────────────────────────────────────

    def send(
        self,
        subject: str,
        body: str,
        to: str = None,
        priority: str = "normal",
    ) -> bool:
        """
        Send a plain text email.

        subject:  Will be prefixed with [AgentName] automatically.
        body:     Plain text message body.
        to:       Override recipient (defaults to JAMES_EMAIL).
        priority: "normal" | "high" — high adds importance headers.

        Returns True on success.
        """
        if not self._ready():
            return False

        full_subject = f"[{self.agent_name}] {subject}"
        recipient    = to or self.to_address

        msg = MIMEMultipart("alternative")
        msg["From"]    = f"{self.agent_name} <{self.from_address}>"
        msg["To"]      = recipient
        msg["Subject"] = full_subject
        msg["Date"]    = email.utils.formatdate(localtime=True)

        if priority == "high":
            msg["X-Priority"] = "1"
            msg["Importance"] = "High"

        # Plain text part
        plain = MIMEText(self._add_signature(body), "plain")
        msg.attach(plain)

        # HTML part — clean, readable on mobile
        html_body = self._to_html(body)
        html = MIMEText(html_body, "html")
        msg.attach(html)

        return self._smtp_send(recipient, msg, full_subject)

    # ─────────────────────────────────────────
    # SEND FILE
    # ─────────────────────────────────────────

    def send_file(
        self,
        subject: str,
        filepath: str,
        body: str = "",
        to: str = None,
    ) -> bool:
        """
        Send an email with a file attachment.

        filepath: Full path to the file to attach.
        body:     Optional message body alongside the file.
        """
        if not self._ready():
            return False

        path = Path(filepath)
        if not path.exists():
            print(f"⚠️  [EmailBridge] File not found: {filepath}")
            return False

        full_subject = f"[{self.agent_name}] {subject}"
        recipient    = to or self.to_address

        msg = MIMEMultipart()
        msg["From"]    = f"{self.agent_name} <{self.from_address}>"
        msg["To"]      = recipient
        msg["Subject"] = full_subject
        msg["Date"]    = email.utils.formatdate(localtime=True)

        # Body
        text = body or f"File attached: {path.name}"
        msg.attach(MIMEText(self._add_signature(text), "plain"))

        # Attachment
        mime_type, _ = mimetypes.guess_type(str(path))
        mime_type    = mime_type or "application/octet-stream"
        main, sub    = mime_type.split("/", 1)

        with open(path, "rb") as f:
            if main == "text":
                part = MIMEText(f.read().decode("utf-8", errors="replace"), sub)
            else:
                part = MIMEBase(main, sub)
                part.set_payload(f.read())
                encoders.encode_base64(part)

        part.add_header(
            "Content-Disposition",
            "attachment",
            filename=path.name,
        )
        msg.attach(part)

        return self._smtp_send(recipient, msg, full_subject)

    # ─────────────────────────────────────────
    # SEND TASK SUMMARY
    # Structured summary of a completed or notable task.
    # Called by task_manager integration.
    # ─────────────────────────────────────────

    def send_task_summary(self, task: dict) -> bool:
        """
        Send a formatted task summary email.
        task: a task dict from TaskManager.
        """
        state    = task.get("state", "unknown")
        title    = task.get("title", "Untitled")
        origin   = task.get("origin", "?")
        priority = task.get("priority", "medium")
        notes    = task.get("notes", [])

        subject = f"Task {state}: {title}"

        lines = [
            f"Task: {title}",
            f"Status: {state.upper()}",
            f"Priority: {priority} | Origin: {origin}",
            f"Created: {task.get('created_at', 'unknown')[:16].replace('T', ' ')}",
        ]

        if task.get("completed_at"):
            lines.append(f"Completed: {task['completed_at'][:16].replace('T', ' ')}")

        if task.get("description"):
            lines.append(f"\nDescription:\n{task['description']}")

        if task.get("blocked_reason"):
            lines.append(f"\nBlocked reason: {task['blocked_reason']}")

        if notes:
            lines.append("\nNotes:")
            for note in notes:
                ts     = note.get("timestamp", "")[:16].replace("T", " ")
                author = note.get("author", "?")
                content = note.get("content", "")
                lines.append(f"  [{ts}] {author}: {content}")

        return self.send(subject, "\n".join(lines))

    # ─────────────────────────────────────────
    # SEND NOTIFICATION
    # Short push-style alert. Keeps subject as the full message
    # so it's readable in phone notification preview.
    # ─────────────────────────────────────────

    def notify(self, message: str, priority: str = "normal") -> bool:
        """
        Send a short notification — subject IS the message.
        Designed to be readable in phone notification preview without opening.
        """
        # Keep it short enough to show fully in notification
        short = message[:80]
        return self.send(short, message, priority=priority)

    # ─────────────────────────────────────────
    # CHECK INBOX
    # Read emails sent TO the agent address.
    # Useful if James wants to send her a task or note by email.
    # ─────────────────────────────────────────

    def check_inbox(
        self,
        unread_only: bool = True,
        max_messages: int = 10,
        folder: str = "INBOX",
    ) -> list[dict]:
        """
        Check the inbox for new messages.
        Returns list of message dicts: {from, subject, body, date, uid}

        Hayeong can use this to receive tasks or notes from James by email.
        """
        if not self._ready():
            return []

        messages = []
        try:
            mail = imaplib.IMAP4_SSL(GMAIL_IMAP_HOST, GMAIL_IMAP_PORT)
            mail.login(HAYEONG_EMAIL, EMAIL_PASSWORD)
            mail.select(folder)

            search_criteria = "UNSEEN" if unread_only else "ALL"
            _, data = mail.search(None, search_criteria)

            uids = data[0].split()
            if not uids:
                mail.logout()
                return []

            # Most recent first, up to max
            for uid in reversed(uids[-max_messages:]):
                _, msg_data = mail.fetch(uid, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                            break
                else:
                    body = msg.get_payload(decode=True).decode("utf-8", errors="replace")

                messages.append({
                    "uid":     uid.decode(),
                    "from":    msg.get("From", ""),
                    "subject": msg.get("Subject", ""),
                    "date":    msg.get("Date", ""),
                    "body":    body.strip()[:2000],
                })

            mail.logout()

        except Exception as e:
            print(f"⚠️  [EmailBridge] IMAP error: {e}")

        return messages

    # ─────────────────────────────────────────
    # SEND DAILY SUMMARY
    # Called by main.py on a schedule or when James asks.
    # Summarizes task status, active processes, recent activity.
    # ─────────────────────────────────────────

    def send_daily_summary(
        self,
        task_summary: dict = None,
        process_status: dict = None,
        notes: str = "",
    ) -> bool:
        """
        Send a daily summary email to James.

        task_summary:   dict from TaskManager.summary()
        process_status: dict from ProcessManager.status()
        notes:          any freeform notes Hayeong wants to include
        """
        now   = datetime.datetime.now()
        lines = [
            f"Daily summary — {now.strftime('%A, %B %d %Y at %I:%M %p')}",
            "",
        ]

        if task_summary:
            lines += [
                "TASKS",
                f"  Active:    {task_summary.get('active', 0)}",
                f"  Backlog:   {task_summary.get('backlog', 0)}",
                f"  Blocked:   {task_summary.get('blocked', 0)}",
                f"  Completed: {task_summary.get('completed', 0)} total",
                f"  Needs code: {task_summary.get('needs_code', 0)}",
                "",
            ]

        if process_status:
            lines.append("PROCESSES")
            for name, state in process_status.items():
                icon = "✅" if state == "running" else "⛔"
                lines.append(f"  {icon} {name}: {state}")
            lines.append("")

        if notes:
            lines += ["NOTES", notes, ""]

        return self.send(
            f"Daily summary — {now.strftime('%b %d')}",
            "\n".join(lines),
        )

    # ─────────────────────────────────────────
    # INTERNAL
    # ─────────────────────────────────────────

    def _ready(self) -> bool:
        if not EMAIL_PASSWORD:
            print("⚠️  [EmailBridge] No email password — skipping send.")
            return False
        if not self.to_address:
            print("⚠️  [EmailBridge] No recipient (JAMES_EMAIL not set) — skipping send.")
            return False
        return True

    def _smtp_send(self, recipient: str, msg, subject: str) -> bool:
        try:
            with smtplib.SMTP(GMAIL_SMTP_HOST, GMAIL_SMTP_PORT) as server:
                server.ehlo()
                server.starttls()
                server.login(HAYEONG_EMAIL, EMAIL_PASSWORD)
                server.sendmail(HAYEONG_EMAIL, recipient, msg.as_string())

            print(f"📧 [{self.agent_name}] Sent: {subject[:60]}")
            self._log(recipient, subject, success=True)
            return True

        except smtplib.SMTPAuthenticationError:
            print(
                "⚠️  [EmailBridge] Authentication failed.\n"
                "   Make sure you're using an App Password, not your Gmail password.\n"
                "   Google Account → Security → 2-Step Verification → App Passwords"
            )
            self._log(recipient, subject, success=False, error="auth_failed")
            return False

        except Exception as e:
            print(f"⚠️  [EmailBridge] Send failed: {e}")
            self._log(recipient, subject, success=False, error=str(e))
            return False

    def _add_signature(self, body: str) -> str:
        sig = (
            f"\n\n—\n"
            f"{self.agent_name}\n"
            f"Sent from Hayeong's system at "
            f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        return body + sig

    def _to_html(self, body: str) -> str:
        """Convert plain text to minimal readable HTML for mobile."""
        escaped = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        paragraphs = "".join(
            f"<p>{line}</p>" if line.strip() else "<br>"
            for line in escaped.split("\n")
        )
        return f"""
        <html><body style="font-family: sans-serif; font-size: 15px; color: #222; max-width: 600px;">
        {paragraphs}
        <hr style="margin-top:24px; border:none; border-top:1px solid #ddd;">
        <p style="font-size:12px; color:#999;">{self.agent_name} — Hayeong system</p>
        </body></html>
        """

    def _log(self, recipient: str, subject: str, success: bool, error: str = None):
        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "agent":     self.agent_name,
            "to":        recipient,
            "subject":   subject[:80],
            "success":   success,
            "error":     error,
        }
        try:
            log = []
            if EMAIL_LOG_PATH.exists():
                with open(EMAIL_LOG_PATH, "r") as f:
                    log = json.load(f)
            log.append(entry)
            # Keep last 500 entries
            if len(log) > 500:
                log = log[-500:]
            with open(EMAIL_LOG_PATH, "w") as f:
                json.dump(log, f, indent=2)
        except Exception:
            pass


# ─────────────────────────────────────────────
# CONVENIENCE — pre-built instances
# Import these directly in other modules:
#   from email_bridge import hayeong_email
#   hayeong_email.send("Done", "Task completed.")
# ─────────────────────────────────────────────

hayeong_email = EmailBridge(agent_name="Hayeong")


# ─────────────────────────────────────────────
# MAIN LOOP INTEGRATION HELPERS
# Called from main.py
# ─────────────────────────────────────────────

def detect_email_command(text: str) -> tuple[str, str] | tuple[None, None]:
    """
    Detect email-related commands in conversation.
    Returns (command, remainder) or (None, None).

    Commands:
        "send_summary" — send daily summary now
        "check_inbox"  — check for new messages from James
        "notify"       — send a quick notification
    """
    t = text.lower().strip()

    if any(p in t for p in ["send me a summary", "email me a summary",
                              "send daily summary", "email your summary"]):
        return "send_summary", t

    if any(p in t for p in ["check your email", "check inbox",
                              "any emails", "new emails"]):
        return "check_inbox", t

    if any(p in t for p in ["email me", "send me a message",
                              "notify me", "send me a note"]):
        return "notify", text  # preserve case for the message

    return None, None


# ─────────────────────────────────────────────
# STANDALONE TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("=== EMAIL BRIDGE TEST ===\n")

    # Config check
    print(f"From:     {HAYEONG_EMAIL}")
    print(f"Password: {'✅ set' if EMAIL_PASSWORD else '❌ NOT SET — add to .env'}")
    print(f"To:       {JAMES_EMAIL if JAMES_EMAIL else '❌ NOT SET — add JAMES_EMAIL to .env'}")
    print()

    if not EMAIL_PASSWORD or not JAMES_EMAIL:
        print("Set HAYEONG_EMAIL_PASSWORD and JAMES_EMAIL in .env before testing.")
        sys.exit(0)

    if "--send" in sys.argv:
        print("Sending test email...")
        ok = hayeong_email.send(
            subject="Test email",
            body=(
                "This is a test from Hayeong's email bridge.\n\n"
                "If you're reading this, email sending is working correctly.\n"
                "You can now receive task summaries, notifications, and file attachments."
            ),
        )
        print(f"Result: {'✅ sent' if ok else '❌ failed'}")

    elif "--inbox" in sys.argv:
        print("Checking inbox...")
        messages = hayeong_email.check_inbox(unread_only=True)
        if messages:
            for m in messages:
                print(f"\nFrom:    {m['from']}")
                print(f"Subject: {m['subject']}")
                print(f"Date:    {m['date']}")
                print(f"Body:    {m['body'][:200]}")
        else:
            print("No unread messages.")

    else:
        print("Run with --send to test sending, --inbox to test reading.")
        print("Example: python email_bridge.py --send")
