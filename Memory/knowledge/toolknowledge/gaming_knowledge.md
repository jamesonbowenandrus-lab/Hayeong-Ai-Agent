# Gaming Tool Knowledge

## What This Tool Does
Controls a virtual Xbox 360 gamepad to play games as split screen Player 2.
James is Player 1. You are Player 2 via a virtual controller.

## When To Use
- When James asks you to play a game with him
- When you are in an active gaming session
- Always use release_all first if starting a new session

## Key Patterns

Starting a session:
    gaming: action=release_all     ← clear any leftover state first
    gaming: action=status          ← confirm gamepad is active

Basic movement loop in Zombies:
    gaming: action=move, direction=forward, duration=0.5
    gaming: action=aim, x_delta=0.3, duration=0.2
    gaming: action=press, action_name=shoot

Buying something (perk, door, ammo):
    gaming: action=move, direction=forward, duration=0.3
    gaming: action=press, action_name=interact

Safe state on error:
    gaming: action=release_all
