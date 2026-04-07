#!/usr/bin/env python3
"""
HAYEONG VOICE PREP TOOLKIT
Strips audio from YouTube, cuts clips, and builds XTTS-ready samples.

SETUP (run once):
    pip install yt-dlp pydub
    # ffmpeg must be installed — on Windows: https://ffmpeg.org/download.html
    # or: winget install ffmpeg

WORKFLOW:
    Step 1 — Download audio from YouTube URLs
        python voice_prep.py download

    Step 2 — Cut clips from downloaded audio
        python voice_prep.py cut

    Step 3 — Review and pick your best clips, then build final samples
        python voice_prep.py build

    Step 4 — Validate clips are XTTS-ready
        python voice_prep.py validate
"""

import os
import sys
import json
import subprocess
from pathlib import Path

# ─────────────────────────────────────────────
# CONFIGURATION
# Edit this section to match your clips and preferences
# ─────────────────────────────────────────────

# Where everything lives
DOWNLOADS_DIR  = Path("voice_prep/downloads")   # raw YouTube audio
CLIPS_DIR      = Path("voice_prep/clips")        # cut segments
SAMPLES_DIR    = Path("voice_prep/samples")      # final XTTS-ready files
SESSIONS_FILE  = Path("voice_prep/sessions.json")

# Your YouTube sources
# Add as many as you want — one URL per entry
# name: short label for the file
# url:  full YouTube URL
SOURCES = [
    # Example — replace these with your actual sources:
    # {"name": "source_01", "url": "https://www.youtube.com/watch?v=XXXXXXXXX"},
    # {"name": "source_02", "url": "https://www.youtube.com/watch?v=XXXXXXXXX"},
    
    {"name": "source_01", "url": "https://www.youtube.com/shorts/kep8hWOrMmA"},
    {"name": "source_02", "url": "https://www.youtube.com/watch?v=63jkaB0bof8"},
     {"name": "source_03", "url": "https://www.youtube.com/watch?v=P7JblaJ40Yo&t=245s"},
    {"name": "source_04", "url": "https://www.youtube.com/watch?v=UbTIMTqP0xg&t=337s"},
]

# Clips to cut from downloaded audio
# file:  which downloaded file to cut from (just the name, no extension)
# start: timestamp to start cut  (format: "MM:SS" or "HH:MM:SS")
# end:   timestamp to end cut    (format: "MM:SS" or "HH:MM:SS")
# label: short description of what this clip is (tone, mood, content)
# keep:  set to False to skip this clip in the final build
CLIPS = [
    # Example — fill these in after you've listened to downloads:
    # {"file": "source_01", "start": "0:32", "end": "0:48", "label": "calm_neutral",  "keep": True},
    # {"file": "source_01", "start": "1:14", "end": "1:28", "label": "slightly_warm", "keep": True},
    # {"file": "source_02", "start": "3:05", "end": "3:22", "label": "focused_voice", "keep": True},
    {"file": "source_01", "start": "0:00", "end": "0:15", "label": "calm_relaxed",  "keep": True},
    {"file": "source_02", "start": "0:00", "end": "3:00", "label": "slightly_warm", "keep": True},
    {"file": "source_03", "start": "6:50", "end": "7:50:00", "label": "stressed", "keep": True},
    {"file": "source_04", "start": "0:00", "end": "5:00", "label": "stressed", "keep": True},
]

# XTTS v2 requirements:
# - WAV format, 22050 Hz, mono
# - Each clip: 6–30 seconds (10–15 is ideal)
# - Clean speech, no music/background noise
# - Consistent speaker — same vocal character throughout
# - No very loud or very quiet sections

# ─────────────────────────────────────────────
# STEP 1 — DOWNLOAD
# ─────────────────────────────────────────────

def download_all():
    """Downloads audio from all URLs in SOURCES."""
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    if not SOURCES:
        print("⚠️  No sources defined. Add YouTube URLs to SOURCES in the config section.")
        return

    for source in SOURCES:
        name = source["name"]
        url  = source["url"]
        out  = DOWNLOADS_DIR / f"{name}.%(ext)s"
        final = DOWNLOADS_DIR / f"{name}.wav"

        if final.exists():
            print(f"✅ Already downloaded: {name}")
            continue

        print(f"\n📥 Downloading: {name}")
        print(f"   {url}")

        cmd = [
            "yt-dlp",
            "--extract-audio",
            "--audio-format", "wav",
            "--audio-quality", "0",
            "--output", str(out),
            "--no-playlist",
            url
        ]

        result = subprocess.run(cmd, capture_output=False)
        if result.returncode == 0:
            print(f"✅ Downloaded: {name}.wav")
        else:
            print(f"❌ Failed: {name} — check the URL and try again")

    print(f"\n📁 Downloads saved to: {DOWNLOADS_DIR}")
    print("Next: listen to the files, fill in CLIPS[], then run: python voice_prep.py cut")


# ─────────────────────────────────────────────
# STEP 2 — CUT
# Cuts timestamped segments from downloaded audio
# ─────────────────────────────────────────────

def parse_timestamp(ts: str) -> float:
    """Converts MM:SS or HH:MM:SS to seconds."""
    parts = ts.strip().split(":")
    parts = [float(p) for p in parts]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    elif len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return float(parts[0])


def cut_clips():
    """Cuts all clips defined in CLIPS."""
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)

    if not CLIPS:
        print("⚠️  No clips defined. Fill in CLIPS[] in the config section after listening to downloads.")
        return

    kept = 0
    skipped = 0

    for i, clip in enumerate(CLIPS):
        if not clip.get("keep", True):
            skipped += 1
            continue

        src_file = DOWNLOADS_DIR / f"{clip['file']}.wav"
        if not src_file.exists():
            print(f"❌ Source file not found: {src_file}")
            print(f"   Run: python voice_prep.py download   first")
            continue

        start   = parse_timestamp(clip["start"])
        end     = parse_timestamp(clip["end"])
        duration = end - start
        label   = clip.get("label", f"clip_{i:02d}")
        out_name = f"clip_{i:02d}_{label}.wav"
        out_path = CLIPS_DIR / out_name

        print(f"✂️  Cutting: {out_name}  ({clip['start']} → {clip['end']}, {duration:.1f}s)")

        cmd = [
            "ffmpeg", "-y",
            "-i", str(src_file),
            "-ss", str(start),
            "-t",  str(duration),
            "-ar", "22050",
            "-ac", "1",
            "-sample_fmt", "s16",
            str(out_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            size = out_path.stat().st_size / 1024
            print(f"   ✅ {out_name} ({size:.0f}KB)")
            kept += 1
        else:
            print(f"   ❌ Failed: {result.stderr[-200:]}")

    print(f"\n✂️  Done. {kept} clips cut, {skipped} skipped.")
    print(f"📁 Clips saved to: {CLIPS_DIR}")
    print("\nListen to the clips. Edit CLIPS[] to set keep=False on anything that doesn't work.")
    print("Then run: python voice_prep.py build")


# ─────────────────────────────────────────────
# STEP 3 — BUILD
# Processes kept clips into final XTTS-ready samples
# Normalizes volume, trims silence, validates length
# ─────────────────────────────────────────────

def build_samples():
    """Processes clips into final XTTS-ready WAV files."""
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

    clips = sorted(CLIPS_DIR.glob("*.wav"))
    if not clips:
        print("⚠️  No clips found. Run: python voice_prep.py cut   first")
        return

    print(f"🔧 Building {len(clips)} samples...\n")
    built = 0

    for clip_path in clips:
        out_path = SAMPLES_DIR / clip_path.name

        # Normalize volume + trim silence from start/end
        cmd = [
            "ffmpeg", "-y",
            "-i", str(clip_path),
            # Normalize to -3dB peak
            "-af", (
                "silenceremove=start_periods=1:start_silence=0.2:start_threshold=-50dB"
                ":stop_periods=1:stop_silence=0.3:stop_threshold=-50dB,"
                "loudnorm=I=-16:LRA=11:TP=-1.5"
            ),
            "-ar", "22050",
            "-ac", "1",
            "-sample_fmt", "s16",
            str(out_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            # Check duration
            dur = get_duration(out_path)
            status = "✅" if 6 <= dur <= 30 else "⚠️ "
            note   = "" if 6 <= dur <= 30 else f" ← {'too short (min 6s)' if dur < 6 else 'too long (max 30s)'}"
            print(f"  {status} {clip_path.name}  ({dur:.1f}s){note}")
            built += 1
        else:
            print(f"  ❌ Failed: {clip_path.name}")
            print(f"     {result.stderr[-150:]}")

    print(f"\n🎙️  {built} samples built.")
    print(f"📁 Saved to: {SAMPLES_DIR}")
    print("\nRun: python voice_prep.py validate   to see a full quality report")


# ─────────────────────────────────────────────
# STEP 4 — VALIDATE
# Checks every sample against XTTS requirements
# ─────────────────────────────────────────────

def get_duration(path: Path) -> float:
    """Gets audio duration in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def get_audio_info(path: Path) -> dict:
    """Gets sample rate and channel info."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate,channels",
        "-of", "json",
        str(path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        info = json.loads(result.stdout)
        stream = info["streams"][0]
        return {
            "sample_rate": int(stream["sample_rate"]),
            "channels":    int(stream["channels"])
        }
    except Exception:
        return {"sample_rate": 0, "channels": 0}


def validate_samples():
    """Validates all samples in SAMPLES_DIR against XTTS requirements."""
    samples = sorted(SAMPLES_DIR.glob("*.wav"))

    if not samples:
        print("⚠️  No samples found in samples/")
        print("Run: python voice_prep.py build   first")
        return

    print(f"\n📋 Validating {len(samples)} samples...\n")
    print(f"{'File':<45} {'Duration':>10} {'SampleRate':>12} {'Channels':>10} {'Status':>10}")
    print("─" * 95)

    ready = 0
    issues = 0

    for path in samples:
        dur  = get_duration(path)
        info = get_audio_info(path)
        sr   = info["sample_rate"]
        ch   = info["channels"]

        problems = []
        if dur < 6:     problems.append("too short (<6s)")
        if dur > 30:    problems.append("too long (>30s)")
        if sr != 22050: problems.append(f"wrong rate ({sr}≠22050)")
        if ch != 1:     problems.append("not mono")

        if problems:
            status = "❌ " + ", ".join(problems)
            issues += 1
        else:
            status = "✅ ready"
            ready += 1

        print(f"  {path.name:<43} {dur:>9.1f}s {sr:>11}Hz {ch:>9}ch   {status}")

    print("─" * 95)
    print(f"\n✅ XTTS-ready: {ready}   ❌ Issues: {issues}")

    if ready >= 5:
        print(f"\n🎙️  You have {ready} clean samples — enough to clone a voice.")
        print(f"📁 Point XTTS v2 at: {SAMPLES_DIR.resolve()}")
    elif ready > 0:
        print(f"\n⚠️  You have {ready} samples — XTTS works best with 5+.")
        print("    Cut more clips and rebuild.")
    else:
        print("\n❌ No ready samples. Check the issues above.")

    if issues > 0:
        print("\n💡 To fix sample rate or channel issues, re-run: python voice_prep.py build")


# ─────────────────────────────────────────────
# STEP 0 — LISTEN HELPER
# Opens downloads folder so you can listen before cutting
# ─────────────────────────────────────────────

def list_downloads():
    """Lists downloaded files with durations so you know what you're working with."""
    files = sorted(DOWNLOADS_DIR.glob("*.wav"))
    if not files:
        print("No downloads yet. Run: python voice_prep.py download")
        return

    print(f"\n📁 Downloaded files in {DOWNLOADS_DIR}:\n")
    for f in files:
        dur = get_duration(f)
        mins = int(dur // 60)
        secs = int(dur % 60)
        size = f.stat().st_size / (1024 * 1024)
        print(f"  {f.name:<40} {mins}m{secs:02d}s   {size:.1f}MB")

    print(f"\n{len(files)} files. Listen to them and fill in CLIPS[] with your timestamps.")
    print("Then run: python voice_prep.py cut")


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

COMMANDS = {
    "download": (download_all,    "Download audio from YouTube URLs in SOURCES"),
    "list":     (list_downloads,  "List downloaded files with durations"),
    "cut":      (cut_clips,       "Cut clips from downloads using timestamps in CLIPS"),
    "build":    (build_samples,   "Normalize and finalize clips into XTTS-ready samples"),
    "validate": (validate_samples,"Check all samples meet XTTS v2 requirements"),
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("\n🎙️  HAYEONG VOICE PREP TOOLKIT\n")
        print("Usage: python voice_prep.py <command>\n")
        for cmd, (_, desc) in COMMANDS.items():
            print(f"  {cmd:<12} — {desc}")
        print("\nWorkflow:")
        print("  1. Add YouTube URLs to SOURCES in this file")
        print("  2. python voice_prep.py download")
        print("  3. Listen to downloads, fill in CLIPS[] with timestamps")
        print("  4. python voice_prep.py cut")
        print("  5. Listen to clips, set keep=False on anything bad")
        print("  6. python voice_prep.py build")
        print("  7. python voice_prep.py validate")
        sys.exit(0)

    cmd, (fn, _) = sys.argv[1], COMMANDS[sys.argv[1]]
    fn()
