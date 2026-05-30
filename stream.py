"""直播流与设备信息模块"""

from auth import HJQAuth, CameraInfo, make_sign
import requests


def get_live_url(auth: HJQAuth, cam: CameraInfo) -> str | None:
    url = cam.base_url + "/dcs/device/getLiveAddress"
    params = auth.camera_signed_params(cam, url, requestTime=str(int(__import__("time").time() * 1000)))
    r = requests.get(url, params=params, headers=auth.camera_headers(cam))
    try:
        data = r.json()
    except Exception:
        print(f"❌ 获取流地址失败: {r.text[:120]}")
        return None
    if "data" not in data or "flv" not in data["data"]:
        print(f"❌ 未获取到流: {r.text[:120]}")
        return None
    return data["data"]["flv"]


def get_device_info(auth: HJQAuth, cam: CameraInfo) -> dict:
    url = cam.base_url + "/dcs/device/fullInfo"
    params = auth.camera_signed_params(cam, url)
    r = requests.get(url, params=params, headers=auth.camera_headers(cam))
    return r.json().get("data", {})


def keep_alive(auth: HJQAuth, cam: CameraInfo) -> None:
    url = cam.base_url + "/dcs/device/keepOpenLiveAddress"
    params = auth.camera_signed_params(cam, url)
    r = requests.post(url, data=params, headers={**auth.camera_headers(cam), "Content-Type": "application/x-www-form-urlencoded"})
    return r.json()

def take_snapshot(auth, cam, output_path="/tmp/camera_snap.jpg"):
    """从直播流截取一帧"""
    import subprocess, os
    url = get_live_url(auth, cam)
    if not url:
        return None
    subprocess.run(
        ["ffmpeg", "-y", "-i", url, "-vframes", "1", "-f", "image2", output_path],
        capture_output=True, timeout=10,
    )
    return output_path if os.path.exists(output_path) else None
