# Toolbox/script

General-purpose Python script execution. Runs a specified script and returns
its stdout output as the result string.

## Calling This Tool

    action: script
    params: script=relative/path/to/script.py

## Notes

- Script path is relative to project root
- stdout is returned as the result string
- Non-zero exit code raises an error (captured by the task loop)
- Timeout: 60 seconds

## Files

- `script_tool.py` — `run(description, params)` entry point
