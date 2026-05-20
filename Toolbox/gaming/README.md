# Toolbox/gaming

Virtual gamepad control layer. Hayeong controls games via a virtual Xbox 360
controller presented to Windows through ViGEm Bus Driver.

## Hardware Requirement

ViGEm Bus Driver is installed at `H:\GamePad\` (non-default location).
The `gamepad.py` module injects this path via `os.add_dll_directory()` before
importing vgamepad, so no system PATH change is needed.

Python dependency:
    pip install vgamepad

## Primary Use Case

Black Ops 3 Zombies split screen. James plays on Controller 1.
Hayeong controls split screen Player 2 via this virtual Controller 2.
No input conflicts — separate XInput channels.

## Files

- `gaming_tool.py`   — registry entry point, run() function
- `gamepad.py`       — virtual gamepad wrapper, high-level intent commands
- `gamepad_state.py` — state tracker, writes to Brain/state/gaming_state.json

## Calling This Tool

    action: gaming
    params:
      action=move, direction=forward, magnitude=0.8, duration=0.5

    action: gaming
    params:
      action=press, action_name=jump

    action: gaming
    params:
      action=aim, x_delta=0.5, y_delta=0.0, duration=0.2

    action: gaming
    params:
      action=release_all

    action: gaming
    params:
      action=status

## Available Actions

| Action | Required Params | Description |
|--------|----------------|-------------|
| move | direction, magnitude?, duration? | Left stick movement |
| aim | x_delta, y_delta, duration? | Right stick camera |
| press | action_name, duration? | Single button press |
| hold | action_name | Begin holding button |
| release | action_name | Release held button |
| release_all | none | Release all inputs — safe state |
| status | none | Return current gamepad state |

## Action Names (for press/hold/release)

shoot, ads, melee, reload, jump, crouch, sprint,
interact, switch_weapon, pause, back,
dpad_up, dpad_down, dpad_left, dpad_right

## State File

Current gamepad state written to: `Brain/state/gaming_state.json`
