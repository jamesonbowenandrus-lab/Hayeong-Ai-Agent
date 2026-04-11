# presence_governor.py
# Detects whether James is actively at the machine.
#
# Two modes:
#   present — James at machine. Hayeong yields GPU headroom, limits background work.
#   away    — James gone. Hayeong can use 7900 XTX more aggressively for queued tasks.
#
# Detection combines two signals:
#   1. Windows idle time (GetLastInputInfo) — seconds since last keyboard/mouse event.
#   2. Active window title — if a game, browser, or creative app is in focus, he's there.
#
# James is considered PRESENT if EITHER signal indicates activity.
# James is considered AWAY only when BOTH signals confirm absence.
#
# Usage:
#   from presence_governor import is_james_present, get_mode
#   if not is_james_present():
#       run_background_task()

import ctypes
import threading
import time
from typing import Callable, Optional


# ─────────────────────────────────────────────
# PRESENCE APP SIGNALS
# Window title keywords that mean James is actively using the machine.
# Any match = present, regardless of idle time.
# ─────────────────────────────────────────────

PRESENT_APP_SIGNALS = [
    "minecraft", "steam", "discord", "chrome", "firefox", "edge",
    "blender", "clip studio", "photoshop", "premiere", "davinci",
    "chief architect", "comfyui", "visual studio", "cursor",
    "youtube", "twitch", "netflix", "spotify",
]


# ─────────────────────────────────────────────
# WINDOWS API HELPERS
# ─────────────────────────────────────────────

class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("dwTime", ctypes.c_uint),
    ]


def _get_idle_seconds() -> float:
    """
    Returns seconds since the last keyboard or mouse input event.
    Falls back to 0.0 (assume present) if the Windows call fails.
    """
    try:
        lii = _LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
            return millis / 1000.0
    except Exception:
        pass
    return 0.0


def _get_active_window_title() -> str:
    """
    Returns the title of the currently focused window.
    Falls back to empty string if the Windows call fails.
    """
    try:
        hwnd   = ctypes.windll.user32.GetForegroundWindow()
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf    = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    except Exception:
        return ""


# ─────────────────────────────────────────────
# PRESENCE GOVERNOR
# ─────────────────────────────────────────────

class PresenceGovernor:
    """
    Detects whether James is at the machine using idle time + active window title.

    James is PRESENT if:
      - Idle time is under IDLE_AWAY_THRESHOLD, OR
      - Active window title contains a keyword from PRESENT_APP_SIGNALS

    James is AWAY only when both signals confirm absence.
    """

    IDLE_AWAY_THRESHOLD = 300   # seconds — 5 minutes of no input → away

    def is_james_present(self) -> bool:
        """Returns True if James is actively at the machine."""
        if self.idle_seconds() < self.IDLE_AWAY_THRESHOLD:
            return True
        # Idle threshold exceeded — check window title as a secondary signal.
        # A game or app in the foreground means he's still there, just not typing.
        title = _get_active_window_title().lower()
        if any(signal in title for signal in PRESENT_APP_SIGNALS):
            return True
        return False

    def get_mode(self) -> str:
        """Returns 'present' or 'away'."""
        return "present" if self.is_james_present() else "away"

    def idle_seconds(self) -> float:
        """Seconds since last keyboard or mouse input event."""
        return _get_idle_seconds()

    def active_window(self) -> str:
        """Title of the currently focused window."""
        return _get_active_window_title()

    def start_monitoring(
        self,
        on_change: Optional[Callable[[str], None]] = None,
        interval: int = 30,
    ) -> threading.Thread:
        """
        Start a background thread that polls presence every `interval` seconds.
        Calls on_change(new_mode) when the mode switches between 'present' and 'away'.
        Returns the thread so the caller can join or inspect it.

        The thread is a daemon — it stops automatically when the main process exits.
        """
        def _poll():
            last_mode = self.get_mode()
            while True:
                time.sleep(interval)
                current_mode = self.get_mode()
                if current_mode != last_mode:
                    last_mode = current_mode
                    if on_change is not None:
                        try:
                            on_change(current_mode)
                        except Exception as e:
                            print(f"   [PresenceGovernor] on_change error: {e}")

        t = threading.Thread(target=_poll, daemon=True)
        t.start()
        return t


# ─────────────────────────────────────────────
# MODULE-LEVEL SINGLETON
# Import and call directly — no instantiation needed.
# ─────────────────────────────────────────────

governor = PresenceGovernor()


def is_james_present() -> bool:
    """Returns True if James is actively at the machine."""
    return governor.is_james_present()


def get_mode() -> str:
    """Returns 'present' or 'away'."""
    return governor.get_mode()


def get_idle_seconds() -> float:
    """Seconds since last keyboard or mouse input."""
    return governor.idle_seconds()


def start_monitoring(
    on_change: Optional[Callable[[str], None]] = None,
    interval: int = 30,
) -> threading.Thread:
    """Start background presence monitoring. See PresenceGovernor.start_monitoring()."""
    return governor.start_monitoring(on_change=on_change, interval=interval)


# ─────────────────────────────────────────────
# DEBUG / TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print(f"Idle time:     {get_idle_seconds():.1f}s")
    print(f"Active window: {governor.active_window()!r}")
    print(f"Threshold:     {PresenceGovernor.IDLE_AWAY_THRESHOLD}s")
    print(f"Mode:          {get_mode()}")
    print()
    print("Polling every 5s — move mouse or open a game to confirm detection:")
    try:
        while True:
            idle   = get_idle_seconds()
            mode   = get_mode()
            window = governor.active_window()[:50]
            print(f"  [{mode:8s}] idle={idle:6.1f}s  window={window!r}          ", end="\r")
            time.sleep(5)
    except KeyboardInterrupt:
        print("\nDone.")
