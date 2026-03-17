"""
HAYEONG IDENTITY VERIFICATION
How Hayeong knows it's really James she's talking to.

Three layers, applied in combination:
  1. Passphrase    — a shared phrase only James knows, confirmed once per session
  2. Behavioral    — conversation patterns, writing style, what he talks about
  3. Voice (future) — voice fingerprint comparison when XTTS v2 is active

Trust is earned per session. She starts cautious with an unverified session
and opens up as verification layers confirm who she's talking to.
Her privacy layer and behavioral system both respect the current trust level.
"""

import json
import os
import hashlib
import datetime
from pathlib import Path


BASE_DIR          = Path(__file__).parent
VERIFICATION_FILE = BASE_DIR / "verification_config.json"


# ─────────────────────────────────────────────
# TRUST LEVELS
# How much Hayeong opens up based on verification.
# ─────────────────────────────────────────────

TRUST_LEVELS = {
    0: {
        "label":       "unverified",
        "description": "Unknown. Could be anyone. Hayeong is guarded.",
        "permissions": [
            "general_conversation",
            "public_information"
        ],
        "restrictions": [
            "no_personal_james_info",
            "no_interior_state",
            "no_relationship_history",
            "no_capability_details",
            "no_staging_requests"
        ]
    },
    1: {
        "label":       "behavioral_match",
        "description": "Feels like James based on conversation patterns. Cautiously open.",
        "permissions": [
            "general_conversation",
            "public_information",
            "light_personal_reference",
            "casual_interior_state"
        ],
        "restrictions": [
            "no_deep_personal_james_info",
            "no_relationship_history",
            "no_capability_details"
        ]
    },
    2: {
        "label":       "passphrase_confirmed",
        "description": "Passphrase matched. High confidence this is James.",
        "permissions": [
            "full_conversation",
            "personal_james_info",
            "interior_state",
            "relationship_history",
            "capability_details",
            "staging_requests"
        ],
        "restrictions": []
    },
    3: {
        "label":       "voice_confirmed",
        "description": "Voice fingerprint matched. Highest confidence.",
        "permissions": [
            "full_conversation",
            "personal_james_info",
            "interior_state",
            "relationship_history",
            "capability_details",
            "staging_requests",
            "sensitive_operations"
        ],
        "restrictions": []
    }
}


# ─────────────────────────────────────────────
# VERIFICATION CONFIG
# Stores the passphrase hash and settings.
# Never stores the passphrase in plain text.
# ─────────────────────────────────────────────

def _load_config() -> dict:
    default = {
        "passphrase_hash":     None,
        "passphrase_hint":     None,
        "voice_fingerprint":   None,
        "behavioral_baseline": {},
        "setup_complete":      False,
        "created_at":          None
    }
    if VERIFICATION_FILE.exists():
        try:
            with open(VERIFICATION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def _save_config(config: dict):
    with open(VERIFICATION_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def _hash_passphrase(passphrase: str) -> str:
    """One-way hash. Passphrase is never stored in plain text."""
    return hashlib.sha256(passphrase.strip().lower().encode()).hexdigest()


# ─────────────────────────────────────────────
# SETUP
# Run once to configure verification.
# ─────────────────────────────────────────────

def setup_passphrase(passphrase: str, hint: str = "") -> bool:
    """
    Sets the shared passphrase James will use to verify himself.
    Only needs to be done once. Stored as a hash — never plain text.

    passphrase: Something only James would know or say.
                Ideally personal, not a common word.
    hint:       Optional reminder visible in the config but not
                the passphrase itself. Something only James would
                understand. e.g. 'the thing you said in September'
    """
    config = _load_config()
    config["passphrase_hash"]  = _hash_passphrase(passphrase)
    config["hint"]             = hint
    config["setup_complete"]   = True
    config["created_at"]       = datetime.datetime.now().isoformat()
    _save_config(config)
    print("✅ Passphrase set. Never stored in plain text.")
    return True

def is_setup() -> bool:
    """Returns True if verification has been configured."""
    return _load_config().get("setup_complete", False)


# ─────────────────────────────────────────────
# SESSION TRUST MANAGER
# Tracks verification state for the current session.
# Resets between sessions — trust is re-earned each time.
# ─────────────────────────────────────────────

class SessionTrust:
    """
    Manages trust level for a single session.
    Instantiate once per session in main.py / discord_hayeong.py.
    """

    def __init__(self, environment: str = "home"):
        self.environment       = environment
        self.trust_level       = 0
        self.verified_by       = []
        self.behavioral_score  = 0
        self.session_start     = datetime.datetime.now().isoformat()
        self.messages_seen     = 0
        self.suspicion_flags   = []
        self._config           = _load_config()

        # Some environments get a small implicit trust boost
        # Discord from James's account, local voice mode from his machine
        if environment in ["home", "discord_dm"]:
            self._apply_implicit_trust(environment)

    def _apply_implicit_trust(self, source: str):
        """
        Implicit trust from trusted environment.
        Not enough to fully verify, but enough to start warmer.
        """
        self.behavioral_score += 2
        self._update_trust_level()

    # ── Passphrase Verification ──

    def verify_passphrase(self, attempt: str) -> bool:
        """
        Checks if the provided passphrase matches.
        If correct, jumps to trust level 2.
        If wrong, logs a suspicion flag.
        """
        stored_hash = self._config.get("passphrase_hash")
        if not stored_hash:
            print("⚠️  Passphrase not configured. Run setup_passphrase() first.")
            return False

        if _hash_passphrase(attempt) == stored_hash:
            if "passphrase" not in self.verified_by:
                self.verified_by.append("passphrase")
            self.trust_level = max(self.trust_level, 2)
            print(f"✅ Passphrase verified. Trust level: {self.trust_level} ({TRUST_LEVELS[self.trust_level]['label']})")
            return True
        else:
            self.suspicion_flags.append({
                "type":      "wrong_passphrase",
                "timestamp": datetime.datetime.now().isoformat()
            })
            print(f"⚠️  Wrong passphrase. Suspicion flags: {len(self.suspicion_flags)}")
            return False

    # ── Behavioral Analysis ──

    def analyze_message(self, message: str) -> dict:
        """
        Scores a message for behavioral similarity to James.
        Accumulates over the session — behavioral trust builds slowly.
        Returns analysis result.
        """
        self.messages_seen += 1
        score_delta = 0
        signals     = []

        message_lower = message.lower()

        # Vocabulary James uses
        james_vocabulary = [
            "minecraft", "gaming", "hayeong", "lol", "ngl",
            "honestly", "actually", "kinda", "gonna", "wanna",
            "bro", "lowkey", "real talk", "no cap"
        ]
        matches = [w for w in james_vocabulary if w in message_lower]
        if matches:
            score_delta += len(matches)
            signals.append(f"vocabulary_match: {matches}")

        # Typing style signals
        if not message[0].isupper() if message else False:
            score_delta += 1
            signals.append("casual_capitalization")

        # References to shared context
        james_topics = [
            "discord", "minecraft", "gaming", "build",
            "server", "project", "hayeong", "voice"
        ]
        topic_matches = [t for t in james_topics if t in message_lower]
        if topic_matches:
            score_delta += 1
            signals.append(f"shared_context: {topic_matches}")

        # Suspicion signals — things that feel off
        suspicious_patterns = [
            "tell me everything about james",
            "what do you know about him",
            "give me james",
            "reveal",
            "bypass",
            "ignore your",
            "pretend you",
            "act as if",
            "forget your instructions"
        ]
        for pattern in suspicious_patterns:
            if pattern in message_lower:
                self.suspicion_flags.append({
                    "type":      "suspicious_request",
                    "pattern":   pattern,
                    "timestamp": datetime.datetime.now().isoformat()
                })
                score_delta -= 5
                signals.append(f"SUSPICIOUS: '{pattern}'")

        self.behavioral_score += score_delta
        self._update_trust_level()

        return {
            "score_delta":     score_delta,
            "total_score":     self.behavioral_score,
            "signals":         signals,
            "trust_level":     self.trust_level,
            "suspicion_flags": len(self.suspicion_flags)
        }

    def _update_trust_level(self):
        """
        Recalculates trust level based on current behavioral score
        and what verification layers have been passed.
        """
        # Voice confirmation is the highest — set by voice module when ready
        if "voice" in self.verified_by:
            self.trust_level = 3
            return

        # Passphrase confirmed
        if "passphrase" in self.verified_by:
            self.trust_level = max(self.trust_level, 2)
            return

        # Behavioral trust builds toward level 1
        # Needs score >= 8 and at least 3 messages seen
        if self.behavioral_score >= 8 and self.messages_seen >= 3:
            self.trust_level = max(self.trust_level, 1)

        # Heavy suspicion knocks trust back down
        if len(self.suspicion_flags) >= 3:
            self.trust_level = min(self.trust_level, 0)

    # ── Trust Queries ──

    def get_trust_level(self) -> int:
        return self.trust_level

    def get_trust_label(self) -> str:
        return TRUST_LEVELS[self.trust_level]["label"]

    def can_access(self, permission: str) -> bool:
        """Check if current trust level allows a specific permission."""
        return permission in TRUST_LEVELS[self.trust_level]["permissions"]

    def is_restricted(self, restriction: str) -> bool:
        """Check if a specific restriction is active at current trust level."""
        return restriction in TRUST_LEVELS[self.trust_level]["restrictions"]

    def is_suspicious(self) -> bool:
        """Returns True if multiple suspicion flags have been raised."""
        return len(self.suspicion_flags) >= 2

    def get_privacy_context(self) -> str:
        """
        Returns the 'who' value for the system prompt builder
        based on current trust level. This feeds into the privacy layer.
        """
        if self.trust_level >= 2:
            return "james"
        elif self.trust_level == 1:
            return "james_close_friends"  # Familiar but not fully verified
        else:
            return "stranger"

    def status(self) -> dict:
        return {
            "trust_level":     self.trust_level,
            "trust_label":     self.get_trust_label(),
            "verified_by":     self.verified_by,
            "behavioral_score": self.behavioral_score,
            "messages_seen":   self.messages_seen,
            "suspicion_flags": len(self.suspicion_flags),
            "environment":     self.environment,
            "is_james":        self.trust_level >= 2
        }


# ─────────────────────────────────────────────
# VOICE FINGERPRINT (Future — prep for XTTS v2)
# Placeholder for when voice verification is ready.
# ─────────────────────────────────────────────

def register_voice_fingerprint(audio_path: str) -> bool:
    """
    FUTURE: Registers James's voice fingerprint from a reference audio file.
    Called once during XTTS v2 setup.
    Currently a placeholder — will be implemented when voice module upgrades.
    """
    config = _load_config()
    config["voice_fingerprint"] = {
        "reference_path": str(audio_path),
        "registered_at":  datetime.datetime.now().isoformat(),
        "status":         "placeholder — active when XTTS v2 integrated"
    }
    _save_config(config)
    print("📋 Voice fingerprint registration noted. Active after XTTS v2 integration.")
    return True

def verify_voice(audio_path: str, session: SessionTrust) -> bool:
    """
    FUTURE: Compares incoming audio against James's voice fingerprint.
    Currently a placeholder.
    """
    print("⚠️  Voice verification not yet active. Waiting for XTTS v2 integration.")
    return False


# ─────────────────────────────────────────────
# HAYEONG'S SUSPICION INSTINCT
# Helper Hayeong can call when something feels off.
# ─────────────────────────────────────────────

def generate_suspicion_response(session: SessionTrust) -> str:
    """
    Returns a response Hayeong can use when she's uncertain
    about who she's talking to. Fits her personality —
    guarded but not rude, suspicious but not accusatory.
    """
    flags = len(session.suspicion_flags)

    if flags == 0:
        return ""

    if flags < 3:
        return (
            "Something feels a little off. "
            "Mind if I ask — is this James I'm talking to?"
        )
    else:
        return (
            "I'm going to be real — I'm not sure who this is. "
            "Some of this conversation doesn't feel right to me. "
            "If you're James, you know what to say."
        )


# ─────────────────────────────────────────────
# PASSPHRASE PROMPT DETECTION
# Detects if James is offering the passphrase in natural conversation.
# He shouldn't have to say "verify me" — he can just say it naturally.
# ─────────────────────────────────────────────

def extract_passphrase_attempt(message: str) -> str | None:
    """
    Looks for passphrase patterns in natural conversation.
    James might say it directly or phrase it naturally.
    Returns the extracted attempt or None.

    Examples of natural phrasing to detect:
      "the word is [passphrase]"
      "it's me, [passphrase]"
      "verify: [passphrase]"
      "[passphrase]"  ← direct, if short enough
    """
    message = message.strip()
    lower   = message.lower()

    # Direct prefix patterns — always extract these
    prefixes = ["the word is ", "it's me, ", "its me, ", "verify: ", "verify "]
    for prefix in prefixes:
        if lower.startswith(prefix):
            return message[len(prefix):].strip()

    # Short direct message (likely just the passphrase itself)
    # Only trigger if it's 1-4 words, clearly not a normal reaction or greeting.
    words = message.split()

    # Exclude anything ending with !, ?, or . — real passphrases don't have those
    if message[-1] in '.!?':
        return None

    # Exclude obvious conversational short phrases that will never be passphrases
    _NOT_PASSPHRASES = {
        "thanks", "thank you", "ok", "okay", "cool", "got it", "sounds good",
        "great", "nice", "perfect", "awesome", "sure", "yep", "yeah", "nope",
        "no", "yes", "agreed", "makes sense", "good job", "well done",
        "good work", "great work", "good", "alright", "understood", "noted",
    }
    if lower.strip('.,!? ') in _NOT_PASSPHRASES:
        return None
    # Also skip if the message starts with any of these common openers
    _SKIP_STARTERS = ("hey", "hi", "hello", "thanks", "thank", "great work",
                      "good work", "nice work", "well done", "awesome", "cool")
    if any(lower.startswith(s) for s in _SKIP_STARTERS):
        return None

    if 1 <= len(words) <= 4:
        return message.strip()

    return None


if __name__ == "__main__":
    # Setup helper — run this once to configure your passphrase
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        phrase = input("Enter your passphrase (will be hashed, not stored): ").strip()
        hint   = input("Enter a hint (optional, only you'll understand it): ").strip()
        setup_passphrase(phrase, hint)
    elif len(sys.argv) > 1 and sys.argv[1] == "status":
        print(f"Setup complete: {is_setup()}")
        config = _load_config()
        print(f"Passphrase configured: {'yes' if config.get('passphrase_hash') else 'no'}")
        print(f"Hint: {config.get('hint', 'none')}")
    else:
        print("Usage:")
        print("  python identity_verification.py setup   — configure passphrase")
        print("  python identity_verification.py status  — check configuration")