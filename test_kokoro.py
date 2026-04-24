"""
test_kokoro.py
Run after RTX 3090 install to confirm Kokoro TTS is stable on CUDA.

Tests speed (RTF), quality (listen), and VRAM usage across phrase lengths.
Run once on install day — result determines whether F5-TTS fallback stays.

RTF interpretation:
  RTF < 0.3   — excellent, real-time with headroom
  RTF 0.3–0.7 — good, suitable for conversation voice
  RTF > 1.0   — slower than real-time, not suitable for conversation

Decision:
  RTF < 0.7 and audio sounds natural → Kokoro is primary TTS, remove F5 fallback
  RTF > 1.0 or audio sounds wrong    → Keep F5-TTS as primary, note for later
"""

import sys
import time
import numpy as np

print("─" * 52)
print("  Hayeong — Kokoro TTS Stability Test")
print("─" * 52)
print()

# ── Check CUDA ──
try:
    import torch
    cuda_ok = torch.cuda.is_available()
    gpu     = torch.cuda.get_device_name(0) if cuda_ok else "none"
    vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9 if cuda_ok else 0
    print(f"CUDA available : {cuda_ok}")
    print(f"GPU            : {gpu}")
    print(f"VRAM total     : {vram_gb:.1f}GB")
    print()
    if not cuda_ok:
        print("ERROR — CUDA not available. Install correct PyTorch CUDA build.")
        sys.exit(1)
except ImportError:
    print("ERROR — torch not installed.")
    sys.exit(1)

# ── Load Kokoro ──
try:
    from kokoro import KPipeline
except ImportError:
    print("ERROR — kokoro not installed. Run: pip install kokoro")
    sys.exit(1)

print("Loading Kokoro pipeline on CUDA...")
load_start = time.time()
try:
    pipeline = KPipeline(lang_code="a")
    load_elapsed = time.time() - load_start
    print(f"Loaded in {load_elapsed:.1f}s")
    print()
except Exception as e:
    print(f"ERROR — Kokoro failed to load: {e}")
    sys.exit(1)

# ── Playback ──
try:
    import sounddevice as sd
    PLAYBACK_AVAILABLE = True
except ImportError:
    PLAYBACK_AVAILABLE = False
    print("NOTE — sounddevice not available, skipping audio playback.")
    print()

# ── Test phrases ──
test_phrases = [
    ("short",   0.88, "Hey, what's up?"),
    ("medium",  0.88, "I've been running some background checks on the task queue. Nothing urgent right now."),
    ("long",    0.88, "Working on something interesting — I've been thinking about how to structure the Minecraft planning loop. The 14b should be doing the strategic decisions while the bridge just executes. I'll have more to say on that once I've thought it through properly."),
    ("emotion", 0.85, "That's actually a really good point. I hadn't thought about it that way."),
]

results = []
print("Running synthesis tests...")
print()

for label, speed, text in test_phrases:
    print(f"  [{label}] {text[:55]}...")
    samples = []
    start   = time.time()
    try:
        for _, _, audio in pipeline(text, voice="af_heart", speed=speed):
            samples.append(audio)
    except Exception as e:
        print(f"    ERROR — {e}")
        results.append({"label": label, "rtf": None, "error": str(e)})
        continue

    if not samples:
        print("    ERROR — no audio generated")
        results.append({"label": label, "rtf": None, "error": "empty output"})
        continue

    audio    = np.concatenate(samples)
    elapsed  = time.time() - start
    duration = len(audio) / 24000
    rtf      = elapsed / duration if duration > 0 else 999

    verdict = (
        "excellent" if rtf < 0.3 else
        "good"      if rtf < 0.7 else
        "marginal"  if rtf < 1.0 else
        "TOO SLOW"
    )
    print(f"    {duration:.1f}s audio in {elapsed:.2f}s  →  RTF {rtf:.2f}  ({verdict})")
    results.append({"label": label, "rtf": rtf, "error": None})

    if PLAYBACK_AVAILABLE:
        sd.play(audio, samplerate=24000)
        sd.wait()
    print()

# ── VRAM after all tests ──
print()
vram_used = torch.cuda.memory_allocated(0) / 1e9
print(f"Kokoro VRAM usage after tests: {vram_used:.2f}GB")
print()

# ── Summary ──
print("─" * 52)
print("  RESULTS SUMMARY")
print("─" * 52)

valid_rtfs = [r["rtf"] for r in results if r["rtf"] is not None]
if not valid_rtfs:
    print("  All tests failed — Kokoro is NOT ready.")
    sys.exit(1)

avg_rtf = sum(valid_rtfs) / len(valid_rtfs)
max_rtf = max(valid_rtfs)

for r in results:
    if r["error"]:
        print(f"  [{r['label']:<8}]  FAILED — {r['error']}")
    else:
        bar = "✓" if r["rtf"] < 0.7 else "✗"
        print(f"  [{r['label']:<8}]  RTF {r['rtf']:.2f}  {bar}")

print()
print(f"  Average RTF: {avg_rtf:.2f}")
print(f"  Peak RTF:    {max_rtf:.2f}")
print()

if max_rtf < 0.7:
    print("  VERDICT: Kokoro is ready as primary TTS on this GPU.")
    print()
    print("  Next step: remove F5-TTS fallback from voice.py and voice_server.py.")
    sys.exit(0)
elif max_rtf < 1.0:
    print("  VERDICT: Kokoro is marginal — usable but watch for stuttering on long responses.")
    print("  Recommendation: keep F5-TTS fallback active for now.")
    sys.exit(0)
else:
    print("  VERDICT: Kokoro is too slow for conversation on this GPU.")
    print("  Keep F5-TTS as primary. Do not remove fallback.")
    sys.exit(1)
