# capabilities/email_cap.py
# Email capability — migrated out of main.py.
#
# Handles: email_check, email_send actions from context_router
# Uses EmailBridge — creates its own instance lazily.

from capability_loader import result

ACTIONS = ["email_check", "email_send"]

# ─────────────────────────────────────────────
# LAZY IMPORT
# ─────────────────────────────────────────────

_email = None

def _get_email():
    global _email
    if _email is None:
        try:
            from email_bridge import EmailBridge
            _email = EmailBridge(agent_name="Hayeong")
        except ImportError:
            pass
    return _email


# ─────────────────────────────────────────────
# HANDLER
# ─────────────────────────────────────────────

def handle(action: str, user_input: str, context: dict) -> dict:
    email = _get_email()
    if email is None:
        return result(
            success=False,
            speak="Email isn't available right now.",
        )

    if action == "email_check":
        return _handle_check(email, user_input, context)
    elif action == "email_send":
        return _handle_send(email, user_input, context)

    return result(success=False, data={"reason": "unknown_action"})


# ─────────────────────────────────────────────
# CHECK INBOX
# ─────────────────────────────────────────────

def _handle_check(email, user_input: str, context: dict) -> dict:
    try:
        messages = email.check_inbox(unread_only=True, max_messages=10)
    except Exception as e:
        return result(
            success=False,
            speak="I had trouble reaching the inbox.",
            data={"error": str(e)},
        )

    logger = context.get("logger")
    if logger:
        try:
            logger.log_capability_used(
                "email", action="check_inbox", outcome="success",
                details={"messages_found": len(messages)},
            )
        except Exception:
            pass

    if not messages:
        return result(
            success=True,
            response="[EMAIL INBOX]: No new messages.",
            speak="Inbox is clear.",
        )

    lines = [f"[EMAIL INBOX — {len(messages)} unread]"]
    for i, msg in enumerate(messages[:5], 1):
        subject = msg.get("subject", "(no subject)")
        sender  = msg.get("from", "unknown")
        date    = msg.get("date", "")
        body    = msg.get("body", "")[:300]
        lines.append(f"\n{i}. From: {sender}")
        lines.append(f"   Subject: {subject}  ({date})")
        if body:
            lines.append(f"   Preview: {body}")

    response_ctx = "\n".join(lines)
    return result(
        success=True,
        response=response_ctx,
        speak="Let me check.",
        data={"message_count": len(messages)},
    )


# ─────────────────────────────────────────────
# SEND EMAIL
# ─────────────────────────────────────────────

def _handle_send(email, user_input: str, context: dict) -> dict:
    decision = context.get("decision", {})
    subject  = decision.get("subject", "Notification")
    body     = decision.get("body") or user_input

    try:
        ok = email.send(subject=subject, body=body)
    except Exception as e:
        return result(
            success=False,
            speak="I couldn't send the email.",
            data={"error": str(e)},
        )

    if ok:
        return result(
            success=True,
            response=f"[EMAIL SENT]: Subject: {subject}. Tell James you sent the email.",
            speak="Sent.",
            data={"subject": subject},
        )
    else:
        return result(
            success=False,
            speak="Email send failed — check the email config.",
        )
