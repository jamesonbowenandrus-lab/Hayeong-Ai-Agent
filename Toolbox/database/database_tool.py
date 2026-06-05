"""
toolbox/database/database_tool.py

Hayeong's database control layer.
PostgreSQL primary (localhost:5432), SQLite fallback (H:/Databases/sqlite/).
Both backends store data on the H: drive.

Called via registry:
    module:   toolbox.database.database_tool
    function: run

Actions:
    test_connection, create_db, create_table, insert, query, update, delete,
    list_dbs, list_tables, describe_table, drop_table

Returns:
    str — "[SUCCESS] ..." | "[ERROR] ..." | "[PARTIAL] ..."
    Never raises. All errors are returned as strings.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from brain.config import (
    POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB,
    SQLITE_DIR, SQLITE_DEFAULT_DB,
)

SQLITE_DIR_PATH = Path(SQLITE_DIR)

# Written after each operation — read by plugin.py for heartbeat context
_LAST_OP_FILE = Path("H:/Databases/last_op.json")


def run(description: str, params: dict) -> str:
    try:
        return _dispatch(description, params)
    except Exception as e:
        return f"[ERROR] database_tool: {e}"


# ─────────────────────────────────────────────
# STATE TRACKING (for plugin.py)
# ─────────────────────────────────────────────

def _write_last_op(action: str, database: str, table: str, row_count: int = 0, sql: str = ""):
    try:
        _LAST_OP_FILE.parent.mkdir(parents=True, exist_ok=True)
        _LAST_OP_FILE.write_text(
            json.dumps({
                "action":    action,
                "database":  database,
                "table":     table,
                "row_count": row_count,
                "sql":       sql[:200],
                "at":        datetime.now().isoformat(),
            }, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


# ─────────────────────────────────────────────
# CONNECTION HELPERS
# ─────────────────────────────────────────────

def _check_pg() -> bool:
    """Quick check — True if PostgreSQL is reachable on localhost."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=POSTGRES_HOST, port=POSTGRES_PORT,
            user=POSTGRES_USER, password=POSTGRES_PASSWORD or None,
            database="postgres", connect_timeout=3,
        )
        conn.close()
        return True
    except Exception:
        return False


def _pg_connect(database: str = None):
    """Open a PostgreSQL connection. Raises on failure — wrap in try/except."""
    import psycopg2
    return psycopg2.connect(
        host=POSTGRES_HOST, port=POSTGRES_PORT,
        user=POSTGRES_USER, password=POSTGRES_PASSWORD or None,
        database=database or POSTGRES_DB,
        connect_timeout=5,
    )


def _ensure_pg_db(database: str):
    """Create the PostgreSQL database if it doesn't exist yet."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=POSTGRES_HOST, port=POSTGRES_PORT,
            user=POSTGRES_USER, password=POSTGRES_PASSWORD or None,
            database="postgres", connect_timeout=5,
        )
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,))
            if not cur.fetchone():
                cur.execute(f'CREATE DATABASE "{database}"')
        conn.close()
    except Exception:
        pass


def _sqlite_path(database: str) -> Path:
    SQLITE_DIR_PATH.mkdir(parents=True, exist_ok=True)
    return SQLITE_DIR_PATH / f"{database}.db"


# ─────────────────────────────────────────────
# DISPATCH
# ─────────────────────────────────────────────

def _dispatch(description: str, params: dict) -> str:
    action   = str(params.get("action", "")).lower().strip()
    database = str(params.get("database", POSTGRES_DB)).strip() or POSTGRES_DB

    if not action:
        return (
            "[ERROR] database_tool: 'action' param required. "
            "Options: test_connection, create_db, create_table, insert, query, update, delete, "
            "list_dbs, list_tables, describe_table, drop_table"
        )

    pg = _check_pg()

    if action == "test_connection":
        return _test_connection(pg)
    if action == "create_db":
        return _create_db(database, pg)
    if action == "list_dbs":
        return _list_dbs(pg)
    if action == "list_tables":
        return _list_tables(database, pg)
    if action == "describe_table":
        table = str(params.get("table", "")).strip()
        if not table:
            return "[ERROR] database_tool: 'table' param required for describe_table"
        return _describe_table(database, table, pg)
    if action == "create_table":
        table  = str(params.get("table", "")).strip()
        schema = params.get("schema", {})
        if not table:
            return "[ERROR] database_tool: 'table' param required for create_table"
        if not schema or not isinstance(schema, dict):
            return "[ERROR] database_tool: 'schema' param required for create_table (dict of col_name: col_type)"
        return _create_table(database, table, schema, pg)
    if action == "insert":
        table = str(params.get("table", "")).strip()
        data  = params.get("data")
        if not table:
            return "[ERROR] database_tool: 'table' param required for insert"
        if data is None:
            return "[ERROR] database_tool: 'data' param required for insert (dict or list of dicts)"
        return _insert(database, table, data, pg)
    if action == "query":
        sql = str(params.get("query", "")).strip()
        if not sql:
            return "[ERROR] database_tool: 'query' param required for query action"
        return _query(database, sql, pg)
    if action in ("update", "delete"):
        sql = str(params.get("sql", "")).strip()
        if not sql:
            return f"[ERROR] database_tool: 'sql' param required for {action}"
        return _execute_write(database, sql, action, pg)
    if action == "drop_table":
        table = str(params.get("table", "")).strip()
        if not table:
            return "[ERROR] database_tool: 'table' param required for drop_table"
        return _drop_table(database, table, pg)

    return (
        f"[ERROR] database_tool: unknown action '{action}'. "
        "Options: create_db, create_table, insert, query, update, delete, "
        "list_dbs, list_tables, describe_table, drop_table"
    )


# ─────────────────────────────────────────────
# ACTIONS
# ─────────────────────────────────────────────

def _test_connection(pg: bool) -> str:
    parts = []
    if pg:
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=POSTGRES_HOST, port=POSTGRES_PORT,
                user=POSTGRES_USER, password=POSTGRES_PASSWORD or None,
                database=POSTGRES_DB, connect_timeout=5,
            )
            conn.close()
            parts.append(f"PostgreSQL: connected ({POSTGRES_HOST}:{POSTGRES_PORT}, db={POSTGRES_DB})")
        except Exception as e:
            parts.append(f"PostgreSQL: FAILED — {e}")
    else:
        parts.append(f"PostgreSQL: unreachable at {POSTGRES_HOST}:{POSTGRES_PORT}")

    try:
        from pathlib import Path
        sqlite_ok = Path(SQLITE_DIR).exists()
        parts.append(f"SQLite: {'ready' if sqlite_ok else 'directory missing'} ({SQLITE_DIR})")
    except Exception as e:
        parts.append(f"SQLite: error — {e}")

    status = "SUCCESS" if pg else "PARTIAL"
    return f"[{status}] test_connection — " + " | ".join(parts)


def _create_db(database: str, pg: bool) -> str:
    if pg:
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=POSTGRES_HOST, port=POSTGRES_PORT,
                user=POSTGRES_USER, password=POSTGRES_PASSWORD or None,
                database="postgres", connect_timeout=5,
            )
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,))
                if cur.fetchone():
                    conn.close()
                    return f"[SUCCESS] Database '{database}' already exists (PostgreSQL)."
                cur.execute(f'CREATE DATABASE "{database}"')
            conn.close()
            _write_last_op("create_db", database, "")
            return f"[SUCCESS] Database '{database}' created (PostgreSQL)."
        except Exception as e:
            return f"[ERROR] database_tool: create_db (PostgreSQL): {e}"
    else:
        try:
            path = _sqlite_path(database)
            conn = sqlite3.connect(str(path))
            conn.close()
            _write_last_op("create_db", database, "")
            return f"[SUCCESS] Database '{database}' created (SQLite at {path})."
        except Exception as e:
            return f"[ERROR] database_tool: create_db (SQLite): {e}"


def _list_dbs(pg: bool) -> str:
    parts = []
    if pg:
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=POSTGRES_HOST, port=POSTGRES_PORT,
                user=POSTGRES_USER, password=POSTGRES_PASSWORD or None,
                database="postgres", connect_timeout=5,
            )
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname"
                )
                dbs = [row[0] for row in cur.fetchall()]
            conn.close()
            parts.append(f"PostgreSQL: {', '.join(dbs) or '(none)'}")
        except Exception as e:
            parts.append(f"PostgreSQL: error — {e}")
    else:
        parts.append("PostgreSQL: unavailable (SQLite fallback active)")

    try:
        SQLITE_DIR_PATH.mkdir(parents=True, exist_ok=True)
        sqlite_dbs = [p.stem for p in sorted(SQLITE_DIR_PATH.glob("*.db"))]
        parts.append(f"SQLite ({SQLITE_DIR_PATH}): {', '.join(sqlite_dbs) or '(none)'}")
    except Exception as e:
        parts.append(f"SQLite: error — {e}")

    return "[SUCCESS] Databases — " + " | ".join(parts)


def _list_tables(database: str, pg: bool) -> str:
    if pg:
        try:
            conn = _pg_connect(database)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' ORDER BY tablename"
                )
                tables = [row[0] for row in cur.fetchall()]
            conn.close()
            return f"[SUCCESS] Tables in '{database}' (PostgreSQL): {', '.join(tables) or '(empty)'}"
        except Exception as e:
            return f"[ERROR] database_tool: list_tables '{database}' (PostgreSQL): {e}"
    else:
        try:
            path = _sqlite_path(database)
            conn = sqlite3.connect(str(path))
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = [row[0] for row in cur.fetchall()]
            conn.close()
            return f"[SUCCESS] Tables in '{database}' (SQLite): {', '.join(tables) or '(empty)'}"
        except Exception as e:
            return f"[ERROR] database_tool: list_tables '{database}' (SQLite): {e}"


def _describe_table(database: str, table: str, pg: bool) -> str:
    if pg:
        try:
            conn = _pg_connect(database)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT column_name, data_type, is_nullable, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = %s "
                    "ORDER BY ordinal_position",
                    (table,),
                )
                cols = cur.fetchall()
            conn.close()
            if not cols:
                return f"[ERROR] database_tool: table '{table}' not found in '{database}' (PostgreSQL)"
            col_lines = [
                f"  {c[0]} {c[1]} {'NULL' if c[2] == 'YES' else 'NOT NULL'}"
                + (f" DEFAULT {c[3]}" if c[3] else "")
                for c in cols
            ]
            return (
                f"[SUCCESS] '{database}.{table}' (PostgreSQL) — {len(cols)} columns:\n"
                + "\n".join(col_lines)
            )
        except Exception as e:
            return f"[ERROR] database_tool: describe_table '{table}' (PostgreSQL): {e}"
    else:
        try:
            path = _sqlite_path(database)
            conn = sqlite3.connect(str(path))
            cur = conn.execute(f"PRAGMA table_info('{table}')")
            cols = cur.fetchall()
            conn.close()
            if not cols:
                return f"[ERROR] database_tool: table '{table}' not found in '{database}' (SQLite)"
            col_lines = [
                f"  {c[1]} {c[2]} {'NOT NULL' if c[3] else 'NULL'}"
                + (f" DEFAULT {c[4]}" if c[4] is not None else "")
                for c in cols
            ]
            return (
                f"[SUCCESS] '{database}.{table}' (SQLite) — {len(cols)} columns:\n"
                + "\n".join(col_lines)
            )
        except Exception as e:
            return f"[ERROR] database_tool: describe_table '{table}' (SQLite): {e}"


def _create_table(database: str, table: str, schema: dict, pg: bool) -> str:
    col_defs = ", ".join(f'"{k}" {v}' for k, v in schema.items())
    sql = f'CREATE TABLE IF NOT EXISTS "{table}" ({col_defs})'
    if pg:
        try:
            _ensure_pg_db(database)
            conn = _pg_connect(database)
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
            conn.close()
            _write_last_op("create_table", database, table, sql=sql)
            return f"[SUCCESS] Table '{table}' created in '{database}' (PostgreSQL)."
        except Exception as e:
            return f"[ERROR] database_tool: create_table '{table}' (PostgreSQL): {e}"
    else:
        try:
            path = _sqlite_path(database)
            conn = sqlite3.connect(str(path))
            conn.execute(sql)
            conn.commit()
            conn.close()
            _write_last_op("create_table", database, table, sql=sql)
            return f"[SUCCESS] Table '{table}' created in '{database}' (SQLite at {path})."
        except Exception as e:
            return f"[ERROR] database_tool: create_table '{table}' (SQLite): {e}"


def _insert(database: str, table: str, data, pg: bool) -> str:
    rows = data if isinstance(data, list) else [data]
    if not rows:
        return "[ERROR] database_tool: insert data is empty"
    if not isinstance(rows[0], dict):
        return "[ERROR] database_tool: insert 'data' must be a dict or list of dicts"

    cols = list(rows[0].keys())
    if not cols:
        return "[ERROR] database_tool: insert data dict has no keys"

    values = [tuple(row.get(c) for c in cols) for row in rows]

    if pg:
        try:
            _ensure_pg_db(database)
            col_str      = ", ".join(f'"{c}"' for c in cols)
            placeholders = ", ".join(["%s"] * len(cols))
            sql = f'INSERT INTO "{table}" ({col_str}) VALUES ({placeholders})'
            conn = _pg_connect(database)
            with conn.cursor() as cur:
                cur.executemany(sql, values)
            conn.commit()
            conn.close()
            _write_last_op("insert", database, table, row_count=len(rows))
            return f"[SUCCESS] Inserted {len(rows)} row(s) into '{database}.{table}' (PostgreSQL)."
        except Exception as e:
            return f"[ERROR] database_tool: insert '{table}' (PostgreSQL): {e}"
    else:
        try:
            col_str      = ", ".join(f'"{c}"' for c in cols)
            placeholders = ", ".join(["?"] * len(cols))
            sql = f'INSERT INTO "{table}" ({col_str}) VALUES ({placeholders})'
            path = _sqlite_path(database)
            conn = sqlite3.connect(str(path))
            conn.executemany(sql, values)
            conn.commit()
            conn.close()
            _write_last_op("insert", database, table, row_count=len(rows))
            return f"[SUCCESS] Inserted {len(rows)} row(s) into '{database}.{table}' (SQLite)."
        except Exception as e:
            return f"[ERROR] database_tool: insert '{table}' (SQLite): {e}"


def _query(database: str, sql: str, pg: bool) -> str:
    if not sql.strip().upper().startswith("SELECT"):
        return (
            "[ERROR] database_tool: 'query' action only allows SELECT. "
            "Use 'update' or 'delete' action for write operations."
        )
    if pg:
        try:
            conn = _pg_connect(database)
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description] if cur.description else []
            conn.close()
            _write_last_op("query", database, "", row_count=len(rows), sql=sql)
            return _format_query_result(rows, cols, "PostgreSQL")
        except Exception as e:
            return f"[ERROR] database_tool: query '{database}' (PostgreSQL): {e}"
    else:
        try:
            path = _sqlite_path(database)
            conn = sqlite3.connect(str(path))
            cur  = conn.execute(sql)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
            conn.close()
            _write_last_op("query", database, "", row_count=len(rows), sql=sql)
            return _format_query_result(rows, cols, "SQLite")
        except Exception as e:
            return f"[ERROR] database_tool: query '{database}' (SQLite): {e}"


def _format_query_result(rows: list, cols: list, backend: str) -> str:
    count = len(rows)
    if count == 0:
        return f"[SUCCESS] query returned 0 rows — columns: {cols}"
    sample = rows[:5]
    sample_dicts = []
    for row in sample:
        d = {}
        for k, v in zip(cols, row):
            d[k] = v if isinstance(v, (str, int, float, bool, type(None))) else str(v)
        sample_dicts.append(d)
    return (
        f"[SUCCESS] query returned {count:,} row(s) — columns: {cols} ({backend})\n"
        f"Sample (first {min(5, count)}): {json.dumps(sample_dicts, ensure_ascii=False, default=str)}"
    )


def _execute_write(database: str, sql: str, action: str, pg: bool) -> str:
    if pg:
        try:
            conn = _pg_connect(database)
            with conn.cursor() as cur:
                cur.execute(sql)
                affected = cur.rowcount
            conn.commit()
            conn.close()
            _write_last_op(action, database, "", row_count=affected, sql=sql)
            return (
                f"[SUCCESS] {action} executed on '{database}' — "
                f"{affected} row(s) affected (PostgreSQL)."
            )
        except Exception as e:
            return f"[ERROR] database_tool: {action} '{database}' (PostgreSQL): {e}"
    else:
        try:
            path = _sqlite_path(database)
            conn = sqlite3.connect(str(path))
            cur  = conn.execute(sql)
            affected = cur.rowcount
            conn.commit()
            conn.close()
            _write_last_op(action, database, "", row_count=affected, sql=sql)
            return (
                f"[SUCCESS] {action} executed on '{database}' — "
                f"{affected} row(s) affected (SQLite)."
            )
        except Exception as e:
            return f"[ERROR] database_tool: {action} '{database}' (SQLite): {e}"


def _drop_table(database: str, table: str, pg: bool) -> str:
    sql = f'DROP TABLE IF EXISTS "{table}"'
    if pg:
        try:
            conn = _pg_connect(database)
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
            conn.close()
            _write_last_op("drop_table", database, table, sql=sql)
            return f"[SUCCESS] Table '{table}' dropped from '{database}' (PostgreSQL)."
        except Exception as e:
            return f"[ERROR] database_tool: drop_table '{table}' (PostgreSQL): {e}"
    else:
        try:
            path = _sqlite_path(database)
            conn = sqlite3.connect(str(path))
            conn.execute(sql)
            conn.commit()
            conn.close()
            _write_last_op("drop_table", database, table)
            return f"[SUCCESS] Table '{table}' dropped from '{database}' (SQLite)."
        except Exception as e:
            return f"[ERROR] database_tool: drop_table '{table}' (SQLite): {e}"
