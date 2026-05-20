# HANDOFF — Hello World Test
*Purpose: Verify handoff_reader, task loop, and self-verification are all working*

---

## What To Do

Create one small Python file and one small text file.
That's all. This is a test of the pipeline, not a real tool.

---

FILE: Toolbox/hello_test/hello_test.py
```python
"""
Toolbox/hello_test/hello_test.py

Test tool. Confirms the full pipeline is working:
- handoff_reader implemented this file
- task loop executed it
- self_check verified the result

Returns a status string with timestamp.
"""

from datetime import datetime

def run(description: str, params: dict) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"[hello_test] Pipeline verified at {timestamp}. Hayeong is working correctly."
```

FILE: Toolbox/hello_test/STATUS.txt
```
Hello from Hayeong.
This file confirms handoff_reader wrote to disk successfully.
If you can read this, the pipeline is working.
```

FILE: Toolbox/hello_test/__init__.py
```python
# Toolbox/hello_test/__init__.py
```
