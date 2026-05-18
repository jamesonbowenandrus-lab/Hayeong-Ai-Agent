"""
plugin_registry.py

Discovers and loads active plugins from Toolbox subdirectories.
A plugin is any folder in Toolbox/ that contains a plugin.py with a tick() function.
Plugins are optional — if none are present, nothing breaks.

Interface:
    load_plugins()                      — scan and register all available plugins
    tick_all()                          — call tick() on every loaded plugin
    get_all_context_injections(state)   — collect context lines from all plugins
"""

import importlib
import inspect
from pathlib import Path

_plugins: list = []


def load_plugins():
    """
    Scan Toolbox/ subdirectories for plugin.py files.
    Import each one and register it if it has a tick() function.
    Import failures are logged and skipped — never crash main.
    """
    toolbox_dir = Path(__file__).parent
    for folder in sorted(toolbox_dir.iterdir()):
        if not folder.is_dir() or folder.name.startswith("_"):
            continue
        if not (folder / "plugin.py").exists():
            continue
        try:
            module_path = f"toolbox.{folder.name}.plugin"
            mod = importlib.import_module(module_path)
            if hasattr(mod, "tick"):
                _plugins.append(mod)
                print(f"   [plugins] Loaded: {folder.name}")
        except Exception as e:
            print(f"   [plugins] Failed to load {folder.name}: {e}")


def tick_all():
    """Call tick() on every loaded plugin. Errors are caught per-plugin."""
    _state = None
    for plugin in _plugins:
        name = getattr(plugin, "__name__", "unknown").split(".")[-2]
        try:
            sig = inspect.signature(plugin.tick)
            if len(sig.parameters) > 0:
                if _state is None:
                    from brain.state.core_manager import read as _read
                    _state = _read()
                plugin.tick(_state)
            else:
                plugin.tick()
        except Exception as e:
            error_msg = str(e)
            if error_msg != getattr(plugin, "_last_error", None):
                print(f"[plugin:{name}] tick error: {e}")
                plugin._last_error = error_msg


def get_all_context_injections(state: dict = None) -> list:
    """
    Collect context injection lines from all plugins that provide them.
    Passes state through so plugins avoid redundant reads.
    Returns flat list of strings to extend presence context with.
    """
    lines = []
    for plugin in _plugins:
        if hasattr(plugin, "get_context_injection"):
            try:
                result = plugin.get_context_injection(state)
                if result:
                    lines.extend(result)
            except Exception:
                pass
    return lines
