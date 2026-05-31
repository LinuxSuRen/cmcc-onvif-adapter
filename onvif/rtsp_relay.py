"""RTSP/MJPEG relay — tries MediaMTX RTSP, falls back to MJPEG HTTP."""

import socket
import subprocess
import time

_proc = None
_mode = None


def _check_port(host, port, timeout=1.0):
    """Check if a TCP port is open on the given host."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def _probe_audio(flv_url):
    """Return True if the FLV stream contains an audio track."""
    try:
        result = subprocess.run(
            ["ffprobe", "-i", flv_url, "-show_streams", "-select_streams", "a",
             "-loglevel", "error"],
            capture_output=True, text=True, timeout=10)
        return "codec_type=audio" in result.stdout
    except Exception:
        return False


def _start_rtsp_push(flv_url):
    """Push FLV to MediaMTX via RTSP (H.264 + AAC)."""
    global _proc
    cmd = ["ffmpeg", "-re", "-i", flv_url,
           "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
           "-pix_fmt", "yuv420p"]
    if _probe_audio(flv_url):
        cmd += ["-c:a", "aac", "-ar", "44100", "-ac", "1"]
    else:
        cmd += ["-an"]
    cmd += ["-f", "rtsp", "rtsp://localhost:8554/camera"]

    _proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    return _proc.poll() is None


def _start_mjpeg_relay(flv_url, mjpeg_port):
    """Fall back to MJPEG HTTP relay (video only, no audio)."""
    global _proc
    _proc = subprocess.Popen([
        "ffmpeg", "-re", "-i", flv_url,
        "-c:v", "mjpeg", "-q:v", "5", "-f", "mpjpeg",
        f"http://0.0.0.0:{mjpeg_port}/stream"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    return _proc.poll() is None


def start_rtsp_relay(flv_url, mjpeg_port=8555):
    """Try MediaMTX RTSP; if unavailable, fall back to MJPEG HTTP relay."""
    global _proc, _mode

    if _check_port("localhost", 8554):
        _mode = "rtsp"
        return _start_rtsp_push(flv_url)
    else:
        _mode = "mjpeg"
        return _start_mjpeg_relay(flv_url, mjpeg_port)


def start_relay(flv_url, mjpeg_port=8555):
    """Legacy wrapper: delegates to start_rtsp_relay."""
    return start_rtsp_relay(flv_url, mjpeg_port)


def stop_relay():
    """Terminate the relay process."""
    global _proc
    if _proc:
        _proc.terminate()
        _proc = None


def get_rtsp_url(host_ip="192.168.1.138"):
    """Get the RTSP stream URL (works only in rtsp mode)."""
    return f"rtsp://{host_ip}:8554/camera"


def get_mode():
    """Return current relay mode: 'rtsp' (audio+video) or 'mjpeg' (video only)."""
    return _mode
