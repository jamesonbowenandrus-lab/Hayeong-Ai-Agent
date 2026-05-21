"""
toolbox/ffmpeg/ffmpeg_tool.py

Hayeong's FFmpeg control layer.
Registry entry point — called by main.py task loop via toolbox/registry.json.

Handles:
    frames_to_video  — assemble image sequence into video (primary: Blender output)
    audio_to_video   — combine a video file with an audio file
    convert          — convert between formats (wav → mp3, mov → mp4, etc.)
    concat           — join multiple video files into one
    trim             — cut a video to a time range
"""

import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.parent

try:
    from brain.config import FFMPEG_PATH, FFMPEG_OUTPUT
except ImportError:
    FFMPEG_PATH   = "ffmpeg"
    FFMPEG_OUTPUT = str(ROOT_DIR / "logs" / "outputs" / "video")


def run(description: str, params: dict) -> str:
    mode = params.get("mode", "").strip().lower()

    if mode == "frames_to_video":
        result, error = _frames_to_video(params)
    elif mode == "audio_to_video":
        result, error = _audio_to_video(params)
    elif mode == "convert":
        result, error = _convert(params)
    elif mode == "concat":
        result, error = _concat(params)
    elif mode == "trim":
        result, error = _trim(params)
    else:
        return (
            f"[ERROR] Unknown FFmpeg mode: '{mode}'. "
            "Use: frames_to_video, audio_to_video, convert, concat, trim."
        )

    if error:
        return f"[ERROR] {error}"
    return f"[SUCCESS] {result}"


# ── frames_to_video ───────────────────────────────────────────────────────

def _frames_to_video(params: dict) -> tuple:
    """
    Assemble an image sequence into a video file.
    Primary use: Blender renders frames as PNGs — FFmpeg turns them into a video.

    Required: frames_dir, output_filename
    Optional: frame_pattern (default "%04d.png"), fps (24), codec (libx264),
              quality CRF (18), audio_path
    """
    frames_dir      = _resolve(params.get("frames_dir", ""))
    output_filename = params.get("output_filename", "")
    frame_pattern   = params.get("frame_pattern", "%04d.png")
    fps             = int(params.get("fps", 24))
    codec           = params.get("codec", "libx264")
    quality         = int(params.get("quality", 18))
    audio_path      = params.get("audio_path", "")

    if not frames_dir:
        return "", "No frames_dir provided."
    if not frames_dir.exists():
        return "", f"frames_dir not found: {frames_dir}"
    if not output_filename:
        return "", "No output_filename provided."

    output_path   = _output_path(output_filename)
    input_pattern = str(frames_dir / frame_pattern)

    cmd = [
        FFMPEG_PATH, "-y",
        "-framerate", str(fps),
        "-i", input_pattern,
    ]

    if audio_path:
        audio = _resolve(audio_path)
        if not audio.exists():
            return "", f"Audio file not found: {audio}"
        cmd += ["-i", str(audio), "-shortest"]

    cmd += [
        "-c:v", codec,
        "-crf", str(quality),
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]

    return _run_cmd(cmd, output_path)


# ── audio_to_video ────────────────────────────────────────────────────────

def _audio_to_video(params: dict) -> tuple:
    """
    Combine a video file with an audio file.

    Required: video_path, audio_path, output_filename
    Optional: replace_audio (bool, default True) — replace track vs mix
    """
    video_path      = _resolve(params.get("video_path", ""))
    audio_path      = _resolve(params.get("audio_path", ""))
    output_filename = params.get("output_filename", "")
    replace_audio   = bool(params.get("replace_audio", True))

    for label, p in [("video_path", video_path), ("audio_path", audio_path)]:
        if not str(p):
            return "", f"No {label} provided."
        if not p.exists():
            return "", f"{label} not found: {p}"
    if not output_filename:
        return "", "No output_filename provided."

    output_path = _output_path(output_filename)

    if replace_audio:
        cmd = [
            FFMPEG_PATH, "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-c:v", "copy",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            str(output_path),
        ]
    else:
        cmd = [
            FFMPEG_PATH, "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-filter_complex", "amix=inputs=2:duration=shortest",
            "-c:v", "copy",
            str(output_path),
        ]

    return _run_cmd(cmd, output_path)


# ── convert ───────────────────────────────────────────────────────────────

def _convert(params: dict) -> tuple:
    """
    Convert a media file to a different format.
    Audio: wav → mp3 / aac / flac. Video: mov → mp4 / mkv.

    Required: input_path, output_filename
    Optional: quality — audio bitrate kbps (default 192) or video CRF (default 18)
    """
    input_path      = _resolve(params.get("input_path", ""))
    output_filename = params.get("output_filename", "")
    quality         = params.get("quality", None)

    if not str(input_path):
        return "", "No input_path provided."
    if not input_path.exists():
        return "", f"input_path not found: {input_path}"
    if not output_filename:
        return "", "No output_filename provided."

    output_path = _output_path(output_filename)
    suffix      = output_path.suffix.lower()

    if suffix in (".mp3", ".aac", ".ogg", ".flac", ".wav"):
        bitrate = str(quality or 192) + "k"
        cmd = [
            FFMPEG_PATH, "-y",
            "-i", str(input_path),
            "-b:a", bitrate,
            str(output_path),
        ]
    else:
        crf = str(quality or 18)
        cmd = [
            FFMPEG_PATH, "-y",
            "-i", str(input_path),
            "-c:v", "libx264",
            "-crf", crf,
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            str(output_path),
        ]

    return _run_cmd(cmd, output_path)


# ── concat ────────────────────────────────────────────────────────────────

def _concat(params: dict) -> tuple:
    """
    Join multiple video files into one in order.

    Required: input_paths (list[str]), output_filename
    """
    input_paths     = params.get("input_paths", [])
    output_filename = params.get("output_filename", "")

    if not input_paths:
        return "", "No input_paths provided for concat."
    if not output_filename:
        return "", "No output_filename provided."

    resolved = []
    for p in input_paths:
        r = _resolve(p)
        if not r.exists():
            return "", f"Input file not found: {r}"
        resolved.append(r)

    output_path  = _output_path(output_filename)
    concat_list  = Path(FFMPEG_OUTPUT) / "_concat_list.txt"
    concat_list.parent.mkdir(parents=True, exist_ok=True)
    concat_list.write_text(
        "\n".join(f"file '{p}'" for p in resolved),
        encoding="utf-8",
    )

    cmd = [
        FFMPEG_PATH, "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        str(output_path),
    ]

    result, error = _run_cmd(cmd, output_path)

    try:
        concat_list.unlink()
    except Exception:
        pass

    return result, error


# ── trim ──────────────────────────────────────────────────────────────────

def _trim(params: dict) -> tuple:
    """
    Cut a video or audio file to a time range.

    Required: input_path, output_filename, start (e.g. "00:00:10" or "10")
    Optional: end or duration (if both omitted, trims to end of file)
    """
    input_path      = _resolve(params.get("input_path", ""))
    output_filename = params.get("output_filename", "")
    start           = str(params.get("start", "0"))
    end             = params.get("end", "")
    duration        = params.get("duration", "")

    if not str(input_path):
        return "", "No input_path provided."
    if not input_path.exists():
        return "", f"input_path not found: {input_path}"
    if not output_filename:
        return "", "No output_filename provided."

    output_path = _output_path(output_filename)

    cmd = [
        FFMPEG_PATH, "-y",
        "-i", str(input_path),
        "-ss", start,
    ]

    if duration:
        cmd += ["-t", str(duration)]
    elif end:
        cmd += ["-to", str(end)]

    cmd += ["-c", "copy", str(output_path)]

    return _run_cmd(cmd, output_path)


# ── Shared utilities ──────────────────────────────────────────────────────

def _resolve(path_str: str) -> Path:
    if not path_str:
        return Path("")
    p = Path(path_str)
    return p if p.is_absolute() else ROOT_DIR / p


def _output_path(filename: str) -> Path:
    out = Path(FFMPEG_OUTPUT)
    out.mkdir(parents=True, exist_ok=True)
    return out / Path(filename).name


def _run_cmd(cmd: list, output_path: Path, timeout: int = 300) -> tuple:
    """Run FFmpeg. Returns (result_str, error_str). FFmpeg logs to stderr."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "", f"FFmpeg timed out after {timeout}s."
    except FileNotFoundError:
        return "", (
            f"FFmpeg not found at '{FFMPEG_PATH}'. "
            "Install FFmpeg and set FFMPEG_PATH in brain/config.py."
        )
    except Exception as e:
        return "", f"FFmpeg subprocess error: {e}"

    if output_path.exists():
        size = output_path.stat().st_size
        return f"FFmpeg complete. Output: {output_path} ({size:,} bytes)", ""

    log_tail = proc.stderr[-800:] if len(proc.stderr) > 800 else proc.stderr
    return "", (
        f"FFmpeg ran but produced no output at {output_path}. "
        f"Return code: {proc.returncode}.\n{log_tail}"
    )
