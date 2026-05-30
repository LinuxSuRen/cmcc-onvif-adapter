"""和家亲 CMCC V31S 摄像头 - 交互式云台控制 Demo"""

import cmd
import sys
import threading
import time
import subprocess

from auth import HJQAuth
from stream import get_live_url, get_device_info, keep_alive, take_snapshot
from ptz import PTZController
import onvif


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

    def do_onvif(self, _):
        if not self.auth or not self.cam:
            print("请先选择摄像头")
            return
        import threading
        onvif.STREAM_URL = get_live_url(self.auth, self.cam)
        onvif.PTZ_CONTROLLER = self.ptz
        if not onvif.STREAM_URL:
            print("❌ 无法获取直播流")
            return

        threading.Thread(target=self._start_onvif, daemon=True).start()
        print("🟢 ONVIF 服务已启动")
        print(f"   MJPEG: http://192.168.1.138:8555/stream")
        print(f"   ONVIF: http://192.168.1.138:8089/onvif/device_service")
        print(f"   发现: 局域网 ONVIF 客户端可自动发现")

    def _start_onvif(self):
        import threading
        onvif.start_rtsp_relay(onvif.STREAM_URL)
        threading.Thread(target=lambda: onvif.discovery_run(
            onvif.UUID_URN, onvif.SCOPES, onvif.HOST_IP, onvif.ONVIF_PORT
        ), daemon=True).start()
        onvif.start_onvif_server()

    def do_probe(self, _):
        pass

    # ── 辅助 ────────────────────────────────────────
    def do_exit(self, _):
        self._stop_keep_alive.set()
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
