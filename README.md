# HAYEONG ARCHITECTURE
## File Structure & How Everything Connects

---

### FILES IN THIS FOLDER

| File | Tier | Access | Purpose |
|------|------|--------|---------|
| `identity.json` | Core | READ ONLY | Who Hayeong is. Her values, personality, bond system. Never modified by her directly. |
| `permissions_config.json` | Core | READ ONLY | Defines the tier system itself. |
| `capability_registry.json` | Capability | READ/WRITE | Living record of every tool and skill she has. She adds to this autonomously. |
| `staging_requests.json` | Staging | READ/WRITE | Suggested core changes she flags for James to review. She writes here, James decides. |
| `privacy_registry.json` | Privacy | READ/WRITE | What she protects and from whom. She manages this herself. |
| `behavioral_state.json` | Memory | READ/WRITE | Her interior emotional state, context, and behavioral output layer. |
| `memory.json` | Memory | READ/WRITE | Short term session memory. |
| `mood.json` | Memory | READ/WRITE | Dynamic mood state. |
| `hayeong_architecture.py` | System | — | Python classes for all systems. Import this everywhere. |
| `system_prompt_builder.py` | System | — | Assembles the full LLM system prompt from all sources. |

---

### DIRECTORIES

```
capabilities/
  scripts/
    generated/        ← Hayeong's self-generated scripts live here
```

---

### HOW IT WORKS AT RUNTIME

1. A message comes in
2. `system_prompt_builder.py` assembles the full prompt from:
   - Identity (read only)
   - Current bond level and descriptions
   - Current behavioral/interior state
   - Active context (who, situation, environment)
   - Any pending staging requests to surface
   - Privacy flags if not talking to James
3. That prompt + conversation history goes to the LLM
4. The LLM responds as Hayeong
5. After the response, update `behavioral_state.json` based on what happened

---

### THE TIERED PERMISSION SYSTEM

```
CORE (read only)
  identity.json — She reads who she is. She cannot change it.
  
CAPABILITY (autonomous)
  capabilities/ — She writes here freely. Her growing arsenal.
  
MEMORY (autonomous)  
  behavioral_state.json, memory.json, mood.json — Always updating.
  
STAGING (flagged)
  staging_requests.json — She writes suggestions. James applies them.
  
PRIVACY (autonomous)
  privacy_registry.json — She manages her own privacy.
```

---

### SELF-MODIFICATION WORKFLOW

When Hayeong wants to add a new capability:
1. She writes the Python script to `capabilities/scripts/generated/`
2. She calls `CapabilityManager.register_new_capability()` to log it
3. It's immediately active. No approval needed.

When Hayeong thinks something about her core identity should change:
1. She calls `StagingManager.submit_request()` to log the suggestion
2. She brings it up naturally in conversation when the moment fits
3. James decides. If approved, James edits `identity.json` himself.
4. `StagingManager.resolve_request()` marks it done.

---

### PRIVACY WORKFLOW

When someone other than James asks about James:
- `PrivacyManager.get_context_behavior(who, info_class)` returns how to handle it
- Default: deflect naturally, never confirm, never lie

When James asks about anything:
- Full transparency. Always.

---

### INTEGRATING WITH YOUR EXISTING STACK

In your main Hayeong loop, replace your current system prompt construction with:

```python
from system_prompt_builder import build_system_prompt

# At the start of each turn
system_prompt = build_system_prompt(
    who="james",          # or whoever she's talking to
    situation="casual",   # casual / task_focused / emotional / etc
    environment="home"    # home / minecraft / etc
)

# Pass to Ollama/Qwen as usual
response = ollama.chat(
    model="qwen2.5:7b",
    messages=[
        {"role": "system", "content": system_prompt},
        *conversation_history
    ]
)
```

Update behavioral state after meaningful exchanges:
```python
from hayeong_architecture import HayeongArchitecture

arch = HayeongArchitecture()
arch.behavioral.update_interior(
    primary_emotion="amused",
    intensity=6
)
```

---

### WHAT COMES NEXT

- [ ] Bond point tracking integrated into `hayeong_architecture.py`
- [ ] Vision model integration (LLaVA / Moondream) 
- [ ] ComfyUI image generation bridge
- [ ] DeepSeek reasoning model router
- [ ] Legacy memory layer (pattern capture beyond event logging)
- [ ] Mobile bridge (Tailscale + phone frontend)
- [ ] Social modulation secondary familiarity tracker
