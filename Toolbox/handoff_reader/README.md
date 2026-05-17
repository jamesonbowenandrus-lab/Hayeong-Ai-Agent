# Toolbox/handoff_reader

Hayeong's self-implementation tool. Reads handoff notes and builds the tools
they describe — without Claude Code involvement.

## What This Does

Takes a handoff .md file, extracts the file specs from code blocks,
and calls the dev tool to create each file. Then verifies the result.

## Calling This Tool

    action: handoff_reader
    params: operation=list

    action: handoff_reader
    params: operation=read, handoff_path=01_api_caller.md

    action: handoff_reader
    params: operation=implement, handoff_path=01_api_caller.md, dry_run=true

    action: handoff_reader
    params: operation=implement, handoff_path=01_api_caller.md

## Operations

- **list** — show all handoff files available
- **read** — read and summarize a handoff file
- **implement** — execute the handoff (create all files it describes)
- **status** — show recent implementation history

## Dry Run

Always run with `dry_run=true` first. This shows what would be created
without touching any files.

## Handoff File Format

Use explicit FILE: markers for reliable extraction:

    FILE: Toolbox/my_tool/my_tool.py
    ```python
    # code here
    ```

    FILE: Toolbox/my_tool/README.md
    ```
    # docs here
    ```

The FILE: marker must be on its own line, immediately before the opening
code fence (no blank lines between them).

**Fallback format** — path on the line immediately before the fence also works:

    `Toolbox/my_tool/my_tool.py`
    ```python
    # code here
    ```

Only paths under `Toolbox/`, `Brain/`, `Memory/`, `Logs/`, or `Dashboard/`
are extracted. Extensions must be `.py`, `.json`, `.md`, `.txt`, or `.bat`.
Paths with spaces, pipes, or brackets are rejected as interface examples.

## Limitations

The tool extracts code blocks from handoff notes. Handoff notes must use
FILE: markers or path-before-fence format. If extraction fails, the tool
will say so — manual implementation needed.
