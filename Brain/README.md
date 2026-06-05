# Brain

The reasoning and identity layer. The LLM makes all decisions here.
Everything else in the system executes what the Brain decides.

## Core Files

| File | Purpose |
|---|---|
| config.py | Single source of truth for all paths, ports, model names |
| hayeong_core.py | Core Brain orchestration |
| reasoning_loop.py | Background reasoning heartbeat |
| cognitive_tick.py | Idle cognition — fires every 5 min, one private LLM call |
| agenda_manager.py | Read/write interface for inner_agenda.json |
| identity_prompt_builder.py | Assembles identity layers into presence prompt |
| inference_layer.py | LLM call abstraction |
| session_logger.py | SQLite append-only session event log |
| session_compressor.py | Conversation history compression |
| uncertainty_patterns.py | Uncertainty expression patterns |
| health.py | Brain health monitoring |

## Identity Files (private, not tracked)

| File | Layer | Ownership |
|---|---|---|
| identity_constitutional.json | Constitutional | James-authored |
| identity_behavioral.json | Behavioral | Deliberately updated |
| identity_living.json | Living | Hayeong-authored |

## State Files (private, not tracked)

All JSON files in Brain/state/ are runtime state — they change every session
and contain live cognitive state. They are excluded from this repository.
The Python files that manage them (core_manager.py, state_manager.py) are public.

## Design Rule

Brain is tool-agnostic. If a file in Brain contains tool-specific logic,
it is in the wrong place. Tool state belongs in Toolbox/[tool]/state/.
