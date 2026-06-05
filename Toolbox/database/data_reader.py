"""
toolbox/database/data_reader.py

Hayeong's data vision tool.
Reads and summarizes CSV, Excel, JSON files and database tables
into structured summaries the brain can reason about.

Never dumps raw rows into context — always summarizes to meaning.

Called via registry:
    module:   toolbox.database.data_reader
    function: run

Actions:
    read_csv, read_excel, read_json, summarize, analyze, sample

Returns:
    str — "[SUCCESS] summary" | "[ERROR] ..." | "[PARTIAL] ..."
    Never raises. All errors are returned as strings.
"""

import json
import sqlite3
from pathlib import Path

from brain.config import (
    POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB,
    SQLITE_DIR,
)

SQLITE_DIR_PATH = Path(SQLITE_DIR)


def run(description: str, params: dict) -> str:
    try:
        return _dispatch(description, params)
    except Exception as e:
        return f"[ERROR] data_reader: {e}"


# ─────────────────────────────────────────────
# DISPATCH
# ─────────────────────────────────────────────

def _dispatch(description: str, params: dict) -> str:
    action = str(params.get("action", "")).lower().strip()
    if not action:
        return (
            "[ERROR] data_reader: 'action' param required. "
            "Options: read_csv, read_excel, read_json, summarize, analyze, sample"
        )

    dispatch = {
        "read_csv":   _read_csv,
        "read_excel": _read_excel,
        "read_json":  _read_json,
        "summarize":  _summarize,
        "analyze":    _analyze,
        "sample":     _sample,
    }

    fn = dispatch.get(action)
    if not fn:
        return (
            f"[ERROR] data_reader: unknown action '{action}'. "
            f"Options: {', '.join(dispatch)}"
        )
    return fn(params)


# ─────────────────────────────────────────────
# PANDAS IMPORT HELPER
# ─────────────────────────────────────────────

def _import_pandas():
    try:
        import pandas as pd
        return pd, None
    except ImportError:
        return None, "[ERROR] data_reader: pandas not installed. Run: pip install pandas openpyxl xlrd"


# ─────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────

def _load_df(params: dict):
    """
    Load a DataFrame from file path, database table, or SQL query.
    Returns (df, None) on success or (None, error_str) on failure.
    """
    pd, err = _import_pandas()
    if err:
        return None, err

    path     = str(params.get("path", "")).strip()
    table    = str(params.get("table", "")).strip()
    database = str(params.get("database", POSTGRES_DB)).strip() or POSTGRES_DB
    query    = str(params.get("query", "")).strip()

    if path:
        file = Path(path)
        if not file.exists():
            return None, f"[ERROR] data_reader: file not found: {file}"
        ext = file.suffix.lower()
        try:
            if ext == ".csv":
                df = pd.read_csv(str(file))
            elif ext in (".xlsx", ".xls"):
                sheet = params.get("sheet", 0)
                df = pd.read_excel(str(file), sheet_name=sheet)
            elif ext == ".json":
                df = pd.read_json(str(file))
            else:
                return None, f"[ERROR] data_reader: unsupported file type '{ext}'. Supported: csv, xlsx, xls, json"
            return df, None
        except Exception as e:
            return None, f"[ERROR] data_reader: failed to read '{file}': {e}"

    if table or query:
        pg = _check_pg()
        sql = query if query else f'SELECT * FROM "{table}"'
        if pg:
            try:
                conn = _pg_connect(database)
                df = pd.read_sql(sql, conn)
                conn.close()
                return df, None
            except Exception as e:
                return None, f"[ERROR] data_reader: DB read (PostgreSQL) failed: {e}"
        else:
            try:
                path_db = SQLITE_DIR_PATH / f"{database}.db"
                conn = sqlite3.connect(str(path_db))
                df = pd.read_sql(sql, conn)
                conn.close()
                return df, None
            except Exception as e:
                return None, f"[ERROR] data_reader: DB read (SQLite) failed: {e}"

    return None, (
        "[ERROR] data_reader: provide 'path' (file) or 'table'/'query' + 'database' (DB) params"
    )


# ─────────────────────────────────────────────
# CONNECTION HELPERS (local — no import from database_tool)
# ─────────────────────────────────────────────

def _check_pg() -> bool:
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


def _pg_connect(database: str):
    import psycopg2
    return psycopg2.connect(
        host=POSTGRES_HOST, port=POSTGRES_PORT,
        user=POSTGRES_USER, password=POSTGRES_PASSWORD or None,
        database=database, connect_timeout=5,
    )


# ─────────────────────────────────────────────
# SUMMARY BUILDER
# ─────────────────────────────────────────────

def _build_summary(df, source_label: str, n_sample: int = 5) -> str:
    pd, _ = _import_pandas()

    rows, cols = df.shape
    col_names  = list(df.columns)

    # Types
    type_map = {}
    for col in df.columns:
        dtype = str(df[col].dtype)
        if "int" in dtype:
            type_map[col] = "int"
        elif "float" in dtype:
            type_map[col] = "float"
        elif "datetime" in dtype or "date" in dtype:
            type_map[col] = "datetime"
        elif "bool" in dtype:
            type_map[col] = "bool"
        else:
            # Try to detect datetime-like object columns
            if df[col].dtype == object:
                sample_vals = df[col].dropna().head(3).tolist()
                if sample_vals and isinstance(sample_vals[0], str):
                    type_map[col] = "str"
                else:
                    type_map[col] = "mixed"
            else:
                type_map[col] = dtype

    type_str = ", ".join(f"{c}={t}" for c, t in type_map.items())

    # Null counts
    null_info = []
    for col in df.columns:
        null_count = int(df[col].isnull().sum())
        if null_count > 0:
            pct = null_count / rows * 100
            null_info.append(f"{col} has {null_count} nulls ({pct:.1f}%)")

    # Sample rows
    sample_rows = df.head(n_sample).to_dict(orient="records")
    # Ensure JSON-serializable
    for row in sample_rows:
        for k, v in row.items():
            if not isinstance(v, (str, int, float, bool, type(None))):
                row[k] = str(v)

    lines = [
        f"[SUCCESS] {source_label} — {rows:,} rows × {len(cols)} columns",
        f"Columns: {col_names}",
        f"Types: {type_str}",
    ]
    if null_info:
        lines.append("Nulls: " + "; ".join(null_info))
    else:
        lines.append("Nulls: none")
    lines.append(f"Sample ({min(n_sample, rows)} rows): {json.dumps(sample_rows, ensure_ascii=False, default=str)}")

    return "\n".join(lines)


# ─────────────────────────────────────────────
# ACTIONS
# ─────────────────────────────────────────────

def _read_csv(params: dict) -> str:
    path = str(params.get("path", "")).strip()
    if not path:
        return "[ERROR] data_reader: 'path' param required for read_csv"
    if not path.lower().endswith(".csv"):
        params = dict(params)
    df, err = _load_df({**params, "path": path})
    if err:
        return err
    return _build_summary(df, f"CSV file '{Path(path).name}'", n_sample=params.get("rows", 5))


def _read_excel(params: dict) -> str:
    path = str(params.get("path", "")).strip()
    if not path:
        return "[ERROR] data_reader: 'path' param required for read_excel"
    df, err = _load_df(params)
    if err:
        return err
    sheet = params.get("sheet", "sheet 0")
    return _build_summary(df, f"Excel '{Path(path).name}' (sheet: {sheet})", n_sample=params.get("rows", 5))


def _read_json(params: dict) -> str:
    path = str(params.get("path", "")).strip()
    if not path:
        return "[ERROR] data_reader: 'path' param required for read_json"
    df, err = _load_df(params)
    if err:
        return err
    return _build_summary(df, f"JSON file '{Path(path).name}'", n_sample=params.get("rows", 5))


def _summarize(params: dict) -> str:
    """Statistical summary of numeric columns."""
    pd, err = _import_pandas()
    if err:
        return err

    df, load_err = _load_df(params)
    if load_err:
        return load_err

    source = params.get("path") or f"{params.get('database','?')}.{params.get('table','?')}"
    rows, ncols = df.shape
    numeric_cols = df.select_dtypes(include="number").columns.tolist()

    if not numeric_cols:
        return (
            f"[SUCCESS] '{source}' — {rows:,} rows × {ncols} columns. "
            "No numeric columns to summarize."
        )

    lines = [
        f"[SUCCESS] Statistical summary — '{source}' ({rows:,} rows)",
    ]
    for col in numeric_cols:
        s    = df[col].dropna()
        if len(s) == 0:
            lines.append(f"  {col}: all null")
            continue
        lines.append(
            f"  {col}: min={s.min():.4g}  max={s.max():.4g}  "
            f"mean={s.mean():.4g}  std={s.std():.4g}  "
            f"p25={s.quantile(0.25):.4g}  p50={s.quantile(0.5):.4g}  "
            f"p75={s.quantile(0.75):.4g}  nulls={int(df[col].isnull().sum())}"
        )
    return "\n".join(lines)


def _analyze(params: dict) -> str:
    """Pattern detection — nulls, cardinality, date ranges, dominant values, duplicates."""
    pd, err = _import_pandas()
    if err:
        return err

    df, load_err = _load_df(params)
    if load_err:
        return load_err

    source = params.get("path") or f"{params.get('database','?')}.{params.get('table','?')}"
    rows, ncols = df.shape
    findings = []

    for col in df.columns:
        s = df[col]
        null_rate = s.isnull().mean()

        if null_rate > 0.10:
            findings.append(
                f"'{col}': {null_rate:.1%} nulls — high missing rate"
            )

        n_unique = s.nunique()

        # Low-cardinality integers — possible FK or category
        if pd.api.types.is_integer_dtype(s) and 1 < n_unique <= 20:
            findings.append(
                f"'{col}': {n_unique} unique integer values — possible FK or categorical column"
            )

        # Date range detection
        is_date_col = (
            pd.api.types.is_datetime64_any_dtype(s)
            or any(kw in col.lower() for kw in ("date", "time", "_at", "created", "updated"))
        )
        if is_date_col:
            try:
                parsed = pd.to_datetime(s, errors="coerce")
                valid  = parsed.dropna()
                if len(valid) > 0:
                    span = (valid.max() - valid.min()).days
                    findings.append(
                        f"'{col}': date range {valid.min().date()} to {valid.max().date()} ({span} days)"
                    )
            except Exception:
                pass

        # Dominant value (>80% same)
        if null_rate < 1.0 and n_unique > 0 and len(s.dropna()) > 0:
            top_rate = s.value_counts(normalize=True).iloc[0]
            if top_rate > 0.80:
                top_val = s.value_counts().index[0]
                findings.append(
                    f"'{col}': dominated by '{top_val}' ({top_rate:.1%}) — likely flag/status column"
                )

    # Duplicate rows
    dup_count = int(df.duplicated().sum())
    if dup_count > 0:
        findings.append(f"{dup_count} fully duplicate rows detected")

    # High-cardinality integer columns — suggest as indexes
    index_candidates = [
        col for col in df.columns
        if pd.api.types.is_integer_dtype(df[col])
        and df[col].nunique() / max(rows, 1) > 0.9
    ]
    if index_candidates:
        findings.append(f"Suggested indexes: {', '.join(index_candidates)}")

    if not findings:
        findings.append("No significant patterns detected.")

    body = "\n  - ".join([""] + findings)
    return (
        f"[SUCCESS] analysis of '{source}' — {rows:,} rows × {ncols} columns:{body}"
    )


def _sample(params: dict) -> str:
    """Return N sample rows from a file or database table."""
    pd, err = _import_pandas()
    if err:
        return err

    n  = int(params.get("rows", 5))
    df, load_err = _load_df(params)
    if load_err:
        return load_err

    source = params.get("path") or f"{params.get('database','?')}.{params.get('table','?')}"
    sample_rows = df.head(n).to_dict(orient="records")
    for row in sample_rows:
        for k, v in row.items():
            if not isinstance(v, (str, int, float, bool, type(None))):
                row[k] = str(v)

    return (
        f"[SUCCESS] sample from '{source}' — {min(n, len(df))} of {len(df):,} rows:\n"
        + json.dumps(sample_rows, ensure_ascii=False, indent=2, default=str)
    )
