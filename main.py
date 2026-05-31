"""和家亲 CMCC V31S 摄像头 - 交互式云台控制 Demo"""

import cmd
import os
import platform
import sys
import threading
import time
import subprocess

from auth import HJQAuth
from stream import get_live_url, get_device_info, keep_alive, take_snapshot
from ptz import PTZController
import onvif
from onvif.rtsp_relay import get_mode
import audio


class CameraConsole(cmd.Cmd):
    intro = """
╔══════════════════════════════════════════╗
║   CMCC V31S 云台控制 Demo               ║
║   基于 和家亲 云端 API 逆向              ║
╚══════════════════════════════════════════╝
输入 help 查看命令, login <手机号> <密码> 开始
"""
    prompt = "📷> "

    def __init__(self):
        super().__init__()
        self.auth: HJQAuth | None = None
        self.cam = None
        self.ptz: PTZController | None = None
        self._keep_alive_task = None
        self._stop_keep_alive = threading.Event()
        self._intercom_proc = None
        self._audio_proc = None

    # ── 登录 ────────────────────────────────────────
    def do_login(self, arg: str):
        args = arg.strip().split()
        if len(args) < 2:
            print("用法: login <手机号> <密码>")
            return
        self.auth = HJQAuth(args[0], args[1])
        if not self.auth.login():
            print("登录失败")
            return
        if not self.auth.get_video_auth():
            print("视频鉴权失败")
            return

        cameras = self.auth.get_cameras()
        if not cameras:
            print("没有找到摄像头")
            return

        if len(cameras) == 1:
            self.cam = cameras[0]
            self._after_select()
        else:
            print(f"发现 {len(cameras)} 个摄像头:")
            for i, c in enumerate(cameras):
                print(f"  {i}: {c.mac_name} ({c.mac_id})")
            print("用 select <编号> 选择")

    def do_select(self, arg: str):
        if not self.auth:
            print("请先 login")
            return
        cameras = self.auth.get_cameras()
        try:
            idx = int(arg.strip())
            self.cam = cameras[idx]
        except (ValueError, IndexError):
            print(f"无效编号, 共 {len(cameras)} 个")
            return
        self._after_select()

    def _after_select(self):
        self.ptz = PTZController(self.auth, self.cam)
        info = get_device_info(self.auth, self.cam)
        print(f"✅ 已选择: {self.cam.mac_name}")
        print(f"   型号: {info.get('mac_model', '?')}  固件: {info.get('firmware_model', '?')}")

    # ── 云台控制 ────────────────────────────────────
    def do_up(self, _):
        self._move("up")
    def do_down(self, _):
        self._move("down")
    def do_left(self, _):
        self._move("left")
    def do_right(self, _):
        self._move("right")
    def do_stop(self, _):
        if self.ptz:
            self.ptz.stop()
    def do_zoomin(self, _):
        if self.ptz:
            print("🔍", "OK" if self.ptz.zoom("in") else "FAIL")
    def do_zoomout(self, _):
        if self.ptz:
            print("🔎", "OK" if self.ptz.zoom("out") else "FAIL")

    def _move(self, direction: str):
        if not self.ptz:
            print("请先 login 并 select 摄像头")
            return
        self.ptz.move(direction)

    # ── 直播流 ──────────────────────────────────────
    def do_live(self, _):
        if not self.auth or not self.cam:
            print("请先 login 并 select 摄像头")
            return
        url = get_live_url(self.auth, self.cam)
        if not url:
            return
        print(f"🌐 直播流: {url}")
        print("用 ffplay / vlc 播放, 或用 live_ffplay 命令")
        self._url = url

    def do_live_ffplay(self, _):
        url = getattr(self, "_url", None) or get_live_url(self.auth, self.cam)
        if not url:
            return
        print("🎬 启动 ffplay...")
        subprocess.Popen(["ffplay", "-window_title", self.cam.mac_name, url])

    def do_keep_alive(self, arg: str):
        if not self.auth or not self.cam:
            print("请先选择摄像头")
            return
        interval = int(arg) if arg.strip() else 20
        self._stop_keep_alive.clear()

        def _loop():
            while not self._stop_keep_alive.is_set():
                try:
                    keep_alive(self.auth, self.cam)
                except Exception as e:
                    print(f"保活异常: {e}")
                self._stop_keep_alive.wait(interval)

        self._keep_alive_task = threading.Thread(target=_loop, daemon=True)
        self._keep_alive_task.start()
        print(f"🔄 保活任务已启动 (间隔 {interval}s)")

    def do_no_keep_alive(self, _):
        self._stop_keep_alive.set()
        print("🛑 保活任务已停止")

    # ── 信息 ────────────────────────────────────────
    def do_info(self, _):
        if not self.auth or not self.cam:
            print("请先选择摄像头")
            return
        info = get_device_info(self.auth, self.cam)
        for k, v in info.items():
            print(f"  {k}: {v}")

    def do_snap(self, arg):
        if not self.auth or not self.cam:
            print("请先选择摄像头")
            return
        path = arg.strip() or "/tmp/camera_snap.jpg"
        result = take_snapshot(self.auth, self.cam, path)
        if result:
            import os
            print(f"📸 截图已保存: {result} ({os.path.getsize(result)} bytes)")

    def do_snapshow(self, arg):
        """拍照并用系统图片查看器打开"""
        if not self.auth or not self.cam:
            print("请先选择摄像头")
            return
        path = arg.strip() or "/tmp/camera_snap.jpg"
        result = take_snapshot(self.auth, self.cam, path)
        if not result:
            return
        print(f"📸 截图已保存: {result} ({os.path.getsize(result)} bytes)")
        self._open_with_viewer(result)

    @staticmethod
    def _open_with_viewer(filepath):
        system = platform.system()
        try:
            if system == "Darwin":
                subprocess.Popen(["open", filepath])
            elif system == "Linux":
                subprocess.Popen(["xdg-open", filepath])
            elif system == "Windows":
                os.startfile(filepath)
            print(f"🖼️ 正在打开图片...")
        except Exception as e:
            print(f"⚠️ 无法打开系统查看器: {e}")

    # ── 音频 ────────────────────────────────────────
    def do_live_audio(self, _):
        """播放摄像头的实时音频 (监听/拾音)"""
        if not self.auth or not self.cam:
            print("请先登录并选择摄像头")
            return
        flv_url = get_live_url(self.auth, self.cam)
        if not flv_url:
            return
        if audio.check_audio_in_flv(flv_url):
            print("🔊 从 FLV 流播放音频...")
            self._audio_proc = audio.play_flv_audio(flv_url)
        else:
            print("🔊 从 RTSP 流播放音频...")
            self._audio_proc = audio.play_rtsp_audio("rtsp://localhost:8554/camera")

    def do_intercom(self, _):
        """开始对讲: 采集麦克风发送给摄像头"""
        if self._intercom_proc:
            print("⚠️ 对讲已在运行中, 先 stop_intercom")
            return
        print("🎤 开始对讲 (麦克风 → 摄像头)...")
        self._intercom_proc = audio.start_mic_capture()
        print("   对讲已启动, 输入 stop_intercom 停止")

    def do_stop_intercom(self, _):
        """停止对讲"""
        if self._intercom_proc:
            ret = audio.stop_audio(self._intercom_proc)
            self._intercom_proc = None
            print(f"🔇 对讲已停止 (exit code: {ret})")
        else:
            print("⚠️ 对讲未在运行")

    # ── ONVIF 服务 ─────────────────────────────────
    def do_onvif(self, _):
        if not self.auth or not self.cam:
            print("请先选择摄像头")
            return
        onvif.STREAM_URL = get_live_url(self.auth, self.cam)
        onvif.SNAPSHOT_URL = lambda: get_live_url(self.auth, self.cam)
        onvif.PTZ_CONTROLLER = self.ptz
        if not onvif.STREAM_URL:
            print("❌ 无法获取直播流")
            return

        onvif.start_rtsp_relay(onvif.STREAM_URL)
        mode = get_mode()

        onvif._onvif_ready.clear()
        threading.Thread(target=self._start_onvif_server, daemon=True).start()
        onvif._onvif_ready.wait(timeout=5)

        actual_port = onvif.ONVIF_PORT
        print("🟢 ONVIF 服务已启动")
        if mode == "rtsp":
            print(f"   RTSP:  rtsp://192.168.1.138:8554/camera")
            print(f"   音频:  拾音 live_audio | 对讲 intercom")
        else:
            print(f"   MJPEG: http://192.168.1.138:8555/stream (⚠️ MediaMTX 未运行, 音频不可用)")
        print(f"   ONVIF: http://192.168.1.138:{actual_port}/onvif/device_service")
        print(f"   发现:  局域网 ONVIF 客户端可自动发现")

    def _start_onvif_server(self):
        threading.Thread(target=onvif.start_onvif_server, daemon=True).start()
        onvif._onvif_ready.wait(timeout=5)
        threading.Thread(target=lambda: onvif.discovery_run(
            onvif.UUID_URN, onvif.SCOPES, onvif.HOST_IP, onvif.ONVIF_PORT
        ), daemon=True).start()

    def do_probe(self, _):
        pass

    def do_help(self, arg):
        if arg:
            cmd.Cmd.do_help(self, arg)
            return
        print("""
╔══════════════════════════════════════════════╗
║   CMCC V31S 云台控制                         ║
╚══════════════════════════════════════════════╝

  🔑 登录
    login <手机号> <密码>    登录和家亲账号
    select <编号>            选择摄像头

  🎥 视频
    live                     获取直播流地址
    live_ffplay              用 ffplay 播放直播
    snap [路径]              截图保存
    snapshow [路径]          截图并打开系统查看器

  🔊 音频
    live_audio               播放摄像头实时音频 (监听)
    intercom                 开始对讲 (麦克风→摄像头)
    stop_intercom            停止对讲

  🕹️  云台 (PTZ)
    up / down / left / right  方向控制
    stop                      停止移动
    zoomin / zoomout          变倍

  🌐 ONVIF 服务
    onvif                     启动 ONVIF 模拟服务
    keep_alive [秒]           启动保活任务
    no_keep_alive             停止保活任务

  ℹ️  信息
    info                      设备信息
    help [命令]               帮助

  🚪 退出
    exit / quit / Ctrl+D      退出
""")

    # ── 辅助 ────────────────────────────────────────
    def do_exit(self, _):
        self._stop_keep_alive.set()
        if self._intercom_proc:
            audio.stop_audio(self._intercom_proc)
        if self._audio_proc:
            audio.stop_audio(self._audio_proc)
        print("👋 Bye")
        return True

    def do_quit(self, _):
        return self.do_exit(_)

    do_EOF = do_exit


def main():
    if len(sys.argv) >= 3:
        console = CameraConsole()
        console.do_login(f"{sys.argv[1]} {sys.argv[2]}")
        console.cmdloop()
    else:
        CameraConsole().cmdloop()


if __name__ == "__main__":
    main()
