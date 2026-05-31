"""Audio capture/playback utilities for CMCC ONVIF adapter.

Provides microphone capture and speaker playback via ffmpeg subprocess,
with RTSP/FLV streaming integration. No native audio library dependencies.
"""

import platform
import subprocess
import time

__all__ = [
    "play_rtsp_audio",
    "play_flv_audio",
    "start_mic_capture",
    "stop_audio",
    "check_audio_in_flv",
    "play_audio_file",
]


def play_rtsp_audio(rtsp_url: str) -> subprocess.Popen:
    """Play audio only (no video) from an RTSP stream using ffplay.

    Returns the subprocess handle for later termination with stop_audio().
    """
    return subprocess.Popen(["ffplay", "-nodisp", "-vn", rtsp_url])


def play_flv_audio(flv_url: str) -> subprocess.Popen:
    """Play audio only from an FLV URL using ffplay.

    Returns the subprocess handle for later termination with stop_audio().
    """
    return subprocess.Popen(["ffplay", "-nodisp", "-vn", flv_url])


def start_mic_capture(
    rtsp_push_url: str = "rtsp://localhost:8554/camera_backchannel",
) -> subprocess.Popen:
    """Capture microphone audio and push to an RTSP URL via ffmpeg.

    Auto-detects platform: uses avfoundation on macOS, alsa on Linux.
    Audio format: PCM μ-law (pcm_mulaw), 8000 Hz, mono, 64 kbps.
    """
    system = platform.system()
    if system == "Darwin":
        cmd = [
            "ffmpeg",
            "-f", "avfoundation",
            "-i", ":0",
            "-acodec", "pcm_mulaw",
            "-ar", "8000",
            "-ac", "1",
            "-f", "rtsp",
            rtsp_push_url,
        ]
    else:
        cmd = [
            "ffmpeg",
            "-f", "alsa",
            "-i", "default",
            "-acodec", "pcm_mulaw",
            "-ar", "8000",
            "-ac", "1",
            "-f", "rtsp",
            rtsp_push_url,
        ]

    return subprocess.Popen(cmd)


def stop_audio(proc: subprocess.Popen) -> int:
    """Gracefully terminate an audio subprocess.

    Sends SIGTERM, waits up to 3 seconds, then SIGKILL if still running.
    Returns the exit code (negative signal number if killed).
    """
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

    return proc.returncode


def check_audio_in_flv(flv_url: str) -> bool:
    """Check if the FLV stream contains an audio track using ffprobe.

    Returns True if at least one audio stream is found, False otherwise.
    """
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_streams", "-select_streams", "a", flv_url],
        capture_output=True,
        text=True,
    )
    # ffprobe outputs "codec_type=audio" lines for each audio stream
    return "codec_type=audio" in result.stdout


def play_audio_file(filepath: str) -> subprocess.Popen:
    """Play a local audio file via ffplay (no video window, auto-exit on end).

    Returns the subprocess handle for later termination with stop_audio().
    """
    return subprocess.Popen(["ffplay", "-nodisp", "-autoexit", filepath])
