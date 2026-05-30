"""简易 RTSP/MJPEG 中继 - 不依赖外部二进制"""

import subprocess
import threading
import time
import os
import signal

_proc = None

def start_relay(flv_url, mjpeg_port=8555):
    """用 ffmpeg 将 FLV 转 MJPEG 流，通过 HTTP 提供"""
    global _proc
    _proc = subprocess.Popen([
        "ffmpeg", "-re", "-i", flv_url,
        "-c:v", "mjpeg", "-q:v", "5", "-f", "mpjpeg",
        f"http://0.0.0.0:{mjpeg_port}/stream"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    return _proc.poll() is None

def stop_relay():
    global _proc
    if _proc:
        _proc.terminate()
        _proc = None
