"""
toolbox/diagnostics/diagnostics.py

Hayeong's self-diagnostic tool. Runs a fresh health check and returns a
plain-text report that Hayeong can read and relay to James.

Called via registry:
    module:   toolbox.diagnostics.diagnostics
    function: run

Params: none required. description is ignored.

Returns:
    [SUCCESS] <formatted report>   — always [SUCCESS] unless the import itself breaks
"""


def run(description: str, params: dict) -> str:
    try:
        return _run_diagnostic()
    except Exception as e:
        return f"[ERROR] diagnostics: {e}"


def _run_diagnostic() -> str:
    from brain.health import run_health_check, get_tool_errors
    from datetime import datetime

    health = run_health_check()
    errors = get_tool_errors()

    now     = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines   = [f"System diagnostic — {now}"]

    lines.append(
        f"LLM presence (11435): {'OK' if health.get('llm_presence') else 'OFFLINE'}"
    )

    healthy = health.get("tools_healthy", [])
    failed  = health.get("tools_failed",  [])

    if healthy:
        lines.append(f"Tools healthy: {', '.join(healthy)}")
    else:
        lines.append("Tools healthy: none")

    if failed:
        for tool in failed:
            err = errors.get(tool, "import error")
            lines.append(f"Tools failed:  {tool} — {err}")
    else:
        lines.append("Tools failed:  none")

    lines.append(
        f"Memory:       {'accessible' if health.get('memory_accessible') else 'INACCESSIBLE'}"
    )
    lines.append(
        f"State bus:    {'OK' if health.get('state_bus_ok') else 'ERROR'}"
    )
    lines.append(
        f"Plugins:      {health.get('plugins_loaded', 0)} loaded"
    )

    if health.get("degraded"):
        lines.append(f"Status: DEGRADED — {health.get('degraded_reason', 'unknown reason')}")
    else:
        lines.append("Status: OK")

    return "[SUCCESS] " + "\n".join(lines)
