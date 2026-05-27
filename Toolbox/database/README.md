# Toolbox/database

Two tools for working with structured data.

## database_tool — Control Layer

Creates, queries, and manages PostgreSQL databases (with SQLite fallback).
All databases stored on H: drive.

- **Primary:** PostgreSQL at localhost:5432
- **Fallback:** SQLite files at `H:/Databases/sqlite/`

Hayeong's own database: `"hayeong"` — auto-created on first use.

### Actions

| Action | Params | Description |
|--------|--------|-------------|
| `create_db` | `database` | Create a new database |
| `create_table` | `database`, `table`, `schema` | Create table with column definitions |
| `insert` | `database`, `table`, `data` | Insert one row (dict) or many rows (list of dicts) |
| `query` | `database`, `query` | SELECT query — returns formatted summary |
| `update` | `database`, `sql` | UPDATE statement |
| `delete` | `database`, `sql` | DELETE statement |
| `list_dbs` | — | List all accessible databases |
| `list_tables` | `database` | List tables in a database |
| `describe_table` | `database`, `table` | Show column definitions |
| `drop_table` | `database`, `table` | Drop a table |

## data_reader — Vision Layer

Reads and summarizes CSV, Excel, JSON files and database tables.
Returns structured summaries the brain can reason about.
Never dumps raw rows into context — always summarizes to meaning.

### Actions

| Action | Params | Description |
|--------|--------|-------------|
| `read_csv` | `path` | Read a CSV and return shape + sample |
| `read_excel` | `path`, `sheet` | Read Excel sheet |
| `read_json` | `path` | Read a JSON file |
| `summarize` | `path` OR `database`+`table` | Statistical summary of numeric columns |
| `analyze` | `path` OR `database`+`table` | Pattern detection (nulls, cardinality, date ranges, duplicates) |
| `sample` | `path` OR `database`+`table`, `rows` | Return N raw rows |

## Storage Locations

```
H:/Databases/postgres/data/   ← PostgreSQL data files (configured in Postgres)
H:/Databases/sqlite/          ← SQLite fallback databases
H:/Databases/last_op.json     ← Last operation written by database_tool (read by plugin)
```

## PostgreSQL Setup

If Postgres is not yet installed or not pointing at H: drive, initialize a new cluster:

```
# Admin terminal — adjust version number to match installed version:
"C:\Program Files\PostgreSQL\16\bin\initdb.exe" -D "H:\Databases\postgres\data" -U postgres

# Start the cluster:
"C:\Program Files\PostgreSQL\16\bin\pg_ctl.exe" -D "H:\Databases\postgres\data" start

# Register as a Windows service:
"C:\Program Files\PostgreSQL\16\bin\pg_ctl.exe" register -N "HayeongPostgres" -D "H:\Databases\postgres\data"
```

Python dependencies:
```
pip install psycopg2-binary pandas openpyxl xlrd
```

## When to Use Which

- Working with Hayeong's own persistent records → `database` (Postgres)
- Quick read of an Excel or CSV → `data_reader`
- Understanding an unfamiliar dataset → `data_reader` (`analyze` action)
- Storing project tracking data → `database` (`create_table` + `insert`)
- Checking what databases exist → `database` (`list_dbs`)
