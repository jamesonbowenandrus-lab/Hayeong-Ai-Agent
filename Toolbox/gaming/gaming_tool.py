"""
Toolbox/gaming/gaming_tool.py

Registry entry point for Hayeong's gaming control layer.
Dispatches gamepad commands from the brain to the virtual controller.

Called via registry:
    module:   toolbox.gaming.gaming_tool
    function: run

Params the reasoning LLM should provide:
    action    (str)   — the gamepad action to perform (see below)
    direction (str)   — for move actions: "forward", "back", "left", "right"
    magnitude (float) — for move/aim: 0.0 to 1.0, default 1.0
    x_delta   (float) — for aim: horizontal, -1.0 to 1.0
    y_delta   (float) — for aim: vertical, -1.0 to 1.0
    duration  (float) — seconds to hold input, default varies by action

Actions:
    move           — left stick movement (requires direction)
    aim            — right stick camera (requires x_delta, y_delta)
    press          — single button press (requires action_name param)
    hold           — begin holding a button (requires action_name param)
    release        — release a held button (requires action_name param)
    release_all    — release everything, safe state
    status         — return current gamepad state (no input sent)

action_name values for press/hold/release:
    shoot, ads, melee, reload, jump, crouch, sprint,
    interact, switch_weapon, pause, back,
    dpad_up, dpad_down, dpad_left, dpad_right

Returns:
    str — confirmation of action taken
"""

from . import gamepad as gp
from . import gamepad_state as gs


def run(description: str, params: dict) -> str:
    """Entry point called by main.py task loop via registry."""
    try:
        action = params.get("action", "").lower()

        if not action:
            return "[ERROR] No action specified in params."

        if action == "status":
            state = gs.read_state()
            return f"[SUCCESS] Gamepad state: {state}"

        if action == "move":
            direction = params.get("direction", "")
            magnitude = float(params.get("magnitude", 1.0))
            duration  = float(params.get("duration", 0.3))
            if not direction:
                return "[ERROR] move action requires 'direction' param."
            gp.move(direction, magnitude, duration)
            result = f"Moved {direction} at magnitude {magnitude} for {duration}s"

        elif action == "aim":
            x        = float(params.get("x_delta", 0.0))
            y        = float(params.get("y_delta", 0.0))
            duration = float(params.get("duration", 0.15))
            gp.aim(x, y, duration)
            result = f"Aimed ({x}, {y}) for {duration}s"

        elif action == "press":
            action_name = params.get("action_name", "")
            duration    = float(params.get("duration", 0.1))
            if not action_name:
                return "[ERROR] press action requires 'action_name' param."
            gp.press(action_name, duration)
            result = f"Pressed {action_name} for {duration}s"

        elif action == "hold":
            action_name = params.get("action_name", "")
            if not action_name:
                return "[ERROR] hold action requires 'action_name' param."
            gp.hold(action_name)
            result = f"Holding {action_name}"

        elif action == "release":
            action_name = params.get("action_name", "")
            if not action_name:
                return "[ERROR] release action requires 'action_name' param."
            gp.release(action_name)
            result = f"Released {action_name}"

        elif action == "release_all":
            gp.release_all()
            result = "All inputs released"

        else:
            return (
                f"[ERROR] Unknown action: '{action}'. "
                "Valid: move, aim, press, hold, release, release_all, status"
            )

        gs.write_state(action, params, result)
        return f"[SUCCESS] {result}"
    except Exception as e:
        return f"[ERROR] gaming_tool: {e}"
