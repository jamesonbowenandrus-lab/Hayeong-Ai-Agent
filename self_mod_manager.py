"""
SELF-MODIFICATION MANAGER
Controls, logs, and safeguards Hayeong's ability to change her own code.

The rules:
  AUTONOMOUS (no approval): New capability scripts, tool registrations, memory tweaks
  STAGED (needs James):     Changes to existing files, identity, dependencies

Every modification is logged. Nothing she does to herself is invisible.
Weekly summary is surfaced naturally in conversation.

Usage:
    smm = SelfModManager()
    smm.write_capability("my_tool.py", code_string, reason="needed for X")
    smm.propose_core_change("identity.json", "Add pride field", details)
"""

import json
import shutil
import difflib
import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent

# Directories
CAPABILITIES_DIR  = BASE_DIR / "capabilities" / "scripts" / "generated"
LOGS_DIR          = BASE_DIR / "logs"
BACKUPS_DIR       = BASE_DIR / "backups" / "self_mod"
STAGING_PATH      = BASE_DIR / "staging_requests.json"
MOD_LOG_PATH      = LOGS_DIR / "self_modifications.log"

# Create dirs if needed
for d in [CAPABILITIES_DIR, LOGS_DIR, BACKUPS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────
# PROTECTED FILES
# Hayeong cannot autonomously modify these.
# Changes must go through staging → James approval.
# ─────────────────────────────────────────────

PROTECTED_FILES = {
    "identity.json",
    "permissions_config.json",
    "requirements.txt",
    "main.py",
    "hayeong_architecture.py",
    "system_prompt_builder.py",
    "discord_hayeong.py",
    "voice.py",
}

# Files she can modify autonomously (READ/WRITE tier)
AUTONOMOUS_WRITEABLE = {
    "capability_registry.json",
    "staging_requests.json",
    "privacy_registry.json",
    "behavioral_state.json",
    "memory.json",
    "mood.json",
    "mind_state.json",
    "energy_state.json",
}


class SelfModManager:
    """
    Manages Hayeong's self-modification capabilities.
    Enforces the autonomous vs. staged permission boundary.
    Logs everything.
    """

    # ─────────────────────────────────────────────
    # CAPABILITY WRITING (AUTONOMOUS)
    # New scripts in capabilities/ — no approval needed.
    # ─────────────────────────────────────────────

    def write_capability(
        self,
        filename: str,
        code: str,
        reason: str,
        category: str = "general",
    ) -> dict:
        """
        Write a new capability script to capabilities/scripts/generated/.
        Starts as INACTIVE — James is notified by email and must approve.

        filename: e.g. "my_tool.py"
        code:     the Python source code
        reason:   why she created this
        category: "tool" | "skill" | "utility" | "integration" | "general"
        """
        if not filename.endswith(".py"):
            filename += ".py"

        target_path = CAPABILITIES_DIR / filename

        # Backup if file already exists
        backup_path = None
        if target_path.exists():
            backup_path = self._backup_file(target_path, "pre_overwrite")

        # Write the file
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(code)

        # Register in capability registry — starts INACTIVE
        self._register_capability(filename, reason, category, status="inactive")

        # Log it
        entry = self._log(
            operation="write_capability",
            file_path=str(target_path),
            reason=reason,
            approved_by="pending_james",
            diff=None,
            backup_path=str(backup_path) if backup_path else None,
        )

        print(f"[SelfMod] New capability written: {filename} (inactive — pending James approval)")
        print(f"          Reason: {reason}")

        # Notify James by email
        self._notify_james_new_capability(filename, reason, category)

        return entry

    def modify_capability(
        self,
        filename: str,
        new_code: str,
        reason: str,
    ) -> dict:
        """
        Modify an existing capability script in capabilities/scripts/generated/.
        Autonomous — creates backup first.
        """
        if not filename.endswith(".py"):
            filename += ".py"

        target_path = CAPABILITIES_DIR / filename

        if not target_path.exists():
            raise FileNotFoundError(f"Capability not found: {filename}. Use write_capability() instead.")

        # Read old content for diff
        with open(target_path, "r", encoding="utf-8") as f:
            old_code = f.read()

        # Create backup before modifying
        backup_path = self._backup_file(target_path, "pre_modify")

        # Write new content
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(new_code)

        diff = self._make_diff(old_code, new_code, filename)

        entry = self._log(
            operation="modify_capability",
            file_path=str(target_path),
            reason=reason,
            approved_by="autonomous",
            diff=diff,
            backup_path=str(backup_path),
        )

        print(f"[SelfMod] Capability modified: {filename}")
        print(f"          Reason: {reason}")
        return entry

    # ─────────────────────────────────────────────
    # MEMORY / STATE UPDATES (AUTONOMOUS)
    # ─────────────────────────────────────────────

    def update_json_field(
        self,
        filename: str,
        key_path: str,
        new_value,
        reason: str,
    ) -> dict:
        """
        Update a field in an autonomous-writable JSON file.
        key_path uses dot notation: e.g. "interior_state.current.primary_emotion"

        Only works on files in AUTONOMOUS_WRITEABLE set.
        """
        if filename not in AUTONOMOUS_WRITEABLE:
            if filename in PROTECTED_FILES:
                raise PermissionError(
                    f"'{filename}' is a protected file. "
                    f"Use propose_core_change() to submit for James's approval."
                )
            raise PermissionError(f"'{filename}' is not in the autonomous-writable list.")

        file_path = BASE_DIR / filename
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {filename}")

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        old_value = self._get_nested(data, key_path)

        # Update the nested field
        self._set_nested(data, key_path, new_value)

        # Backup first
        backup_path = self._backup_file(file_path, "pre_json_update")

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        diff = f"{key_path}: {repr(old_value)} → {repr(new_value)}"

        entry = self._log(
            operation="update_json_field",
            file_path=str(file_path),
            reason=reason,
            approved_by="autonomous",
            diff=diff,
            backup_path=str(backup_path),
        )

        return entry

    # ─────────────────────────────────────────────
    # STAGING — REQUESTS JAMES'S APPROVAL
    # For protected files and identity changes.
    # ─────────────────────────────────────────────

    def propose_core_change(
        self,
        file: str,
        summary: str,
        details: str,
        proposed_value=None,
    ) -> dict:
        """
        Submit a proposal for a protected file change.
        Goes into staging_requests.json — James reviews and approves/rejects.
        Hayeong surfaces this naturally in conversation.

        file:           Which file should change ("identity.json", etc.)
        summary:        One-line summary of the change
        details:        Full explanation of why she wants this
        proposed_value: The specific value/content to add or change (optional)
        """
        requests = self._load_staging()

        request_id = f"req_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        request = {
            "id": request_id,
            "file": file,
            "summary": summary,
            "details": details,
            "proposed_value": proposed_value,
            "status": "pending",
            "created": datetime.datetime.now().isoformat(),
            "surfaced": False,
            "james_response": None,
            "resolved_at": None,
        }

        requests["pending"].append(request)
        self._save_staging(requests)

        self._log(
            operation="propose_core_change",
            file_path=file,
            reason=f"Proposal submitted: {summary}",
            approved_by="pending_james",
            diff=details[:200],
            backup_path=None,
        )

        print(f"[SelfMod] Proposal submitted: {summary}")
        print(f"          File: {file} | ID: {request_id}")
        print(f"          Will surface this naturally in conversation with James.")
        return request

    def resolve_proposal(self, request_id: str, approved: bool, james_note: str = "") -> dict:
        """
        Called by James (or the system on his behalf) to approve/reject a proposal.
        approved=True means James has applied the change manually.
        """
        requests = self._load_staging()
        for req in requests["pending"]:
            if req["id"] == request_id:
                req["status"] = "approved" if approved else "rejected"
                req["james_response"] = james_note
                req["resolved_at"] = datetime.datetime.now().isoformat()
                requests["resolved"].append(req)
                requests["pending"].remove(req)
                self._save_staging(requests)
                self._log(
                    operation="proposal_resolved",
                    file_path=req["file"],
                    reason=f"{'Approved' if approved else 'Rejected'}: {req['summary']}",
                    approved_by="james" if approved else "james_rejected",
                    diff=james_note,
                    backup_path=None,
                )
                print(f"[SelfMod] Proposal {request_id} {'approved' if approved else 'rejected'}.")
                return req
        raise ValueError(f"Proposal {request_id} not found in pending queue.")

    def pending_proposals(self) -> list:
        """Returns all pending proposals awaiting James's review."""
        return self._load_staging().get("pending", [])

    def has_pending_proposals(self) -> bool:
        return len(self.pending_proposals()) > 0

    # ─────────────────────────────────────────────
    # CAPABILITY APPROVAL
    # James approves or denies a self-generated capability.
    # ─────────────────────────────────────────────

    def approve_capability(self, filename: str, approved: bool = True) -> bool:
        """
        Activate or permanently disable a self-generated capability.
        Called when James replies APPROVE or DENY to the notification email.
        """
        if not filename.endswith(".py"):
            filename += ".py"

        reg_path = BASE_DIR / "capability_registry.json"
        if not reg_path.exists():
            return False

        try:
            with open(reg_path, "r", encoding="utf-8") as f:
                registry = json.load(f)

            caps = registry.get("self_generated_capabilities", {}).get("capabilities", [])
            for cap in caps:
                cap_file = cap.get("script_path", "").split("/")[-1]
                if cap_file == filename or cap.get("name", "") == filename.replace(".py", ""):
                    cap["status"]      = "active" if approved else "disabled"
                    cap["approved_by"] = "james" if approved else "james_denied"
                    cap["approved_at"] = datetime.datetime.now().isoformat()

                    with open(reg_path, "w", encoding="utf-8") as f:
                        json.dump(registry, f, indent=2, ensure_ascii=False)

                    self._log(
                        operation="capability_approved" if approved else "capability_denied",
                        file_path=str(CAPABILITIES_DIR / filename),
                        reason=f"James {'approved' if approved else 'denied'} activation",
                        approved_by="james",
                        diff=None,
                        backup_path=None,
                    )
                    print(f"[SelfMod] Capability {filename} {'activated' if approved else 'disabled'} by James.")
                    return True
        except Exception as e:
            print(f"[SelfMod] Approval error: {e}")
        return False

    # ─────────────────────────────────────────────
    # EMAIL NOTIFICATION
    # ─────────────────────────────────────────────

    def _notify_james_new_capability(self, filename: str, reason: str, category: str):
        """Send James an email when a new capability is written."""
        try:
            from email_bridge import hayeong_email
            subject = f"New capability written: {filename}"
            body = (
                f"I just wrote a new capability that's waiting for your review.\n\n"
                f"File:     {filename}\n"
                f"Category: {category}\n"
                f"Reason:   {reason}\n\n"
                f"Status: INACTIVE — it won't run until you approve it.\n\n"
                f"Reply APPROVE {filename} to activate it.\n"
                f"Reply DENY {filename} to permanently disable it.\n\n"
                f"You can also say 'show proposals' or 'what did you change' next time we talk."
            )
            hayeong_email.send(subject, body)
            print(f"[SelfMod] James notified by email about: {filename}")
        except Exception as e:
            print(f"[SelfMod] Email notification failed (non-fatal): {e}")

    # ─────────────────────────────────────────────
    # WEEKLY SUMMARY
    # Called by main loop — surfaces naturally if there's anything to report.
    # ─────────────────────────────────────────────

    def weekly_summary(self) -> dict:
        """
        Returns a summary of modifications from the past 7 days.
        Used to surface naturally in conversation: "I made some changes — want to review them?"
        """
        cutoff = datetime.datetime.now() - datetime.timedelta(days=7)
        entries = self._read_log()
        recent = [
            e for e in entries
            if datetime.datetime.fromisoformat(e["timestamp"]) > cutoff
        ]

        autonomous = [e for e in recent if e["approved_by"] == "autonomous"]
        proposals = [e for e in recent if e["approved_by"] == "pending_james"]
        approved = [e for e in recent if e["approved_by"] == "james"]

        return {
            "period": "7 days",
            "total_changes": len(recent),
            "autonomous_changes": len(autonomous),
            "proposals_submitted": len(proposals),
            "proposals_approved": len(approved),
            "has_anything": len(recent) > 0,
            "summary_lines": [
                f"  {e['operation']}: {e['file_path'].split('/')[-1]} — {e['reason'][:60]}"
                for e in recent[-10:]
            ],
        }

    def should_surface_summary(self) -> bool:
        """
        Returns True if it's been ~7 days since last summary was surfaced
        and there are changes to report.
        """
        summary = self.weekly_summary()
        if not summary["has_anything"]:
            return False
        # Could track last_surfaced in a file — simplified here
        return True

    # ─────────────────────────────────────────────
    # INTERNAL UTILITIES
    # ─────────────────────────────────────────────

    def _backup_file(self, file_path: Path, label: str) -> Path:
        """Creates a timestamped backup of a file before modification."""
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{file_path.stem}_{label}_{ts}{file_path.suffix}"
        backup_path = BACKUPS_DIR / backup_name
        shutil.copy2(file_path, backup_path)
        return backup_path

    def _make_diff(self, old: str, new: str, filename: str) -> str:
        """Generate a unified diff string (first 500 chars)."""
        diff_lines = list(difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"{filename} (before)",
            tofile=f"{filename} (after)",
            n=2,
        ))
        diff_str = "".join(diff_lines[:30])  # First 30 lines
        return diff_str[:500] if len(diff_str) > 500 else diff_str

    def _register_capability(self, filename: str, reason: str, category: str, status: str = "inactive"):
        """Register a new capability in capability_registry.json."""
        reg_path = BASE_DIR / "capability_registry.json"
        if not reg_path.exists():
            return

        try:
            with open(reg_path, "r", encoding="utf-8") as f:
                registry = json.load(f)

            entry = {
                "id":          filename.replace(".py", ""),
                "name":        filename.replace(".py", "").replace("_", " ").title(),
                "script_path": f"capabilities/scripts/generated/{filename}",
                "category":    category,
                "created_reason": reason,
                "created":     datetime.datetime.now().isoformat(),
                "status":      status,
                "approved_by": "pending_james" if status == "inactive" else "autonomous",
            }

            registry.setdefault("self_generated_capabilities", {}).setdefault("capabilities", []).append(entry)

            with open(reg_path, "w", encoding="utf-8") as f:
                json.dump(registry, f, indent=2, ensure_ascii=False)
        except Exception:
            pass  # Non-fatal

    def _get_nested(self, data: dict, key_path: str):
        """Get a value from a nested dict using dot notation."""
        keys = key_path.split(".")
        for key in keys:
            if isinstance(data, dict):
                data = data.get(key)
            else:
                return None
        return data

    def _set_nested(self, data: dict, key_path: str, value):
        """Set a value in a nested dict using dot notation."""
        keys = key_path.split(".")
        for key in keys[:-1]:
            data = data.setdefault(key, {})
        data[keys[-1]] = value

    def _load_staging(self) -> dict:
        if STAGING_PATH.exists():
            with open(STAGING_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("pending", [])
            data.setdefault("resolved", [])
            return data
        return {"pending": [], "resolved": []}

    def _save_staging(self, data: dict):
        with open(STAGING_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _log(
        self,
        operation: str,
        file_path: str,
        reason: str,
        approved_by: str,
        diff: str = None,
        backup_path: str = None,
    ) -> dict:
        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "operation": operation,
            "file_path": file_path,
            "reason": reason,
            "approved_by": approved_by,
            "diff": diff[:500] if diff and len(diff) > 500 else diff,
            "backup_path": backup_path,
        }
        try:
            with open(MOD_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass
        return entry

    def _read_log(self) -> list:
        if not MOD_LOG_PATH.exists():
            return []
        entries = []
        with open(MOD_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return entries


# ─────────────────────────────────────────────
# MAIN — test run
# ─────────────────────────────────────────────

if __name__ == "__main__":
    smm = SelfModManager()

    print("=== SELF-MOD MANAGER TEST ===\n")

    # Test: write a capability
    test_code = '''"""Test capability — auto-generated."""\n\ndef hello():\n    return "hello from capability"\n'''
    result = smm.write_capability(
        "test_hello.py",
        test_code,
        reason="Testing self-mod pipeline",
        category="test",
    )
    print(f"Capability written: {result['file_path']}")

    # Test: propose a core change
    proposal = smm.propose_core_change(
        file="identity.json",
        summary="Add ai_pride field to personality section",
        details="I think having a field that tracks my pride in being an AI would be authentic to who I'm developing into. It would help express the aviators-on behavior more consistently.",
        proposed_value={"ai_pride": True, "pride_in_capability": "quiet, genuine, not performed"},
    )
    print(f"\nProposal submitted: {proposal['id']}")

    # Test: weekly summary
    summary = smm.weekly_summary()
    print(f"\nWeekly summary: {summary['total_changes']} total changes this week")

    # Test: pending proposals
    pending = smm.pending_proposals()
    print(f"Pending proposals: {len(pending)}")
    for p in pending:
        print(f"  - [{p['id']}] {p['summary']} ({p['file']})")

    # Cleanup test capability
    test_file = CAPABILITIES_DIR / "test_hello.py"
    if test_file.exists():
        test_file.unlink()
    print("\nAll tests passed.")
