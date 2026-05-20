"""
Toolbox/gaming/gamepad.py

Virtual Xbox 360 controller for Hayeong.
Wraps vgamepad to expose high-level intent-based commands.
Hayeong's brain calls intents — this layer translates to XInput.

The gamepad is a singleton — one instance per session.
Call get_gamepad() to get or create the shared instance.

ViGEm Bus Driver is installed at H:\\GamePad\\ (non-default location).
We inject that path before importing vgamepad so ctypes can find
ViGEmClient.dll without it being on the system PATH.
"""

import os
import time

# ── ViGEm DLL path injection (non-default install at H:\GamePad\) ─────
_VIGEM_DIR = r"H:\GamePad"
if os.path.isdir(_VIGEM_DIR):
    os.add_dll_directory(_VIGEM_DIR)

import vgamepad as vg

_gamepad_instance = None


def get_gamepad() -> vg.VX360Gamepad:
    """Get or create the shared virtual gamepad instance."""
    global _gamepad_instance
    if _gamepad_instance is None:
        _gamepad_instance = vg.VX360Gamepad()
    return _gamepad_instance


def release_gamepad():
    """Release the gamepad instance. Call on shutdown."""
    global _gamepad_instance
    _gamepad_instance = None


# ── Stick helpers ─────────────────────────────────────────────────────

def move(direction: str, magnitude: float = 1.0, duration: float = 0.3):
    """
    Move the left stick in a named direction.
    direction: "forward", "back", "left", "right"
    magnitude: 0.0 to 1.0
    duration:  seconds to hold before releasing
    """
    pad = get_gamepad()
    x, y = 0.0, 0.0
    magnitude = max(0.0, min(1.0, magnitude))

    if direction == "forward":
        y = magnitude
    elif direction == "back":
        y = -magnitude
    elif direction == "left":
        x = -magnitude
    elif direction == "right":
        x = magnitude
    else:
        raise ValueError(f"Unknown direction: {direction}")

    pad.left_joystick_float(x_value_float=x, y_value_float=y)
    pad.update()
    time.sleep(duration)
    pad.left_joystick_float(x_value_float=0.0, y_value_float=0.0)
    pad.update()


def aim(x_delta: float, y_delta: float, duration: float = 0.15):
    """
    Move the right stick (camera/aim).
    x_delta: -1.0 (left) to 1.0 (right)
    y_delta: -1.0 (down) to 1.0 (up)
    duration: seconds to hold
    """
    pad = get_gamepad()
    x = max(-1.0, min(1.0, x_delta))
    y = max(-1.0, min(1.0, y_delta))
    pad.right_joystick_float(x_value_float=x, y_value_float=y)
    pad.update()
    time.sleep(duration)
    pad.right_joystick_float(x_value_float=0.0, y_value_float=0.0)
    pad.update()


# ── Button helpers ────────────────────────────────────────────────────

# Map readable action names to vgamepad button constants
_BUTTON_MAP = {
    # Combat (shoot/ads are handled via _TRIGGER_ACTIONS — not in this map)
    "melee":         vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,    # RS click
    "reload":        vg.XUSB_BUTTON.XUSB_GAMEPAD_X,              # X
    # Movement
    "jump":          vg.XUSB_BUTTON.XUSB_GAMEPAD_A,              # A
    "crouch":        vg.XUSB_BUTTON.XUSB_GAMEPAD_B,              # B
    "sprint":        vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,     # LS click
    # Interaction
    "interact":      vg.XUSB_BUTTON.XUSB_GAMEPAD_X,              # X (context)
    "switch_weapon": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,              # Y
    # Menu
    "pause":         vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
    "back":          vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
    # D-pad
    "dpad_up":       vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
    "dpad_down":     vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
    "dpad_left":     vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
    "dpad_right":    vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
}

# Trigger actions require analog value, not button press
_TRIGGER_ACTIONS = {"shoot", "ads"}


def press(action: str, duration: float = 0.1):
    """
    Press and release a named action button.
    action: any key from _BUTTON_MAP
    duration: seconds to hold
    """
    if action not in _BUTTON_MAP and action not in _TRIGGER_ACTIONS:
        raise ValueError(f"Unknown action: '{action}'. Valid: {list(_BUTTON_MAP.keys())}")

    pad = get_gamepad()

    if action in _TRIGGER_ACTIONS:
        if action == "shoot":
            pad.right_trigger(value=255)
        elif action == "ads":
            pad.left_trigger(value=255)
        pad.update()
        time.sleep(duration)
        if action == "shoot":
            pad.right_trigger(value=0)
        elif action == "ads":
            pad.left_trigger(value=0)
        pad.update()
    else:
        pad.press_button(button=_BUTTON_MAP[action])
        pad.update()
        time.sleep(duration)
        pad.release_button(button=_BUTTON_MAP[action])
        pad.update()


def hold(action: str):
    """Begin holding an action. Call release() to stop."""
    if action not in _BUTTON_MAP and action not in _TRIGGER_ACTIONS:
        raise ValueError(f"Unknown action: '{action}'")
    pad = get_gamepad()
    if action in _TRIGGER_ACTIONS:
        if action == "shoot":
            pad.right_trigger(value=255)
        elif action == "ads":
            pad.left_trigger(value=255)
    else:
        pad.press_button(button=_BUTTON_MAP[action])
    pad.update()


def release(action: str):
    """Release a held action."""
    if action not in _BUTTON_MAP and action not in _TRIGGER_ACTIONS:
        raise ValueError(f"Unknown action: '{action}'")
    pad = get_gamepad()
    if action in _TRIGGER_ACTIONS:
        if action == "shoot":
            pad.right_trigger(value=0)
        elif action == "ads":
            pad.left_trigger(value=0)
    else:
        pad.release_button(button=_BUTTON_MAP[action])
    pad.update()


def release_all():
    """Release all inputs. Safe state — call on errors or shutdown."""
    pad = get_gamepad()
    pad.reset()
    pad.update()
