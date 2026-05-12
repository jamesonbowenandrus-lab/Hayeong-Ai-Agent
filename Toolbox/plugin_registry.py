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

from pathlib import Path
import importlib

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
    for plugin in _plugins:
        try:
            plugin.tick()
        except Exception as e:
            name = getattr(plugin, "__name__", "unknown")
            print(f"[plugin:{name}] tick error: {e}")


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
