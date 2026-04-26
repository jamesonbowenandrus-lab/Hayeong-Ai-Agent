"""
live2d_controller.py
Drives Hayeong's Live2D model by reading her internal state.

Runs as a background thread at ~30fps.
Reads from: behavioral_state.json, energy_state.json, shared_state.json, voice audio
Writes to:  VTube Studio WebSocket API (port 8001)

No LLM calls. No decision making. Pure state translation.
The LLM decides mood/emotion/energy — this script faithfully reflects what's already true.

Dependencies:
  pip install websocket-client
VTube Studio must be running with API enabled:
  Settings → Plugins → Enable API (port 8001)
"""

import json
import math
import random
import threading
import time
from pathlib import Path

import numpy as np

try:
    import websocket   # websocket-client package
    VTUBE_AVAILABLE = True
except ImportError:
    VTUBE_AVAILABLE = False
    print("[live2d] websocket-client not installed — pip install websocket-client")


BASE_DIR         = Path(__file__).parent
BEHAVIORAL_STATE = BASE_DIR / "behavioral_state.json"
ENERGY_STATE     = BASE_DIR / "energy_state.json"
MIND_STATE       = BASE_DIR / "mind_state.json"
VTUBE_URL        = "ws://localhost:8001"

TARGET_FPS  = 30
FRAME_TIME  = 1.0 / TARGET_FPS

BLINK_INTERVAL_MIN = 2.0    # seconds between blinks
BLINK_INTERVAL_MAX = 6.0
BLINK_DURATION     = 0.15   # seconds for a full blink

RECONNECT_INTERVAL = 10     # seconds between VTube Studio reconnect attempts


# ─────────────────────────────────────────────
# PARAMETER MAPS
# ─────────────────────────────────────────────

# Hayeong's internal emotion states → Live2D expression file names
# Expression IDs must match names configured in the Live2D Cubism model
EMOTION_TO_EXPRESSION = {
    "neutral":          "neutral",
    "amused":           "amused",
    "quietly_pleased":  "amused",
    "curious":          "curious",
    "engaged":          "curious",
    "focused":          "focused",
    "warm":             "warm",
    "fond":             "warm",
    "affectionate":     "warm",
    "worried":          "worried",
    "unsettled":        "worried",
    "uncertain":        "worried",
    "frustrated":       "frustrated",
    "annoyed":          "frustrated",
    "irritated":        "frustrated",
    "embarrassed":      "embarrassed",
    "caught_off_guard": "embarrassed",
    "flustered":        "embarrassed",
    "proud":            "proud",
    "satisfied":        "proud",
    "quietly_smug":     "smug",
    "sad":              "sad",
    "missing_someone":  "sad",
    "wistful":          "sad",
    "protective":       "focused",
    "alert":            "focused",
    "ready":            "focused",
    "tired":            "tired",
    "flat":             "tired",
    "withdrawn":        "tired",
    "ai_pride":         "proud",
    "aviators_on":      "smug",
    "goal_drive":       "focused",
    "running_lean":     "tired",
    "depleted_quiet":   "tired",
    "content":          "neutral",
}
DEFAULT_EXPRESSION = "neutral"

# Energy level (1-5) → animation parameter multipliers
ENERGY_TO_ANIMATION = {
    1: {"breath_speed": 0.4, "idle_range": 0.2, "blink_rate": 0.6},   # depleted
    2: {"breath_speed": 0.6, "idle_range": 0.4, "blink_rate": 0.8},   # low
    3: {"breath_speed": 0.8, "idle_range": 0.6, "blink_rate": 1.0},   # nominal
    4: {"breath_speed": 1.0, "idle_range": 0.8, "blink_rate": 1.0},   # high (default)
    5: {"breath_speed": 1.2, "idle_range": 1.0, "blink_rate": 1.1},   # peak
}

# Current activity context → eye direction (x, y)  0,0 = forward
ACTIVITY_TO_EYE = {
    "talking":   (0.0,  0.0),   # forward — talking to James
    "minecraft": (0.2,  0.0),   # slight right — looking at game
    "thinking":  (0.0, -0.1),   # slight down — processing
    "reading":   (0.1,  0.0),   # slight right — reading screen
    "idle":      (0.0,  0.0),   # forward — natural idle
    "image_gen": (0.1, -0.1),   # right-down — creative focus
    "blender":   (0.2,  0.0),   # right — screen focus
    "music_gen": (0.0,  0.1),   # slight up — listening
}


# ─────────────────────────────────────────────
# AUDIO AMPLITUDE FEED (lip sync)
# Updated by voice.py during TTS playback
# ─────────────────────────────────────────────

_current_amplitude = 0.0
_amplitude_lock    = threading.Lock()


def update_audio_amplitude(amplitude: float):
    """Called by voice.py during TTS playback to drive lip sync in real time."""
    global _current_amplitude
    with _amplitude_lock:
        _current_amplitude = float(amplitude)


def _get_amplitude() -> float:
    with _amplitude_lock:
        return _current_amplitude


# ─────────────────────────────────────────────
# STATE READERS
# ─────────────────────────────────────────────

def _read_behavioral_state() -> dict:
    try:
        return json.loads(BEHAVIORAL_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_energy_level() -> int:
    """Returns discrete energy level 1–5, matching EnergyManager.level."""
    try:
        data    = json.loads(ENERGY_STATE.read_text(encoding="utf-8"))
        current = float(data.get("current", 4.0))
        return max(1, min(5, round(current)))
    except Exception:
        return 4


def _read_mind_state() -> dict:
    try:
        return json.loads(MIND_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_activity() -> str:
    """Infer current activity from shared state."""
    try:
        from state_manager import read_state
        state       = read_state()
        mc_active   = state["reasoning"].get("minecraft_session_active", False)
        active_task = state["reasoning"].get("active_task", "").lower()
        if mc_active:
            return "minecraft"
        if "image" in active_task or "comfy" in active_task:
            return "image_gen"
        if "blender" in active_task:
            return "blender"
        if "music" in active_task:
            return "music_gen"
        if active_task:
            return "reading"
    except Exception:
        pass
    return "talking"


def _read_hood_up() -> bool:
    """Returns True when the embarrassment hood-up tell is active."""
    try:
        state   = _read_behavioral_state()
        emotion = (state.get("interior_state", {})
                       .get("current", {})
                       .get("primary_emotion", ""))
        return emotion in ("embarrassed", "caught_off_guard", "flustered")
    except Exception:
        return False


# ─────────────────────────────────────────────
# VTUBE STUDIO API
# ─────────────────────────────────────────────

_ws:            "websocket.WebSocket | None" = None
_stop_event     = threading.Event()
_thread         = None


def _vtube_send(payload: dict):
    """Send a JSON payload to VTube Studio. Marks ws as None on failure."""
    global _ws
    if not _ws or not VTUBE_AVAILABLE:
        return
    try:
        _ws.send(json.dumps(payload))
    except Exception:
        _ws = None   # will trigger reconnect on next frame


def _vtube_connect() -> bool:
    """Attempt to connect to VTube Studio API. Returns True on success."""
    global _ws
    if not VTUBE_AVAILABLE:
        return False
    try:
        _ws = websocket.create_connection(VTUBE_URL, timeout=3)
        _vtube_send({
            "apiName":    "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID":  "hayeong_init",
            "messageType":"APIStateRequest",
        })
        print("[live2d] Connected to VTube Studio.")
        return True
    except Exception as e:
        print(f"[live2d] VTube Studio not reachable: {e}")
        _ws = None
        return False


def _set_expression(name: str):
    """Activate a named expression."""
    _vtube_send({
        "apiName":    "VTubeStudioPublicAPI",
        "apiVersion": "1.0",
        "requestID":  "set_expression",
        "messageType":"ExpressionActivationRequest",
        "data": {
            "expressionFile": f"{name}.exp3.json",
            "active": True,
        },
    })


def _set_parameter(param_id: str, value: float):
    """Inject a single parameter value."""
    _vtube_send({
        "apiName":    "VTubeStudioPublicAPI",
        "apiVersion": "1.0",
        "requestID":  f"param_{param_id}",
        "messageType":"InjectParameterDataRequest",
        "data": {
            "parameterValues": [
                {"id": param_id, "value": value, "weight": 1.0}
            ],
        },
    })


# ─────────────────────────────────────────────
# BLINK STATE
# ─────────────────────────────────────────────

class _BlinkState:
    def __init__(self):
        self.next_blink  = time.monotonic() + random.uniform(
            BLINK_INTERVAL_MIN, BLINK_INTERVAL_MAX
        )
        self.blink_start = None

    def update(self, energy_multiplier: float = 1.0) -> float:
        """Returns eyelid value: 1.0 = fully open, 0.0 = fully closed."""
        now = time.monotonic()

        if self.blink_start is not None:
            elapsed = now - self.blink_start
            half    = BLINK_DURATION / 2
            if elapsed < half:
                return 1.0 - (elapsed / half)       # closing
            elif elapsed < BLINK_DURATION:
                return (elapsed - half) / half        # opening
            else:
                self.blink_start = None
                interval = random.uniform(BLINK_INTERVAL_MIN, BLINK_INTERVAL_MAX)
                interval /= max(0.1, energy_multiplier)
                self.next_blink = now + interval

        if now >= self.next_blink:
            self.blink_start = now

        return 1.0   # eyes open


# ─────────────────────────────────────────────
# MAIN CONTROLLER LOOP
# ─────────────────────────────────────────────

def _controller_loop():
    blink                  = _BlinkState()
    last_expression        = None
    last_reconnect_attempt = 0.0

    print("[live2d] Controller started.")

    while not _stop_event.is_set():
        frame_start = time.monotonic()

        # Reconnect if VTube Studio dropped or wasn't running at start
        if _ws is None:
            now = time.monotonic()
            if now - last_reconnect_attempt > RECONNECT_INTERVAL:
                last_reconnect_attempt = now
                _vtube_connect()

        if _ws is None:
            _stop_event.wait(timeout=FRAME_TIME)
            continue

        try:
            # ── Read state ──
            behavioral = _read_behavioral_state()
            interior   = behavioral.get("interior_state", {}).get("current", {})
            emotion    = interior.get("primary_emotion", "neutral")
            intensity  = interior.get("intensity", 5) / 10.0   # 0.0–1.0

            energy    = _read_energy_level()
            anim      = ENERGY_TO_ANIMATION.get(energy, ENERGY_TO_ANIMATION[4])
            activity  = _read_activity()
            hood_up   = _read_hood_up()
            amplitude = _get_amplitude()

            # ── Expression ──
            expression = EMOTION_TO_EXPRESSION.get(emotion, DEFAULT_EXPRESSION)
            if expression != last_expression:
                _set_expression(expression)
                last_expression = expression

            # ── Lip sync (mouth open) ──
            mouth_open = min(1.0, amplitude * 3.0)   # scale: amplitude is typically 0–0.3
            _set_parameter("MouthOpen", mouth_open)

            # ── Blinking ──
            eye_open = blink.update(energy_multiplier=anim["blink_rate"])
            _set_parameter("EyeOpenLeft",  eye_open)
            _set_parameter("EyeOpenRight", eye_open)

            # ── Eye direction ──
            eye_x, eye_y = ACTIVITY_TO_EYE.get(activity, (0.0, 0.0))
            drift = math.sin(time.monotonic() * 0.3) * 0.05   # subtle idle drift
            _set_parameter("EyeBallX", eye_x + drift)
            _set_parameter("EyeBallY", eye_y)

            # ── Breathing idle ──
            breath = math.sin(time.monotonic() * anim["breath_speed"]) * anim["idle_range"]
            _set_parameter("ParamBreath", breath * 0.5 + 0.5)   # normalise to 0–1

            # ── Hood up (embarrassment tell) ──
            _set_parameter("HoodUp", 1.0 if hood_up else 0.0)

            # ── Expression intensity blend ──
            _set_parameter("ExpressionIntensity", intensity)

        except Exception as e:
            print(f"[live2d] Frame error: {e}")

        elapsed    = time.monotonic() - frame_start
        sleep_time = FRAME_TIME - elapsed
        if sleep_time > 0:
            _stop_event.wait(timeout=sleep_time)

    print("[live2d] Controller stopped.")


# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────

def start_live2d():
    """Start the Live2D controller thread. Non-blocking. Call once at startup."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _vtube_connect()
    _thread = threading.Thread(
        target=_controller_loop, daemon=True, name="live2d-controller"
    )
    _thread.start()


def stop_live2d():
    """Stop the Live2D controller."""
    _stop_event.set()
