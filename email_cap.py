# capabilities/email_cap.py
# Email capability — check inbox and send notifications.

import re
from capability_loader import result

ACTIONS = ["email_check", "email_send"]


def handle(action: str, user_input: str, context: dict) -> dict:
    email         = context.get("email")
    email_monitor = context.get("email_monitor")

    if email is None:
        return result(success=False, speak="Email isn't set up right now.")

    try:
        if action == "email_check":
            if email_monitor:
                unsurfaced = email_monitor.get_unsurfaced_important()
                recent     = email_monitor.get_recent(5)
                if unsurfaced:
                    ctx = f"[EMAIL] {len(unsurfaced)} important email(s) James hasn't seen. Show him the details."
                elif recent:
                    sender = recent[0].get("from", "").split("<")[0].strip()
                    subj   = recent[0].get("subject", "(no subject)")
                    ctx    = f"[EMAIL] Inbox quiet. Last email: from {sender} — {subj}."
                else:
                    ctx = "[EMAIL] Inbox is empty / nothing new."
            else:
                msgs = email.check_inbox(unread_only=True)
                ctx  = f"[EMAIL] {len(msgs)} new message(s)." if msgs else "[EMAIL] Nothing new in inbox."

            return result(success=True, response=ctx)

        elif action == "email_send":
            msg_text = re.sub(
                r'(?i)(email me|notify me|ping me|send me)[:\s]*', '', user_input
            ).strip() or "Hello from Hayeong!"
            ok  = email.notify(msg_text)
            ctx = "[EMAIL SENT] Notification delivered." if ok else "[EMAIL] Send failed — check config."
            return result(success=True, response=ctx)

    except Exception as e:
        return result(success=False, data={"error": str(e)})
