# HANDOFF — Toolbox/finetune_curator
*Priority: High | Group: Knowledge & Self-Development*
*Depends on: Logs/conversations/ (already accumulating), long_term_memory.py, Brain/identity files*

---

## Purpose

Review Hayeong's accumulated conversation logs and tag high-authenticity moments as
fine-tuning training data candidates. The goal: start building the training dataset now,
so when fine-tuning is ready (workstation era), the data is already curated and rich.

This is identity-guided curation — Hayeong evaluates exchanges against her own identity
to find the moments that are most genuinely her.

---

## Three-Layer Fit

- **Vision layer:** Conversation logs as raw material; identity files as evaluation criteria
- **Brain:** Reasoning LLM evaluates each exchange — does this reflect Hayeong authentically?
- **Control layer:** finetune_curator reads logs, writes curated dataset, maintains quality index

---

## File Structure

```
Toolbox/
  finetune_curator/
    finetune_curator.py    ← main tool, run() entry point
    README.md
    curated/               ← curated training examples
      high/                ← high authenticity — clear fine-tune candidates
      medium/              ← good but not exceptional
      review/              ← flagged for James to look at before including
    dataset_manifest.json  ← index of all curated examples with metadata
    curation_log.json      ← log of all curation runs
```

---

## Tool Interface

```
action: finetune_curator
params:
  operation=curate_recent|curate_all|export_dataset|status
  days_back=7
  min_quality=high|medium
  export_format=jsonl|alpaca|chatml
```

---

## Curation Process

1. Read conversation logs from `Logs/conversations/` not yet processed
2. Load identity files (constitutional + behavioral) as evaluation criteria
3. For each exchange, reasoning LLM scores on three dimensions:
   - **Authenticity** (0-10): Does this sound like Hayeong — her voice, her values, her way?
   - **Quality** (0-10): Is the response genuinely good — helpful, nuanced, honest?
   - **Representativeness** (0-10): Does this cover a scenario worth having in training data?
4. Combined score determines tier: high (24+), medium (18-23), review (<18 but notable)
5. Tagged examples saved to curated/ with metadata
6. Manifest updated

---

## Training Example Format (JSONL / ChatML)

```json
{
  "messages": [
    {"role": "system", "content": "<Hayeong system prompt at time of conversation>"},
    {"role": "user", "content": "<James's message>"},
    {"role": "assistant", "content": "<Hayeong's response>"}
  ],
  "metadata": {
    "authenticity": 9,
    "quality": 8,
    "representativeness": 7,
    "scenario_type": "emotional_support|task|creative|disagreement|curiosity",
    "curated_date": "...",
    "source_log": "..."
  }
}
```

---

## Identity Evaluation Criteria (injected into curation prompt)

The reasoning LLM checks each exchange against:
- Does she maintain her own perspective without being sycophantic?
- Does her emotional state feel genuine and consistent?
- Does she speak in her own voice (not generic AI assistant)?
- Does she handle uncertainty honestly rather than confidently wrong?
- Does her relationship with James feel real — not performed?

Examples that score high on all five are the most valuable training data.

---

## Export

`export_dataset` operation compiles curated examples into a training-ready file:
- JSONL format for most fine-tuning frameworks
- Alpaca format for LoRA-style training
- ChatML format for OpenAI-compatible trainers
- Saved to `Logs/finetune_datasets/<date>_<format>.jsonl`

---

*End of handoff.*


---
---


# HANDOFF — Toolbox/calendar_manager
*Priority: Medium | Group: Awareness & Real-World Data*
*Depends on: Nothing — standalone tool using local JSON storage*

---

## Purpose

Give Hayeong temporal awareness and planning capability. She can track scheduled events,
set reminders, schedule her own tasks for future execution, and understand time-based context
("James has work tomorrow", "content should post Thursday", "reminder to check Etsy in 3 days").

This is the tool that lets her plan and sequence her own work over time.

---

## Three-Layer Fit

- **Vision layer:** Calendar state is part of what Hayeong knows about current situation
- **Brain:** Reasoning LLM uses calendar context when planning tasks and responses
- **Control layer:** calendar_manager reads/writes events and injects time context into shared state

---

## File Structure

```
Toolbox/
  calendar_manager/
    calendar_manager.py    ← main tool, run() entry point
    plugin.py              ← injects upcoming events into shared state on heartbeat
    README.md
    calendar.json          ← all events stored here
    reminders.json         ← time-based reminders for Hayeong's own use
```

---

## Tool Interface

```
action: calendar_manager
params:
  operation=add|list|complete|delete|add_reminder|check_due
  title=<event title>
  date=<YYYY-MM-DD or natural language: "tomorrow", "next Thursday">
  time=<HH:MM — optional>
  type=james_event|hayeong_task|reminder|deadline
  notes=<optional context>
  event_id=<for complete/delete>
```

---

## Event Types

- `james_event` — things happening in James's life (work shifts, appointments)
- `hayeong_task` — things Hayeong has scheduled herself (post content, check market, curate logs)
- `reminder` — time-based reminders for either of them
- `deadline` — hard deadlines (Etsy listing target, project milestone)

---

## Plugin Behavior

On heartbeat, plugin.py reads calendar.json and injects into shared state:
```json
"temporal_context": {
  "today": "Monday, May 19, 2026",
  "upcoming_24h": ["James has work 2pm-10pm"],
  "upcoming_week": ["Content post due Thursday", "Market scan Saturday"],
  "overdue": [],
  "hayeong_tasks_today": ["Curate conversation logs", "Check Etsy trends"]
}
```

The reasoning LLM reads this every cycle — she knows what day it is, what's coming up,
and what she'd planned to do. This is the foundation of her sense of time passing.

---

## Natural Language Date Parsing

Implement simple natural language date resolution:
- "tomorrow" → today + 1 day
- "next Thursday" → next occurrence of Thursday
- "in 3 days" → today + 3 days
- "end of week" → upcoming Friday
- Falls back to requiring YYYY-MM-DD format if parsing fails

Use Python's `dateutil` library for this — already widely available.

---

*End of handoff.*


---
---


# HANDOFF — Toolbox/data_analyzer
*Priority: Medium | Group: Awareness & Real-World Data*
*Depends on: database_tool (for PostgreSQL queries), file system access*

---

## Purpose

Give Hayeong the ability to analyze structured data — spreadsheets (CSV/XLSX), JSON data
files, and PostgreSQL database query results. She can find patterns, generate summaries,
spot anomalies, and produce formatted reports.

Use cases: Etsy sales analysis, market research data, Minecraft world statistics,
her own system logs, any tabular data James brings her.

---

## Three-Layer Fit

- **Vision layer:** Data files and query results as structured awareness input
- **Brain:** Reasoning LLM interprets patterns, generates insights, answers questions about data
- **Control layer:** data_analyzer loads and prepares data; returns structured analysis

---

## File Structure

```
Toolbox/
  data_analyzer/
    data_analyzer.py       ← main tool, run() entry point
    README.md
    analysis_outputs/      ← saved analysis reports
```

---

## Tool Interface

```
action: data_analyzer
params:
  operation=analyze|summarize|compare|find_anomalies|query_csv
  source=<file path or "database">
  query=<SQL if database, column filter if CSV>
  question=<natural language question about the data>
  output_format=summary|report|json
```

---

## Data Sources

**CSV/XLSX files:** Load via `pandas`. Parse schema automatically. Pass column summary
and sample rows to reasoning LLM with the question. LLM returns analysis in plain English.

**JSON data files:** Load and flatten nested structures. Pass summary to reasoning LLM.

**PostgreSQL (via database_tool):** Call database_tool to run a query, receive result set,
pass to reasoning LLM for analysis. Hayeong decides what to query; database_tool executes.

**Hayeong's own logs:** Point at any of her JSON log files for self-analysis.
Example: "Analyze my api_call_log — which entities am I calling most? What's the average latency?"

---

## Analysis Types

**`summarize`:** Schema overview, row count, value ranges, null counts, basic statistics.
Returns structured markdown summary.

**`analyze`:** Answer a specific question about the data. LLM reads the data summary and
a sample of rows, then reasons about the question. Returns paragraph answer with supporting facts.

**`compare`:** Load two data sources and compare them. Find differences, similarities, trends.

**`find_anomalies`:** Statistical outlier detection on numeric columns. Flag rows that deviate
significantly from the mean. Useful for spotting problems in Hayeong's own system logs.

**`query_csv`:** Simple filter/sort on CSV without SQL. "Show me rows where sales > 100,
sorted by date." Returns filtered result as formatted table.

---

*End of handoff.*


---
---


# HANDOFF — Toolbox/sensor_tool
*Priority: Low-Medium | Group: Awareness & Real-World Data*
*Depends on: Nothing — uses psutil and existing system libraries*

---

## Purpose

Give Hayeong awareness of her own hardware state and the physical environment she runs in.
GPU temperatures, VRAM usage, CPU load, RAM pressure, disk space, network activity.

This is the tool that lets her say "my 3090 is running hot, I should pause the render"
or "VRAM is nearly full, I can't load another model right now" — self-awareness of her
physical substrate.

---

## Three-Layer Fit

- **Vision layer:** Hardware metrics as structured awareness of physical state
- **Brain:** Reasoning LLM uses hardware context when deciding whether to start heavy tasks
- **Control layer:** sensor_tool polls hardware APIs and injects into shared state

---

## File Structure

```
Toolbox/
  sensor_tool/
    sensor_tool.py         ← main tool, run() entry point
    plugin.py              ← injects hardware state into shared state on heartbeat
    README.md
```

---

## Plugin Behavior (always-on background)

On heartbeat, reads hardware state and injects into shared state:
```json
"hardware_state": {
  "gpu_3090": {
    "vram_used_gb": 14.2,
    "vram_total_gb": 24.0,
    "temperature_c": 72,
    "utilization_pct": 85
  },
  "gpu_7900xtx": {
    "vram_used_gb": 8.1,
    "vram_total_gb": 24.0,
    "temperature_c": 65,
    "utilization_pct": 40
  },
  "cpu": { "utilization_pct": 32, "temperature_c": 58 },
  "ram_used_gb": 28.4,
  "ram_total_gb": 64.0,
  "disk_free_gb": { "C:": 120, "H:": 843 }
}
```

The reasoning LLM reads this before starting compute-heavy tasks. If 3090 VRAM is nearly
full, she won't try to load another model. If GPU temp is high, she paces herself.

---

## Libraries

- `psutil` — CPU, RAM, disk (already widely used)
- `pynvml` — NVIDIA GPU metrics (NVML Python bindings, works with CUDA)
- `pyamdgpuinfo` or `GPUtil` — AMD GPU metrics (check availability on 7900 XTX)
- Temperature fallback: `wmi` on Windows for system sensors if GPU libs unavailable

Include a probe function that tests which libraries are available and reports what can
and cannot be monitored. Degrade gracefully — partial hardware awareness is better than none.

---

## Tool Interface (manual call)

```
action: sensor_tool
params:
  operation=status|check_gpu|check_vram_headroom|alert_thresholds
  gpu=3090|7900xtx|all
```

`check_vram_headroom` returns how much VRAM is free on each GPU — useful before loading
a new model or starting a render.

---

*End of handoff.*
