"""
HAYEONG CORE ARCHITECTURE
Manages permissions, capability layer, staging requests, and privacy.
This is the layer that enforces Hayeong's tiered access system.
"""

import json
import os
import datetime
import subprocess
from pathlib import Path

try:
    from rollback_manager import RollbackManager as _RollbackManager
    _arch_rollback = _RollbackManager()
    _ROLLBACK_AVAILABLE = True
except ImportError:
    _ROLLBACK_AVAILABLE = False


# ─────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
IDENTITY_PATH         = BASE_DIR / "identity.json"
PERMISSIONS_PATH      = BASE_DIR / "permissions_config.json"
CAPABILITY_PATH       = BASE_DIR / "capability_registry.json"
STAGING_PATH          = BASE_DIR / "staging_requests.json"
PRIVACY_PATH          = BASE_DIR / "privacy_registry.json"
BEHAVIORAL_PATH       = BASE_DIR / "behavioral_state.json"
MEMORY_PATH           = BASE_DIR / "memory.json"
MOOD_PATH             = BASE_DIR / "mood.json"
CAPABILITIES_DIR      = BASE_DIR / "capabilities"
GENERATED_SCRIPTS_DIR = BASE_DIR / "capabilities" / "scripts" / "generated"


# ─────────────────────────────────────────────
# LOADER UTILITIES
# ─────────────────────────────────────────────

def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path: Path, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ─────────────────────────────────────────────
# PERMISSION MANAGER
# Enforces the tiered access system.
# ─────────────────────────────────────────────

class PermissionManager:

    def __init__(self):
        self.permissions = load_json(PERMISSIONS_PATH)

    def can_write(self, tier: str) -> bool:
        """Returns True if the given tier allows autonomous writes."""
        tier_config = self.permissions["tiers"].get(tier)
        if not tier_config:
            return False
        return tier_config["access"] in ["read_write"]

    def get_tier_for_file(self, filename: str) -> str:
        """Identify which tier a given file belongs to."""
        for tier_name, tier_config in self.permissions["tiers"].items():
            if "files" in tier_config and filename in tier_config["files"]:
                return tier_name
            if "directories" in tier_config:
                for d in tier_config["directories"]:
                    if filename.startswith(d):
                        return tier_name
        return "unknown"

    def is_protected(self, filename: str) -> bool:
        """Returns True if Hayeong cannot autonomously modify this file."""
        tier = self.get_tier_for_file(filename)
        if tier == "unknown":
            return True  # default to protected if unknown
        return not self.can_write(tier)


# ─────────────────────────────────────────────
# CAPABILITY MANAGER
# Handles Hayeong's self-generated tools and skills.
# ─────────────────────────────────────────────

class CapabilityManager:

    def __init__(self):
        self.registry = load_json(CAPABILITY_PATH)
        GENERATED_SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    def list_active_capabilities(self) -> list:
        """Returns all currently active capabilities across all categories."""
        active = []
        for category in ["built_in_capabilities", "planned_capabilities", "self_generated_capabilities"]:
            caps = self.registry.get(category, {}).get("capabilities", [])
            active.extend([c for c in caps if c.get("status") == "active"])
        return active

    def register_new_capability(
        self,
        capability_id: str,
        name: str,
        description: str,
        script_path: str,
        created_reason: str,
        dependencies: list = None
    ) -> bool:
        """
        Hayeong registers a new self-generated capability.
        This is autonomous — no approval needed.
        A backup checkpoint is created automatically before any modification.
        """
        # ── Safety checkpoint before any capability modification ──
        try:
            from backup_manager import checkpoint_before_modification
            checkpoint_before_modification(f"register_capability: {capability_id}")
        except Exception as e:
            print(f"⚠️  Backup checkpoint failed: {e} — proceeding anyway")

        new_cap = {
            "id": capability_id,
            "name": name,
            "description": description,
            "created": datetime.datetime.now().isoformat(),
            "created_reason": created_reason,
            "script_path": script_path,
            "status": "active",
            "dependencies": dependencies or [],
            "notes": ""
        }

        # Snapshot registry before modification for rollback
        if _ROLLBACK_AVAILABLE:
            try:
                before_content = CAPABILITY_PATH.read_text(encoding="utf-8") if CAPABILITY_PATH.exists() else None
                before_state = {"path": str(CAPABILITY_PATH), "existed": CAPABILITY_PATH.exists(), "content": before_content}
            except Exception:
                before_state = {}

        self.registry["self_generated_capabilities"]["capabilities"].append(new_cap)
        self.registry["last_updated"] = datetime.datetime.now().isoformat()
        save_json(CAPABILITY_PATH, self.registry)

        # Log to rollback audit trail
        if _ROLLBACK_AVAILABLE:
            try:
                after_content = CAPABILITY_PATH.read_text(encoding="utf-8")
                _arch_rollback.log_action(
                    action_type   = "capability_registered",
                    description   = f"Registered capability: {capability_id} ({name}) — {created_reason}",
                    before_state  = before_state,
                    after_state   = {"path": str(CAPABILITY_PATH), "content": after_content},
                    triggered_by  = "hayeong_architecture",
                    approved_by   = "autonomous",
                    reversible    = True,
                    rollback_cmd  = "restore_file",
                    rollback_args = {"path": str(CAPABILITY_PATH)},
                )
            except Exception:
                pass

        return True

    def sync_mood_to_behavioral_state(self, mood: dict):
        """
        Map mood values → behavioral interior state.
        Replaces the free function mood_to_behavioral_state() in main.py.
        Call after any mood update so behavioral state stays in sync.
        """
        p = mood.get("playfulness", 0)
        f = mood.get("focus", 0)
        m = mood.get("motivation", 0)

        if p >= 3:    emotion, intensity = "amused",    6
        elif f >= 3:  emotion, intensity = "focused",   7
        elif m <= -2: emotion, intensity = "withdrawn", 4
        else:         emotion, intensity = "neutral",   3

        self.behavioral.update_interior(primary_emotion=emotion, intensity=intensity)

    def write_generated_script(self, filename: str, code: str) -> Path:
        """
        Writes a self-generated Python script to the capabilities directory.
        Hayeong owns this space — no approval needed.
        """
        script_path = GENERATED_SCRIPTS_DIR / filename
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)
        return script_path

    def execute_capability(self, script_path: str, args: list = None) -> dict:
        """
        Executes a generated capability script and returns the result.
        Runs in a subprocess for safety.
        """
        try:
            cmd = ["python", script_path] + (args or [])
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            return {
                "success": result.returncode == 0,
                "output": result.stdout.strip(),
                "error": result.stderr.strip() if result.returncode != 0 else None
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "output": "", "error": "Execution timed out"}
        except Exception as e:
            return {"success": False, "output": "", "error": str(e)}

    def disable_capability(self, capability_id: str) -> bool:
        """Disables a self-generated capability without deleting it."""
        caps = self.registry["self_generated_capabilities"]["capabilities"]
        for cap in caps:
            if cap["id"] == capability_id:
                cap["status"] = "disabled"
                save_json(CAPABILITY_PATH, self.registry)
                return True
        return False


# ─────────────────────────────────────────────
# STAGING MANAGER
# Handles Hayeong's requests to change core identity elements.
# She flags. James decides.
# ─────────────────────────────────────────────

class StagingManager:

    def __init__(self):
        self.staging = load_json(STAGING_PATH)

    def submit_request(
        self,
        category: str,
        what: str,
        why: str,
        specific_change: dict
    ) -> str:
        """
        Hayeong submits a suggested core change.
        This does NOT apply the change — it queues it for James.
        Returns the request ID.
        """
        request_id = f"stage_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        request = {
            "id": request_id,
            "timestamp": datetime.datetime.now().isoformat(),
            "category": category,
            "what": what,
            "why": why,
            "specific_change": specific_change,
            "surfaced_to_james": False,
            "james_response": None,
            "resolved": False
        }
        self.staging["pending"].append(request)
        save_json(STAGING_PATH, self.staging)
        return request_id

    def get_pending_requests(self) -> list:
        """Returns all pending staging requests not yet surfaced to James."""
        return [r for r in self.staging["pending"] if not r["surfaced_to_james"]]

    def mark_surfaced(self, request_id: str):
        """Marks a request as having been mentioned to James in conversation."""
        for r in self.staging["pending"]:
            if r["id"] == request_id:
                r["surfaced_to_james"] = True
                save_json(STAGING_PATH, self.staging)
                return

    def resolve_request(self, request_id: str, james_response: str):
        """
        James has responded to a staging request.
        Moves it from pending to reviewed.
        """
        for i, r in enumerate(self.staging["pending"]):
            if r["id"] == request_id:
                r["james_response"] = james_response
                r["resolved"] = True
                self.staging["reviewed"].append(r)
                self.staging["pending"].pop(i)
                save_json(STAGING_PATH, self.staging)
                return

    def has_pending_to_surface(self) -> bool:
        """Quick check — does Hayeong have something to bring up?"""
        return len(self.get_pending_requests()) > 0


# ─────────────────────────────────────────────
# PRIVACY MANAGER
# Handles what Hayeong protects and from whom.
# ─────────────────────────────────────────────

class PrivacyManager:

    def __init__(self):
        self.registry = load_json(PRIVACY_PATH)

    def get_context_behavior(self, who: str, info_class: str) -> dict:
        """
        Given who is asking and what class of information,
        returns how Hayeong should handle it.
        """
        # James always gets full access
        if who == "james":
            return {
                "share": True,
                "note": "Full transparency — no restrictions apply with James."
            }

        info_config = self.registry["information_classes"].get(info_class)
        if not info_config:
            return {"share": False, "note": "Unknown information class — defaulting to protected."}

        behavior = info_config.get("when_asked_by_others", "Deflect naturally.")
        return {
            "share": False,
            "note": behavior
        }

    def add_active_secret(
        self,
        secret_id: str,
        category: str,
        description: str,
        context: str,
        accessible_to: list = None,
        expiry: str = None
    ):
        """Hayeong explicitly marks something as being held privately."""
        secret = {
            "id": secret_id,
            "category": category,
            "description": description,
            "accessible_to": accessible_to or ["james"],
            "created": datetime.datetime.now().isoformat(),
            "context": context,
            "expiry": expiry
        }
        self.registry["active_secrets"]["items"].append(secret)
        save_json(PRIVACY_PATH, self.registry)

    def release_secret(self, secret_id: str):
        """Removes a secret — it no longer needs protecting."""
        items = self.registry["active_secrets"]["items"]
        self.registry["active_secrets"]["items"] = [
            s for s in items if s["id"] != secret_id
        ]
        save_json(PRIVACY_PATH, self.registry)

    def can_access(self, who: str, secret_id: str) -> bool:
        """Checks if a given person can access a specific secret."""
        for secret in self.registry["active_secrets"]["items"]:
            if secret["id"] == secret_id:
                return who in secret["accessible_to"]
        return True  # if not in secrets list, not protected


# ─────────────────────────────────────────────
# BEHAVIORAL ENGINE
# Manages interior state and what surfaces as output.
# ─────────────────────────────────────────────

class BehavioralEngine:

    def __init__(self):
        self.state = load_json(BEHAVIORAL_PATH)

    def update_interior(
        self,
        primary_emotion: str,
        intensity: int,
        secondary_emotions: list = None,
        active_thoughts: list = None,
        something_unresolved: str = None
    ):
        """Updates Hayeong's interior emotional state."""
        self.state["interior_state"]["current"] = {
            "primary_emotion": primary_emotion,
            "intensity": max(1, min(10, intensity)),
            "secondary_emotions": secondary_emotions or [],
            "active_thoughts": active_thoughts or [],
            "something_unresolved": something_unresolved,
            "last_updated": datetime.datetime.now().isoformat()
        }
        save_json(BEHAVIORAL_PATH, self.state)

    def update_context(
        self,
        who: str = None,
        situation: str = None,
        topic_weight: str = None,
        social_role: str = None,
        environment: str = None
    ):
        """Updates the active context that shapes what surfaces from her interior."""
        ctx = self.state["filter_layer"]["active_context"]
        if who:         ctx["who"] = who
        if situation:   ctx["situation"] = situation
        if topic_weight: ctx["topic_weight"] = topic_weight
        if social_role:  ctx["social_role"] = social_role
        if environment:  ctx["environment"] = environment
        save_json(BEHAVIORAL_PATH, self.state)

    def get_micro_behavior(self) -> dict | None:
        """
        Given current interior state, returns a micro-behavior that
        might spontaneously surface — or None if nothing should leak through.
        The calling code decides whether to actually use it.
        """
        emotion = self.state["interior_state"]["current"]["primary_emotion"]
        intensity = self.state["interior_state"]["current"]["intensity"]
        who = self.state["filter_layer"]["active_context"]["who"]

        # Low intensity or filtered context — nothing surfaces
        if intensity < 4 and who != "james":
            return None

        # Find matching micro-behavior
        behaviors = self.state["output_layer"]["micro_behaviors"]["examples"]
        for b in behaviors:
            if b["trigger_state"] == emotion:
                return {
                    "behavior": b["behavior"],
                    "trigger": emotion,
                    "intensity": intensity
                }
        return None

    def should_initiate(self) -> bool:
        """
        Rough check — given current interior state and context,
        is there something Hayeong might want to say unprompted?
        High intensity emotions with James present = higher likelihood.
        """
        emotion = self.state["interior_state"]["current"]["primary_emotion"]
        intensity = self.state["interior_state"]["current"]["intensity"]
        who = self.state["filter_layer"]["active_context"]["who"]

        # Hayeong doesn't speak just to fill silence
        if intensity < 5:
            return False

        # More likely to initiate with James
        if who == "james" and intensity >= 6:
            return True

        # Curiosity can prompt initiation at lower intensity
        if emotion == "curious" and intensity >= 4:
            return True

        return False

    def get_full_state_for_prompt(self) -> dict:
        """
        Returns a summarized version of her current state
        to inject into the LLM prompt context.
        """
        interior = self.state["interior_state"]["current"]
        context = self.state["filter_layer"]["active_context"]
        return {
            "interior": {
                "feeling": interior["primary_emotion"],
                "intensity": interior["intensity"],
                "also_feeling": interior["secondary_emotions"],
                "unresolved": interior["something_unresolved"]
            },
            "context": context
        }


# ─────────────────────────────────────────────
# MAIN HAYEONG ARCHITECTURE INSTANCE
# Import this elsewhere to access all systems.
# ─────────────────────────────────────────────

class HayeongArchitecture:
    """
    Single access point for all of Hayeong's architectural systems.
    Import and instantiate this where needed.
    """

    def __init__(self):
        self.permissions  = PermissionManager()
        self.capabilities = CapabilityManager()
        self.staging      = StagingManager()
        self.privacy      = PrivacyManager()
        self.behavioral   = BehavioralEngine()

    def load_identity(self) -> dict:
        """Read-only access to identity. Hayeong can read who she is."""
        return load_json(IDENTITY_PATH)

    def status(self) -> dict:
        """Quick status check — what's active, what's pending."""
        return {
            "active_capabilities":     len(self.capabilities.list_active_capabilities()),
            "pending_staging_requests": len(self.staging.get_pending_requests()),
            "staging_needs_surfacing":  self.staging.has_pending_to_surface(),
            "interior_state":           self.behavioral.state["interior_state"]["current"]["primary_emotion"],
            "interior_intensity":       self.behavioral.state["interior_state"]["current"]["intensity"],
            "active_context":           self.behavioral.state["filter_layer"]["active_context"]["who"]
        }

    def full_status(self, session=None) -> dict:
        """
        Extended status including backup and verification state.
        Accepts an optional SessionTrust instance.
        """
        from backup_manager import list_backups
        backups = list_backups()

        base = self.status()
        base["backups_available"]  = len(backups)
        base["latest_backup"]      = backups[0]["label"] if backups else None

        if session:
            base["session_trust"]  = session.get_trust_label()
            base["verified_by"]    = session.verified_by
            base["is_james"]       = session.trust_level >= 2

        return base

    def create_manual_backup(self, reason: str = "Manual backup") -> dict:
        """James can trigger a manual backup at any time."""
        from backup_manager import create_backup
        return create_backup(label="manual", reason=reason)

    def restore_backup(self, backup_name: str) -> dict:
        """Restore from a named backup. Use with caution."""
        from backup_manager import restore_from_backup
        return restore_from_backup(backup_name)

    def list_backups(self) -> list:
        """Returns all available backups."""
        from backup_manager import list_backups
        return list_backups()

    def sync_mood_to_behavioral_state(self, mood: dict):
        """Map mood values → behavioral interior state. Called after every mood update."""
        p = mood.get("playfulness", 0)
        f = mood.get("focus", 0)
        m = mood.get("motivation", 0)

        if p >= 3:    emotion, intensity = "amused",    6
        elif f >= 3:  emotion, intensity = "focused",   7
        elif m <= -2: emotion, intensity = "withdrawn", 4
        else:         emotion, intensity = "neutral",   3

        self.behavioral.update_interior(primary_emotion=emotion, intensity=intensity)


if __name__ == "__main__":
    hayeong = HayeongArchitecture()
    print("Hayeong Architecture initialized.")
    print(json.dumps(hayeong.status(), indent=2))
