"""
HAYEONG BACKUP MANAGER
Protects Hayeong from broken self-modifications.

Three layers of protection:
  1. Clean startup snapshot — saves a known-good state on every healthy boot
  2. Pre-modification checkpoint — backs up before any capability write
  3. Health check — validates critical files on startup before doing anything

If something breaks, she detects it, tells James, and they restore together.
She is never silently broken and never silently auto-restored without James knowing.
"""

import json
import os
import shutil
import datetime
from pathlib import Path


BASE_DIR    = Path(__file__).parent
BACKUP_DIR  = BASE_DIR / "backups"
BACKUP_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────
# FILES THAT ARE BACKED UP
# Core identity + all architecture configs.
# Memory is excluded — it changes every session
# and restoring old memory would lose conversations.
# ─────────────────────────────────────────────

CRITICAL_FILES = [
    "identity.json",
    "permissions_config.json",
    "capability_registry.json",
    "staging_requests.json",
    "privacy_registry.json",
    "behavioral_state.json",
    "mood.json",
    "hayeong_architecture.py",
    "system_prompt_builder.py",
    "main.py",
    "discord_hayeong.py",
    "minecraft_bridge.py",
    "voice.py",
    "long_term_memory.py",
]

# Generated capability scripts — back up the whole directory
CAPABILITY_SCRIPTS_DIR = BASE_DIR / "capabilities" / "scripts" / "generated"

# How many backups to keep before rotating old ones out
MAX_BACKUPS = 10


# ─────────────────────────────────────────────
# HEALTH CHECK
# Run this on startup before anything else.
# Validates that critical files exist and are
# valid JSON where applicable.
# ─────────────────────────────────────────────

def run_health_check() -> dict:
    """
    Validates Hayeong's critical files on startup.
    Returns a report — healthy=True means safe to proceed.
    Healthy=False means something is wrong and James should know.
    """
    issues = []
    warnings = []

    json_files = [
        "identity.json",
        "permissions_config.json",
        "capability_registry.json",
        "staging_requests.json",
        "privacy_registry.json",
        "behavioral_state.json",
        "mood.json",
    ]

    python_files = [
        "hayeong_architecture.py",
        "system_prompt_builder.py",
        "main.py",
        "voice.py",
        "long_term_memory.py",
    ]

    # Check JSON files exist and parse cleanly
    for filename in json_files:
        path = BASE_DIR / filename
        if not path.exists():
            issues.append(f"MISSING: {filename}")
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not data:
                warnings.append(f"EMPTY: {filename}")
        except json.JSONDecodeError as e:
            issues.append(f"CORRUPT JSON: {filename} — {e}")
        except Exception as e:
            issues.append(f"UNREADABLE: {filename} — {e}")

    # Check Python files exist
    for filename in python_files:
        path = BASE_DIR / filename
        if not path.exists():
            issues.append(f"MISSING: {filename}")

    # Check identity has required keys
    identity_path = BASE_DIR / "identity.json"
    if identity_path.exists():
        try:
            with open(identity_path, "r", encoding="utf-8") as f:
                identity = json.load(f)
            required_keys = ["name", "personality", "bond", "speech_style"]
            for key in required_keys:
                if key not in identity:
                    issues.append(f"identity.json missing required key: '{key}'")
        except Exception:
            pass  # Already caught above

    # Check behavioral_state has required structure
    behavioral_path = BASE_DIR / "behavioral_state.json"
    if behavioral_path.exists():
        try:
            with open(behavioral_path, "r", encoding="utf-8") as f:
                behavioral = json.load(f)
            if "interior_state" not in behavioral:
                issues.append("behavioral_state.json missing 'interior_state'")
            if "filter_layer" not in behavioral:
                issues.append("behavioral_state.json missing 'filter_layer'")
        except Exception:
            pass

    healthy   = len(issues) == 0
    available = list_backups()

    return {
        "healthy":          healthy,
        "issues":           issues,
        "warnings":         warnings,
        "backup_available": len(available) > 0,
        "latest_backup":    available[0]["label"] if available else None,
        "checked_at":       datetime.datetime.now().isoformat()
    }


# ─────────────────────────────────────────────
# CREATE BACKUP
# ─────────────────────────────────────────────

def create_backup(label: str = "auto", reason: str = "") -> dict:
    """
    Creates a timestamped backup of all critical files.

    label:  'startup'   — clean boot snapshot
            'pre_mod'   — before a capability modification
            'manual'    — James triggered it manually
            'auto'      — scheduled / other automatic

    Returns info about the backup created.
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{timestamp}_{label}"
    backup_path = BACKUP_DIR / backup_name
    backup_path.mkdir(exist_ok=True)

    backed_up = []
    failed    = []

    # Copy critical files
    for filename in CRITICAL_FILES:
        src = BASE_DIR / filename
        if src.exists():
            try:
                shutil.copy2(src, backup_path / filename)
                backed_up.append(filename)
            except Exception as e:
                failed.append(f"{filename}: {e}")

    # Copy generated capability scripts directory
    if CAPABILITY_SCRIPTS_DIR.exists():
        dest_scripts = backup_path / "capabilities" / "scripts" / "generated"
        try:
            shutil.copytree(CAPABILITY_SCRIPTS_DIR, dest_scripts)
            backed_up.append("capabilities/scripts/generated/")
        except Exception as e:
            failed.append(f"capabilities/scripts/generated/: {e}")

    # Write backup manifest
    manifest = {
        "label":      label,
        "reason":     reason,
        "timestamp":  timestamp,
        "created_at": datetime.datetime.now().isoformat(),
        "backed_up":  backed_up,
        "failed":     failed,
        "healthy":    len(failed) == 0
    }
    with open(backup_path / "MANIFEST.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # Rotate old backups if over limit
    _rotate_old_backups()

    print(f"✅ Backup created: {backup_name} ({len(backed_up)} files)")
    if failed:
        print(f"⚠️  Failed to back up: {failed}")

    return {
        "backup_name": backup_name,
        "backup_path": str(backup_path),
        "files_backed_up": len(backed_up),
        "failures": failed,
        "success": len(failed) == 0
    }


# ─────────────────────────────────────────────
# PRE-MODIFICATION CHECKPOINT
# Call this before any capability write.
# ─────────────────────────────────────────────

def checkpoint_before_modification(what: str) -> str:
    """
    Creates a backup specifically before a capability modification.
    Returns the backup name so it can be referenced if restore is needed.
    """
    result = create_backup(
        label="pre_mod",
        reason=f"Before modifying: {what}"
    )
    return result["backup_name"]


# ─────────────────────────────────────────────
# LIST BACKUPS
# ─────────────────────────────────────────────

def list_backups() -> list:
    """Returns all available backups, newest first."""
    backups = []
    for folder in sorted(BACKUP_DIR.iterdir(), reverse=True):
        if not folder.is_dir():
            continue
        manifest_path = folder / "MANIFEST.json"
        if manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                backups.append({
                    "label":      folder.name,
                    "reason":     manifest.get("reason", ""),
                    "created_at": manifest.get("created_at", ""),
                    "files":      manifest.get("files_backed_up", 0),
                    "healthy":    manifest.get("healthy", True),
                    "path":       str(folder)
                })
            except Exception:
                backups.append({
                    "label":   folder.name,
                    "healthy": False,
                    "path":    str(folder)
                })
    return backups


# ─────────────────────────────────────────────
# RESTORE FROM BACKUP
# ─────────────────────────────────────────────

def restore_from_backup(backup_name: str, files_to_restore: list = None) -> dict:
    """
    Restores files from a named backup.

    backup_name:      The backup folder name (from list_backups)
    files_to_restore: Optional list of specific files to restore.
                      If None, restores everything in the backup.

    Returns a report of what was restored.
    """
    backup_path = BACKUP_DIR / backup_name
    if not backup_path.exists():
        return {
            "success": False,
            "error":   f"Backup not found: {backup_name}"
        }

    restored = []
    failed   = []

    manifest_path = backup_path / "MANIFEST.json"
    if manifest_path.exists():
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        available_files = manifest.get("backed_up", [])
    else:
        available_files = [f.name for f in backup_path.iterdir() if f.name != "MANIFEST.json"]

    to_restore = files_to_restore if files_to_restore else available_files

    # Before restoring, back up current state so we can undo the restore if needed
    create_backup(label="pre_restore", reason=f"Before restoring from {backup_name}")

    for filename in to_restore:
        src = backup_path / filename
        dest = BASE_DIR / filename

        if not src.exists():
            failed.append(f"{filename}: not in backup")
            continue

        try:
            # Make sure destination directory exists
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            restored.append(filename)
        except Exception as e:
            failed.append(f"{filename}: {e}")

    # Restore capability scripts directory if it was backed up
    backed_up_scripts = backup_path / "capabilities" / "scripts" / "generated"
    if backed_up_scripts.exists() and (not files_to_restore or "capabilities/scripts/generated/" in files_to_restore):
        try:
            if CAPABILITY_SCRIPTS_DIR.exists():
                shutil.rmtree(CAPABILITY_SCRIPTS_DIR)
            shutil.copytree(backed_up_scripts, CAPABILITY_SCRIPTS_DIR)
            restored.append("capabilities/scripts/generated/")
        except Exception as e:
            failed.append(f"capabilities/scripts/generated/: {e}")

    print(f"✅ Restored {len(restored)} files from {backup_name}")
    if failed:
        print(f"⚠️  Failed to restore: {failed}")

    return {
        "success":  len(failed) == 0,
        "restored": restored,
        "failed":   failed,
        "from":     backup_name
    }


# ─────────────────────────────────────────────
# ROTATE OLD BACKUPS
# Keeps the most recent MAX_BACKUPS, deletes the rest.
# Always keeps all 'pre_restore' backups as a safety net.
# ─────────────────────────────────────────────

def _rotate_old_backups():
    all_backups = sorted(BACKUP_DIR.iterdir(), reverse=True)
    regular     = [b for b in all_backups if b.is_dir() and "pre_restore" not in b.name]
    protected   = [b for b in all_backups if b.is_dir() and "pre_restore" in b.name]

    # Delete oldest regular backups over the limit
    for old in regular[MAX_BACKUPS:]:
        try:
            shutil.rmtree(old)
            print(f"🗑️  Rotated old backup: {old.name}")
        except Exception as e:
            print(f"⚠️  Could not rotate {old.name}: {e}")

    # Keep only last 3 pre_restore backups
    for old in protected[3:]:
        try:
            shutil.rmtree(old)
        except Exception:
            pass


# ─────────────────────────────────────────────
# STARTUP SEQUENCE
# Call this at the very beginning of main.py
# before loading anything else.
# ─────────────────────────────────────────────

def startup_sequence() -> dict:
    """
    Full startup sequence:
      1. Run health check
      2. If healthy, create startup snapshot
      3. If unhealthy, report and offer restore

    Returns the health check result.
    Call this before instantiating HayeongArchitecture.
    """
    print("🔍 Running health check...")
    health = run_health_check()

    if health["healthy"]:
        if health["warnings"]:
            print(f"⚠️  Warnings: {health['warnings']}")
        create_backup(label="startup", reason="Clean startup snapshot")
        print("✅ Hayeong is healthy.\n")
    else:
        print("\n🚨 HEALTH CHECK FAILED")
        print("Issues found:")
        for issue in health["issues"]:
            print(f"   ✗ {issue}")

        if health["backup_available"]:
            print(f"\n💾 Latest backup available: {health['latest_backup']}")
            print("   Hayeong can be restored. Tell James what happened.")
        else:
            print("\n⚠️  No backups available yet.")
            print("   Check the files listed above manually.")

    return health


if __name__ == "__main__":
    # Run standalone to check health or create a manual backup
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "backup":
        result = create_backup(label="manual", reason="Manual backup requested")
        print(json.dumps(result, indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "list":
        backups = list_backups()
        for b in backups:
            print(f"  {b['label']}  —  {b.get('created_at', '?')}")
    elif len(sys.argv) > 1 and sys.argv[1] == "restore":
        if len(sys.argv) < 3:
            print("Usage: python backup_manager.py restore <backup_name>")
        else:
            result = restore_from_backup(sys.argv[2])
            print(json.dumps(result, indent=2))
    else:
        health = run_health_check()
        print(json.dumps(health, indent=2))
