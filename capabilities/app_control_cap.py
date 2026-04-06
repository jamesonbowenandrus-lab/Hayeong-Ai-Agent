# capabilities/app_control_cap.py
# Application control capability.
#
# Gives Hayeong the ability to start and close external applications.
# She calls this explicitly when asked, or it fires automatically
# via capability_loader's pre-dispatch check.

from capability_loader import result

ACTIONS = ["app_start", "app_close", "app_status"]


def handle(action: str, user_input: str, context: dict) -> dict:
    try:
        from app_manager import get_app_manager
        mgr = get_app_manager()
    except ImportError:
        return result(success=False, speak="App manager isn't available right now.")

    decision = context.get("decision", {})

    # ── Determine which app she's talking about ──
    app_id = decision.get("app_id") or _infer_app_id(user_input, mgr)

    if action == "app_status":
        status = mgr.status()
        if not status:
            return result(
                success=True,
                response="[APP STATUS] No external applications registered yet.",
            )
        lines = []
        for aid, info in status.items():
            state     = "running" if info["running"] else "stopped"
            who       = " (I started it)" if info["we_started"] else ""
            vram      = f" — {info['vram_cost']} VRAM" if info["vram_cost"] != "unknown" else ""
            lines.append(f"  {info['name']}: {state}{who}{vram}")
        return result(
            success=True,
            response="[APP STATUS]\n" + "\n".join(lines),
        )

    if not app_id:
        return result(
            success=False,
            speak="I'm not sure which application you mean. Can you be more specific?",
        )

    if action == "app_start":
        ok, msg = mgr.start(app_id)
        return result(
            success=ok,
            speak=msg,
            data={"app_id": app_id},
        )

    elif action == "app_close":
        ok, msg = mgr.close(app_id)
        return result(
            success=ok,
            speak=msg,
            data={"app_id": app_id},
        )

    return result(success=False, data={"reason": "unknown_action"})


def _infer_app_id(user_input: str, mgr) -> str | None:
    """
    Try to figure out which app the user is referring to
    by matching against known app names and ids.
    """
    u = user_input.lower()
    for app_id, app in mgr._apps.items():
        if app_id in u or app["name"].lower() in u:
            return app_id
    return None
