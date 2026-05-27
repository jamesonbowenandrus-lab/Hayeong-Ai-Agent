"""
toolbox/database/plugin.py

Heartbeat plugin — reports database connection status and last operation
to Hayeong's reasoning loop every tick.

Auto-discovered by plugin_registry.py. No registration needed.
"""

import json
from pathlib import Path

from brain.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, SQLITE_DIR

_LAST_OP_FILE   = Path("H:/Databases/last_op.json")
_SQLITE_DIR_PATH = Path(SQLITE_DIR)


def tick() -> dict:
    """Called every ~2s by the plugin loop. Returns current DB awareness."""
    postgres_status      = _check_pg_status()
    active_databases     = _list_active_databases(postgres_status)
    last_op              = _read_last_op()
    sqlite_fallback      = postgres_status != "connected"

    return {
        "tool_name":            "database",
        "postgres_status":      postgres_status,
        "active_databases":     active_databases,
        "last_query":           last_op.get("sql", ""),
        "last_table":           last_op.get("table", ""),
        "last_result_rows":     last_op.get("row_count", 0),
        "last_action":          last_op.get("action", ""),
        "last_action_at":       last_op.get("at", ""),
        "sqlite_fallback_active": sqlite_fallback,
    }


def _check_pg_status() -> str:
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT,
            user=DB_USER, password=DB_PASSWORD or None,
            database="postgres", connect_timeout=2,
        )
        conn.close()
        return "connected"
    except ImportError:
        return "psycopg2 not installed"
    except Exception:
        return "unavailable"


def _list_active_databases(pg_status: str) -> list:
    dbs = []
    if pg_status == "connected":
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=DB_HOST, port=DB_PORT,
                user=DB_USER, password=DB_PASSWORD or None,
                database="postgres", connect_timeout=2,
            )
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT datname FROM pg_database "
                    "WHERE datistemplate = false ORDER BY datname"
                )
                dbs = [row[0] for row in cur.fetchall()]
            conn.close()
        except Exception:
            pass
    else:
        try:
            if _SQLITE_DIR_PATH.exists():
                dbs = [p.stem for p in sorted(_SQLITE_DIR_PATH.glob("*.db"))]
        except Exception:
            pass
    return dbs


def _read_last_op() -> dict:
    try:
        if _LAST_OP_FILE.exists():
            return json.loads(_LAST_OP_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}
