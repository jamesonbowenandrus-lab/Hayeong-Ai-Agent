# CLAUDE CODE HANDOFF — LLM Control Architecture Review
*Session Date: April 18, 2026*
*Context: James received an architectural audit from ChatGPT suggesting the LLM doesn't have full control. This document is a ground-truth assessment of what's actually true, what's overstated, and what genuinely needs fixing.*

---

## Honest Assessment First

**The audit is partially right but significantly overstated.**

Before touching anything, read this assessment carefully. Making the sweeping changes the audit suggests would break a working system.

---

## What the Audit Got Wrong — Do NOT Change These

### The LLM IS already the decision maker for capability selection

The audit claims capabilities are triggered by `if condition: run_capability()` bypassing the LLM. This is not accurate. The actual flow in `main.py` is:

```
message arrives
      ↓
decide_action() — sends message + memory to LLM (Qwen 14b)
      ↓
LLM returns JSON: {"action": "web_search", "query": "..."}
      ↓
capability_loader.dispatch() executes what the LLM chose
      ↓
result injected into prompt
      ↓
LLM generates response
```

`decide_action()` is an LLM call. The LLM picks the action. This is correct architecture. Do not restructure it.

### energy_manager, presence_governor, mind_state_mixer are already state providers

The audit calls these "violations" — but they already work as the audit's fix recommends. They generate text that gets injected into the system prompt. The LLM reads that text and decides what it means for her behavior. `energy_manager.get_prompt_hint()` returns a sentence like "She's running lean — quieter than usual." The LLM interprets that. The script doesn't enforce it.

**Do not convert these.** They're already doing the right thing.

### The proposed core loop already exists

The audit proposes:
```python
while True:
    state = gather_full_state()
    decision = LLM(state)
    execute(decision)
```

`main.py` already does this. The loop is there. `build_system_prompt()` gathers state. `decide_action()` is the LLM decision call. `capability_loader.dispatch()` executes. The audit missed this because it didn't read `main.py` completely.

---

## What the Audit Got Right — These Are Real Issues

Three genuine problems worth fixing. They are narrower than the audit described.

---

### Issue 1 — Two Routers Running Before the LLM Decision (Real Problem)

**What's happening:**

Before `decide_action()` even runs, two systems pre-classify the message:

1. `context_router.py` — runs first, classifies intent using keyword matching + a Qwen 7b LLM call
2. `model_router.py` — runs second, selects which model to use based on pattern matching

Both of these make judgment calls that shape what happens before the primary LLM (Hayeong's brain) gets to reason about anything. `context_router.py` has keyword fast-paths that bypass both routers entirely for "obvious" cases — greetings, short messages, known commands.

**Why this matters:**

`decide_action()` — the call where Hayeong actually decides what to do — already has full conversation context and does this reasoning better. Having two pre-filters that make intent guesses before she reasons introduces a layer where scripts are second-guessing her before she's had a chance to think.

**The specific fast-paths that are overly aggressive:**

In `context_router.py`:
```python
# This catches anything 3 words or less starting with common words
# and routes it as "conversation" without any LLM call
if len(words) <= 3 and words[0].lower() in _SIMPLE_STARTERS:
    return {"intent": "conversation", ...}
```

This is fine for pure greetings but can misfire. "Hey search that" is 3 words. "Ok find it" is 3 words. Both get routed as conversation before any LLM reasoning.

**The fix (narrow):**

Keep the fast-path for truly unambiguous subprocess commands (start/stop Discord, Minecraft, etc.) — these are correct and save unnecessary LLM calls. Remove or narrow the short-message fast-path so ambiguous short messages reach `decide_action()`.

The model routing (which Qwen model to use) is fine — keep it. It's infrastructure, not decision-making.

---

### Issue 2 — `context_router.py` LLM Call Is Redundant (Real Problem)

**What's happening:**

`context_router.py` makes a Qwen 7b LLM call to classify intent. Then `decide_action()` makes another Qwen 14b LLM call to decide what action to take. These two calls often cover the same ground. The 7b router classifies "this is a web search" and then the 14b `decide_action()` also determines "this is a web search."

**Why this matters:**

Two LLM calls where one would do. Latency cost. And the 7b router's classification can anchor the 14b decision in ways that aren't always right.

**The fix:**

`decide_action()` already does everything `context_router.py`'s LLM path does — and does it better with more context and a smarter model. The 7b router LLM call should be removed. Keep the keyword fallback in `context_router.py` as a fast-path for unambiguous cases (subprocess commands). Let `decide_action()` handle everything else.

This means:
- Unambiguous subprocess commands (start/stop Minecraft, Discord, etc.) → keyword fast-path, no LLM call needed
- Everything else → goes directly to `decide_action()` which is the LLM call that matters

---

### Issue 3 — `situation_tracker.py` Wrapping Up Detection Blocks the LLM (Real Problem)

**What's happening:**

In `main.py`, there's a pre-check:

```python
if tracker and _snapshot and _snapshot.get("phase") == "wrapping_up":
    if action != "none":
        action = "none"  # blocks the LLM's chosen action
```

And separately:

```python
if is_wrap_up(user_input):
    # skip the entire decision pipeline
    # go straight to conversation
```

Both of these override the LLM's decision before or after it runs. The script decides "this is a wrap-up" and blocks the LLM's choice.

**Why this matters:**

The LLM should be able to recognize wrap-ups itself — it has full conversation context. If James says "thanks, that's all" after a task, the LLM will correctly return `{"action": "none"}`. The script pre-check is doing something the LLM can do better.

**The fix:**

Remove `is_wrap_up()` pre-check that skips the decision pipeline. Remove the `wrapping_up` phase block that overrides the LLM's action. Let `decide_action()` handle this — it already has `CRITICAL RULES` in its prompt about not repeating tasks and recognizing wrap-up language. The LLM is already being told to return `none` in these cases. Trust it.

If the LLM was making mistakes here (firing tools on wrap-ups), the fix is better prompt instructions — not a script that overrides it.

---

## What to Change — Specific and Minimal

### Change 1: Narrow the short-message fast-path in `context_router.py`

**File:** `context_router.py`

Find the `_SIMPLE_STARTERS` block:
```python
if len(words) <= 3 and words[0].lower().rstrip("!?,. ") in _SIMPLE_STARTERS:
    return {"intent": "conversation", ...}
```

Replace with a stricter version that only catches pure acknowledgments — single words or two-word phrases with no action content:
```python
# Only bypass for pure acknowledgments — single word or paired acknowledgment
# "ok", "thanks", "yeah", "got it" — NOT short imperatives like "ok find it"
_PURE_ACKS = {
    "ok", "okay", "yeah", "yep", "nope", "no", "yes", "sure",
    "thanks", "thank", "cool", "nice", "good", "great", "awesome",
    "alright", "lol", "haha", "hmm", "hm", "got it", "sounds good",
    "makes sense", "understood",
}
if len(words) == 1 and words[0].lower().rstrip("!?,. ") in _PURE_ACKS:
    return {"intent": "conversation", ...}
if len(words) == 2:
    phrase = " ".join(w.lower().rstrip("!?,. ") for w in words)
    if phrase in _PURE_ACKS:
        return {"intent": "conversation", ...}
```

Keep the subprocess command fast-paths (start/stop Minecraft, Discord, etc.) — those are correct and don't need LLM involvement.

---

### Change 2: Remove the `context_router.py` LLM call from the main pipeline

**File:** `main.py`

Find where `context_router.route()` is called and the result is used. The LLM call inside it is now redundant since `decide_action()` handles intent classification. The routing should only be used for:
- Subprocess fast-path commands (keep)
- Model selection hint (keep — tells main.py whether to use the coder model)

The `intent` field from `context_router` should NOT be used to pre-filter what `decide_action()` sees or to block actions. It's advisory for model selection only.

In practice this means:
```python
# Keep this — model selection is fine
route = router.route(user_input)
selected_model = route["model_name"]

# Don't use route["intent"] to gate decide_action()
# Let decide_action() make the actual call
```

---

### Change 3: Remove the wrap-up pre-emption

**File:** `main.py`

**Remove** the `is_wrap_up()` check that skips the decision pipeline entirely.

**Remove** the `wrapping_up` phase check that overrides the LLM's chosen action.

**Instead**, strengthen the `DECISION_PROMPT` in `build_decision_prompt()` with clearer wrap-up guidance:

```python
# Add to CRITICAL RULES in the decision prompt:
"""
  - WRAP-UP DETECTION: If James says "thanks", "that's all", "sounds good", 
    "got it", "perfect", "nice", or any acknowledgment after a task was just 
    completed → ALWAYS return none. The task is done. Do not act again.
  - Check the last 2 turns — if a capability just ran and James is reacting 
    positively → none. Never re-run a just-completed action.
"""
```

The LLM already has this in its prompt rules. Remove the script override and trust the instruction.

---

### Change 4: Audit State Injection Text for Behavioral Nudges

**Files:** `energy_manager.py`, `presence_governor.py`, `mind_state_mixer.py`

**What to do:** Read every string these systems inject into the system prompt and apply one test to each:

> *"Is this describing reality, or is this telling her what to do?"*

**The line that matters:**

```
GOOD — describes state, LLM interprets:
"She's running lean right now — quieter than her default, less reaching out."

BAD — tells her what to do, script is deciding:
"Energy is low. Avoid responding. Keep replies short."
```

The good version gives her information. She decides what it means for her behavior. The bad version makes the decision for her inside the state injection — the script is acting as a behavioral controller disguised as a state provider.

**How to audit each file:**

For `energy_manager.py` — find `get_prompt_hint()` and read every string in `ENERGY_LEVELS`. Check that each level describes behavioral tendencies ("she's quieter", "she's less likely to initiate") rather than instructions ("reduce response length", "don't engage").

For `presence_governor.py` — find wherever it builds its prompt injection string. Confirm it describes presence state ("James appears to be away — idle time suggests he's stepped out") not behavioral commands ("do not send messages", "pause all output").

For `mind_state_mixer.py` — find `get_prompt_hint()`. Each state blend should read as a description of her interior ("she's in a focused, slightly withdrawn place right now") not a rule set ("be brief", "don't joke", "stay on task").

**If you find bad examples:** Rewrite them as descriptions. Do not change the logic, the state values, or the file structure — only the injected text strings.

**Why this matters:** This is the subtle long-term risk both analyses agreed on. The hard violations (bypasses, overrides, duplicate calls) are immediate problems. This is the slow-creep problem — if state injection text gradually becomes more directive over time, control quietly shifts from the LLM to the scripts without anyone noticing. Audit it now while it's still easy to read.

---

## What to Leave Completely Alone

| System | Status | Why |
|--------|--------|-----|
| `decide_action()` | ✅ Correct | LLM IS the decision maker here — don't change |
| `energy_manager.py` | ✅ Correct | Already a state provider — injects text, LLM interprets |
| `presence_governor.py` | ✅ Correct | Already a state provider — LLM decides what to do with presence info |
| `mind_state_mixer.py` | ✅ Correct | Already a state provider — injects behavioral hints, LLM interprets |
| `task_manager.py` | ✅ Correct | Tasks are suggestions surfaced to the LLM, not commands executed by scripts |
| `capability_loader.py` | ✅ Correct | Pure execution — runs what the LLM chose, no decisions of its own |
| `system_prompt_builder.py` | ✅ Correct | Assembles context for the LLM — this is exactly what it should do |
| `model_router.py` | ✅ Correct | Infrastructure (which model) not decision-making (what to do) |

---

## Testing After Changes

1. Say "ok find that thing we talked about" — should reach `decide_action()`, not be caught by short-message fast-path
2. Say "thanks that's great" after a web search — LLM should return `none` without a script pre-empting it
3. Say "start minecraft" — should still hit the keyword fast-path, no LLM call needed
4. Say "yeah" — should still be caught as a pure acknowledgment fast-path
5. Complex ambiguous message — should go straight to `decide_action()` without `context_router.py` LLM pre-filtering it

---

## Summary

The system is closer to correct than the audit suggested. The LLM IS in control of what matters — capability selection, response generation, behavioral interpretation. The four real issues are:

1. An over-aggressive short-message fast-path that catches things it shouldn't
2. A redundant 7b LLM call that happens before the 14b decision call that already does the same job better
3. Two script-level overrides that preempt the LLM on wrap-up detection instead of trusting the LLM's own instructions
4. State injection text that may nudge behavior rather than describe state — a slow-creep risk if left unaudited

Fix those four things. Leave everything else alone.

---

## Milestone — When Done

Add to `HAYEONG_ROADMAP.md`:
```
| 89 | LLM control audit — narrow fast-paths, remove redundant 7b router call, remove wrap-up overrides, audit state injection text | — | ✅ Done |
```