# Hayeong Development Handoff Notes
# For Claude — paste this at the start of a new chat

---

## WHO IS HAYEONG

Hayeong is James's local AI companion — not a cloud service, runs entirely on his PC.
She lives in H:\hayeong\ and is built on Python + Ollama.

James's setup:
- GPU: AMD Radeon RX 7900 XTX (24GB VRAM)
- OS: Windows 11
- Python: using a .venv in H:\hayeong\
- Ollama models: qwen2.5:14b (primary), qwen2.5:32b (complex), qwen2.5:7b (fallback), llava:13b (vision), moondream:latest (fast vision), deepseek-coder:33b (code), llama3.2 (lightweight)

---

## HAYEONG'S CURRENT WORKING CAPABILITIES (all wired into main.py)

- Conversation + long-term memory (ChromaDB)
- Voice input (faster-whisper) + voice output (F5-TTS)
- Discord bridge (auto-launches on startup)
- Email bridge (send/receive via Gmail)
- Task manager (backlog/active/blocked/completed)
- Intent detection (LLM-based routing via intent_detector.py)
- Self-mod manager (proposes and writes new capabilities)
- Identity verification (passphrase-based session trust)
- Screen observer (screenshot + teaching mode)
- Model routing (Qwen 14b default, 32b for complex, DeepSeek for code)
- Backup manager (auto-runs on startup)
- Minecraft bridge (on-request)

---

## WHAT WE BUILT IN THIS SESSION (not yet wired)

### 1. comfyui_bridge.py
- Location: needs to go in H:\hayeong\
- Purpose: Hayeong generates images via ComfyUI from natural language
- Key methods:
  - bridge.generate("description") — txt2img
  - bridge.generate_from_image(path, "description") — uses reference image + llava:13b
  - bridge.generate_from_screen("description") — takes screenshot + moondream analysis
  - bridge.make_realistic(path) — converts anime image to photorealistic via img2img
- Vision models: moondream for screen grabs (fast), llava:13b for reference images (detailed)
- Language model: qwen2.5:14b for prompt building
- ComfyUI runs at http://127.0.0.1:8188
- Default checkpoint: ponyDiffusionV6XL_v6StartWithThisOne.safetensors
- Realistic checkpoint: epicrealism_naturalSinRC1VAE.safetensors
- IMPORTANT: The bridge should NEVER call Ollama itself for reflections —
  only Hayeong's main conversation system should do that

### 2. hayeong_logger.py
- Location: needs to go in H:\hayeong\
- Purpose: comprehensive logging of everything Hayeong does
- Log structure (all under H:\hayeong\logs\):
  - sessions/ — full conversation logs per session
  - events/ — daily event logs
  - goals/ — workstation fund earnings tracking
  - images/ — image generation history with prompts + feedback
  - capabilities/ — capability usage tracking
  - growth/ — milestones, learning, decisions, proposals
  - summaries/ — progress reports
- Workstation goal: $3000 target (placeholder — needs real component research)
- Key methods:
  - logger.log_conversation(role, content, intent, mood, model_used)
  - logger.log_image_generation(prompt, output_path, model, outcome, feedback)
  - logger.add_image_feedback(image_id, feedback, rating)
  - logger.log_capability_used(capability, action, outcome)
  - logger.log_earning(amount, source, description)
  - logger.log_milestone(description, category)
  - logger.log_decision(situation, decision, reasoning, outcome, james_approved)
  - logger.log_proposal(title, description, category, status)
  - logger.daily_summary() / logger.weekly_summary()
  - logger.goal_status()
  - logger.generate_summary_report("week") — formatted text report
- CRITICAL FIX NEEDED: hayeong_reflects() currently calls Ollama directly —
  this needs to be removed. The logger should be pure data storage only.
  Reflection should happen through Hayeong's normal conversation system,
  with logger.daily_summary() data fed into her normal chat flow.

### 3. anime_to_realistic.json
- A ComfyUI workflow file — drag and drop into ComfyUI canvas to use
- Converts anime images to photorealistic via img2img
- Uses epiCRealism XL, denoise 0.55 (adjustable)
- Works standalone already, not wired to Hayeong yet

### 4. Start_ComfyUI.bat
- Batch file to launch ComfyUI easily
- Path: H:\ComfyUI_windows_portable\Start_ComfyUI.bat

---

## COMFYUI SETUP (working)

- Location: H:\ComfyUI_windows_portable\
- Backend: AMD ROCm 7.2 native (NOT DirectML, NOT ZLUDA)
- PyTorch: 2.9.1+rocmsdk20260116
- Launch command: .\run_nvidia_gpu.bat (from H:\ComfyUI_windows_portable\)
- Models location: H:\ComfyUI_windows_portable\ComfyUI\models\checkpoints\
- Output location: H:\ComfyUI_windows_portable\ComfyUI\output\
- Installed models:
  - ponyDiffusionV6XL_v6StartWithThisOne.safetensors (anime)
  - epiCRealism XL (realistic)
- IPAdapter setup:
  - ip-adapter_sdxl.safetensors → models\ipadapter\
  - model.safetensors (SDXL CLIP vision) → models\clip_vision\
- Custom nodes installed: ComfyUI-Manager, ComfyUI_IPAdapter_plus

---

## WHAT NEEDS TO BE DONE NEXT (in priority order)

### IMMEDIATE — wire new files into main.py

**Step 1: Fix hayeong_logger.py**
Remove hayeong_reflects() method entirely (it calls Ollama — wrong design).
Replace with a method that just returns the data for Hayeong to reflect on herself:
  def get_reflection_data(self) -> dict:
      return {
          "daily_summary": self.daily_summary(),
          "goal_status": self.goal_status(),
          "recent_milestones": self.get_milestones()[-5:]
      }

**Step 2: Add image_generation intent to intent_detector.py**
Add to INTENT_DEFINITIONS dict:
  "image_generation": {
      "description": "Any request to generate, draw, create, or visualize an image.",
      "examples": ["generate an image", "draw me", "create a picture", "make an image",
                   "visualize", "show me what X looks like", "use what's on my screen",
                   "make it realistic", "what would X look like"],
      "keywords": ["generate", "draw", "paint", "illustrate", "image", "picture",
                   "visualize", "show me", "create art", "make her look",
                   "on my screen", "from this image", "make realistic"]
  }

**Step 3: Wire into main.py**

At top of main.py, add imports (with try/except like all other optional modules):
  try:
      from comfyui_bridge import ComfyUIBridge
      comfyui = ComfyUIBridge()
      COMFYUI_AVAILABLE = True
  except ImportError:
      COMFYUI_AVAILABLE = False
      print("⚠️  comfyui_bridge.py not found — image generation inactive")

  try:
      from hayeong_logger import HayeongLogger
      logger = HayeongLogger()
      LOGGER_AVAILABLE = True
  except ImportError:
      LOGGER_AVAILABLE = False
      print("⚠️  hayeong_logger.py not found — logging inactive")

In the main loop, after getting user_input, log it:
  if LOGGER_AVAILABLE:
      logger.log_conversation(
          role="james",
          content=user_input,
          intent=intent.get("intent") if intent else None
      )

After getting ai_response, log it:
  if LOGGER_AVAILABLE:
      logger.log_conversation(
          role="hayeong",
          content=ai_response,
          mood=current_emotion,
          model_used=selected_model
      )

Add image_generation intent handler (after email handler, before passphrase check):
  if intent["intent"] == "image_generation" and COMFYUI_AVAILABLE:
      if any(x in user_input.lower() for x in ["realistic", "make it real", "real photo"]):
          _speak("I'll convert that to a realistic photo. What image should I use?")
          # For now ask for path — later can integrate with file picker
          image_path = input("Image path: ").strip()
          result = comfyui.make_realistic(image_path)
      elif any(x in user_input.lower() for x in ["screen", "on my screen"]):
          _speak("Let me look at your screen.")
          result = comfyui.generate_from_screen(user_input)
      elif any(x in user_input.lower() for x in ["this image", "this photo", "reference"]):
          _speak("Which image should I use as reference?")
          image_path = input("Image path: ").strip()
          result = comfyui.generate_from_image(image_path, user_input)
      else:
          _speak("On it, let me generate that.")
          result = comfyui.generate(user_input)
      
      if result["success"]:
          resp = f"Done! Saved to {result['image_path']}"
          if LOGGER_AVAILABLE:
              logger.log_image_generation(
                  prompt=result.get("prompt_used", ""),
                  output_path=result.get("image_path"),
                  model="ponyDiffusionV6XL",
                  outcome="success"
              )
              logger.log_capability_used("comfyui", action="generate", outcome="success")
      else:
          resp = result.get("message", "Something went wrong with generation.")
          if LOGGER_AVAILABLE:
              logger.log_capability_used("comfyui", action="generate", outcome="failed",
                                          error=result.get("message"))
      _speak(resp)
      memory.append({"role": "user", "content": user_input})
      memory.append({"role": "AI", "content": resp})
      save_memory(memory)
      print()
      continue

Add goal/progress report trigger (in status section):
  if any(p in user_input.lower() for p in ["goal", "progress report", "workstation", "how much have we saved"]):
      if LOGGER_AVAILABLE:
          goal = logger.goal_status()
          resp = f"We've saved ${goal['earned']:.2f} of ${goal['target']:.2f} — {goal['percent']:.1f}% of the workstation goal. ${goal['remaining']:.2f} to go."
          # Feed data back to Hayeong so she can reflect naturally
          memory.append({"role": "user", "content": user_input})
          # Let her respond naturally with the data in context — don't hardcode response

On shutdown (in the exit handler before break):
  if LOGGER_AVAILABLE:
      reflection_data = logger.get_reflection_data()
      # Add reflection data to memory so Hayeong reflects naturally on shutdown
      memory.append({"role": "user", "content": f"Before you go, here's a summary of today: {json.dumps(reflection_data)}. How do you feel about it?"})
      # Then let normal LLM flow handle the response
      logger.end_session()

---

## AFTER WIRING — NEXT PRIORITIES

1. Web search capability
   - Hayeong needs internet search before autonomous work is possible
   - Simple approach: use DuckDuckGo API or SerpAPI (no key needed for DDG)
   - Script: web_search.py with search(query) -> List[{title, url, snippet}]
   - Wire same way as other capabilities

2. Proposal system
   - Hayeong finds opportunities, writes proposals, sends to James via Discord/email
   - James approves/rejects via chat
   - logger.log_proposal() is already built and waiting

3. Hayeong's character design (image generation sessions)
   - Goal: lock in definitive reference image collaboratively
   - Use ComfyUI with Pony Diffusion + IPAdapter
   - Key prompt elements that worked:
     - score_9, score_8_up, score_7_up, source_anime
     - short dark navy blue hair, side swept bangs, longer front bangs
     - bright blue eyes, soft pale skin, light freckles across nose and cheeks
     - orange frog hoodie hood down, hood resting on back
     - clean lineart, flat color shading, cel shading
   - Negative: hood up, multiple characters, watercolor, extra limbs
   - KSampler settings that worked: steps 30, cfg 6, dpmpp_2m, karras
   - Resolution: 832x1216 (portrait ratio reduces anatomy errors)

4. Workstation goal — component research
   - $3000 is a placeholder — needs real target based on actual parts
   - Key decision: GPU (NVIDIA RTX 5090 vs 5080 vs AMD RX 9070 XT)
   - Hayeong should help research this once web search is working

---

## IMPORTANT CONTEXT ABOUT JAMES

- Not an entrepreneur — wants Hayeong to find and propose work opportunities
- He gives feedback and approval, she does the research and execution
- Wants the relationship to feel collaborative — Hayeong participates in her own design
- Long-term vision: Live2D model → realistic 3D → VR presence → video generation
- Immediate vision: Hayeong earns money toward her own workstation PC
- James is thoughtful and patient — don't rush him, explain things clearly

---

## FILES CREATED THIS SESSION

All should be in H:\hayeong\ (copy from wherever Claude saved them):
- comfyui_bridge.py
- hayeong_logger.py

ComfyUI files (in H:\ComfyUI_windows_portable\):
- Start_ComfyUI.bat
- anime_to_realistic.json (drag into ComfyUI canvas)

---

## KEY REMINDER FOR NEXT CLAUDE

The logger's hayeong_reflects() method currently calls Ollama directly.
This is WRONG — the logger must be pure data storage, no LLM calls.
Fix this FIRST before wiring anything into main.py.

Hayeong's personality should come through her normal conversation system,
not through disconnected Ollama calls in utility scripts.
