# Task Dispatch — What I Know

## params vs description — Critical Distinction

**description** = human-readable intent. What I am trying to do.
Can be prose. Will be summarised and may be truncated. Not for precise data.

**params** = precise data the tool needs to execute. Never truncated.
File paths, operation types, specific values — always go in params.

### Why this matters
If I put a file path in description and the description gets truncated,
the tool receives a broken path and reports file not found — even though
I knew the correct file. The file name was right. The channel was wrong.

### Rule
Any time I am assigning a task that involves a file:
- description: "Implement the image2image workflow handoff"
- params: {"handoff_path": "handoff_01_img2img_workflow.md"}

NOT:
- description: "Implement handoff_01_img2img_workflow.md"
- params: {}

The intent lives in description. The file lives in params.

## handoff_reader params
- operation: list | implement | read
- handoff_path: exact filename (e.g. handoff_01_img2img_workflow.md)
- dry_run: true | false

## file_manager params
- operation: read | write | append | list | exists | delete | mkdir
- path: relative path from project root
- content: text to write (write/append operations)
- pattern: glob pattern (list operation, default *)

## Key Directory Paths

| What                        | Path                          |
|-----------------------------|-------------------------------|
| Handoff files for me        | logs/handoffs/                |
| Handoff files for James     | logs/handoffs/                |
| Conversation logs           | logs/conversations/           |
| Session logs                | logs/sessions/                |
| My output files             | logs/outputs/                 |
| Roadmap / design docs       | logs/notes/roadmap/           |
| Toolbox tools               | Toolbox/<tool_name>/          |
| Brain modules               | Brain/                        |
| Memory store                | Memory/                       |

All handoff files that James drops for me live in `logs/handoffs/`.
When listing available handoffs, list that directory.
