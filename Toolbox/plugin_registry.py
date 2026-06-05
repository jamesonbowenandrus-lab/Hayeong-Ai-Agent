"""
plugin_registry.py

Discovers and loads plugins from Toolbox subdirectories.
A plugin is any folder in Toolbox/ that contains a plugin.py with a tick() function.

Persistent plugins (PERSISTENT = True in plugin.py) load at startup.
Lazy plugins load on first use of their tool — call load_plugin_for_tool(tool_name).

External interface (unchanged from original):
    load_plugins()                        — load all persistent plugins at startup
    tick_all()                            — call tick() on every loaded plugin
    get_all_context_injections(state)     — collect context lines from all loaded plugins

Added:
    load_plugin_for_tool(tool_name)       — lazy-load a tool's plugin if not yet loaded
    _load_results                         — module-level dict read by Brain/health.py
"""

import importlib
import importlib.util
import inspect
from pathlib import Path

_plugins: list = []          # loaded and active plugin modules
_lazy_loaded: set = set()    # tool names whose plugin has been lazy-loaded this session
_load_results: dict = {}     # {tool_name: True|False|None} — True=loaded, False=failed, None=lazy/not loaded
_toolbox_dir = Path(__file__).parent


def _load_single(folder: Path) -> bool:
    """
    Import and register one plugin folder.
    Each call is isolated — a failure here cannot affect any other plugin.
    Returns True if successfully loaded, False otherwise.
    """
    try:
        module_path = f"toolbox.{folder.name}.plugin"
        mod = importlib.import_module(module_path)
        if hasattr(mod, "tick"):
            _plugins.append(mod)
            _load_results[folder.name] = True
            print(f"   [plugins] Loaded: {folder.name}")
            return True
        else:
            _load_results[folder.name] = False
            print(f"   [plugins] {folder.name}/plugin.py has no tick() — skipped")
    except Exception as e:
        _load_results[folder.name] = False
        print(f"   [plugins] Failed to load {folder.name}: {e}")
    return False


def load_plugins() -> dict:
    """
    Scan Toolbox/ subdirectories for persistent plugin.py files.
    Only loads plugins where PERSISTENT = True in plugin.py.
    Lazy plugins are discovered but not loaded — they load on first tool use.

    Each plugin's discovery and load is isolated in its own try/except.
    A broken plugin cannot prevent other plugins from loading.

    Returns {plugin_name: True/False} for plugins that were attempted.
    Lazy (not-yet-loaded) plugins are omitted from the return value but
    appear in the module-level _load_results dict with value None.
    """
    for folder in sorted(_toolbox_dir.iterdir()):
        if not folder.is_dir() or folder.name.startswith("_"):
            continue
        plugin_file = folder / "plugin.py"
        if not plugin_file.exists():
            continue
        try:
            # Inspect the PERSISTENT flag without fully importing the module.
            # This lets us check the flag even if the module has broken imports.
            spec = importlib.util.spec_from_file_location(
                f"toolbox.{folder.name}.plugin", plugin_file
            )
            mod_check = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod_check)
            if getattr(mod_check, "PERSISTENT", False):
                _load_single(folder)
            else:
                _load_results[folder.name] = None  # discovered, lazy — not loaded at startup
        except Exception as e:
            _load_results[folder.name] = False
            print(f"   [plugins] Could not inspect {folder.name}: {e}")

    return {k: v for k, v in _load_results.items() if v is not None}


def load_plugin_for_tool(tool_name: str) -> bool:
    """
    Lazy-load the plugin for a specific tool if it exists and hasn't been loaded yet.
    Safe to call on every tool invocation — returns False immediately if already loaded.
    Returns True if a plugin was newly loaded, False otherwise.
    """
    if tool_name in _lazy_loaded:
        return False

    folder = _toolbox_dir / tool_name
    if not folder.is_dir():
        return False

    plugin_file = folder / "plugin.py"
    if not plugin_file.exists():
        return False

    loaded = _load_single(folder)
    if loaded:
        _lazy_loaded.add(tool_name)
    return loaded


def tick_all():
    """Call tick() on every loaded plugin. Each plugin's error is caught in isolation."""
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
    Collect context injection lines from all loaded plugins that provide them.
    Only loaded plugins contribute — lazy plugins that haven't been triggered yet
    are silent, which is correct behavior.
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
