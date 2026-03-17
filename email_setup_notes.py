# ─────────────────────────────────────────────
# ADD THESE TO YOUR .env FILE (H:\hayeong\_env → rename to .env)
# ─────────────────────────────────────────────

DISCORD_TOKEN=your_existing_token
OWNER_DISCORD_ID=your_existing_id

# Email — Hayeong's outbox
HAYEONG_EMAIL_ADDRESS=hayeong.agent@gmail.com
HAYEONG_EMAIL_PASSWORD=xxxx xxxx xxxx xxxx    # ← App Password (spaces are fine)
JAMES_EMAIL=your.personal.email@gmail.com     # ← where she sends things to you

# Optional: Claude API key for Tier 2 code generation (code_consultant.py)
# ANTHROPIC_API_KEY=sk-ant-...


# ─────────────────────────────────────────────
# WIRING SNIPPET — paste into main.py
# Add after the self_mod_manager import block (around line 65)
# ─────────────────────────────────────────────

# In the imports section, add:
try:
    from email_bridge import EmailBridge, hayeong_email, detect_email_command
    EMAIL_AVAILABLE = True
except ImportError:
    EMAIL_AVAILABLE = False
    print("⚠️  email_bridge.py not found — email inactive")


# In main() → STEP 4 (after tasks and smm init), add:
#   email = hayeong_email if EMAIL_AVAILABLE else None


# In the main loop, add after the task commands block:

        # ── Email commands ──
        if EMAIL_AVAILABLE:
            email_cmd, email_remainder = detect_email_command(user_input)

            if email_cmd == "send_summary":
                task_sum  = tasks.summary() if tasks else None
                proc_stat = procs.status()
                ok = hayeong_email.send_daily_summary(
                    task_summary   = task_sum,
                    process_status = proc_stat,
                )
                resp = "Sent you a summary." if ok else "Couldn't send — check email config."
                speak(resp, emotion="neutral")
                memory.append({"role": "user", "content": user_input})
                memory.append({"role": "AI",   "content": resp})
                save_memory(memory)
                print()
                continue

            elif email_cmd == "check_inbox":
                messages = hayeong_email.check_inbox(unread_only=True)
                if messages:
                    resp = f"{len(messages)} new message{'s' if len(messages) != 1 else ''}."
                    for m in messages[:3]:
                        print(f"  From: {m['from']}")
                        print(f"  Subject: {m['subject']}")
                        print(f"  {m['body'][:150]}\n")
                else:
                    resp = "Nothing new."
                speak(resp, emotion="neutral")
                memory.append({"role": "user", "content": user_input})
                memory.append({"role": "AI",   "content": resp})
                save_memory(memory)
                print()
                continue

            elif email_cmd == "notify":
                # Extract the message after "email me" / "notify me" etc.
                msg_text = re.sub(
                    r'(email me|send me a message|notify me|send me a note)\s*',
                    '', user_input, flags=re.IGNORECASE
                ).strip() or user_input
                ok = hayeong_email.notify(msg_text)
                resp = "Done." if ok else "Couldn't send — check email config."
                speak(resp, emotion="neutral")
                memory.append({"role": "user", "content": user_input})
                memory.append({"role": "AI",   "content": resp})
                save_memory(memory)
                print()
                continue


# ─────────────────────────────────────────────
# SECOND AGENT USAGE (future — Kai or whoever)
# In that agent's main file, just import with a different name:
# ─────────────────────────────────────────────

# from email_bridge import EmailBridge
# kai_email = EmailBridge(agent_name="Kai")
# kai_email.send("Task done", "Finished the analysis.")
#
# Subject will show: [Kai] Task done
# From alias will show: hayeong.agent+kai@gmail.com
# Same inbox, clearly labeled, filtered separately in Gmail if you want.
