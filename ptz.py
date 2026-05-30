"""CMCC V31S 云台控制 - DCS ptzControl API (抓包验证)"""

import hashlib
import time as _time
from auth import HJQAuth, CameraInfo

SECRET = "r8rw4d1kjwqgqqto9dwsq3ew0ip2np1b"
PTZ_BASE = "https://accessnb.region.video.komect.com:2443"


def _sign(params, path="/dcs/device/ptzControl"):
    raw = "".join(k + str(params[k]) for k in sorted(params))
    return hashlib.md5((raw + path + SECRET).encode()).hexdigest()


class PTZController:
    DIRECTION = {"up": "1", "down": "2", "left": "4", "right": "3"}

    def __init__(self, auth: HJQAuth, cam: CameraInfo):
        self.auth = auth
        self.cam = cam
        self.url = PTZ_BASE + "/dcs/device/ptzControl"

    def _headers(self):
        return {
            "AppName": "hejiaqin",
            "DeviceId": "abc",
            "Version": "6.11.1",
            "DeviceType": "ANDROID",
            "AuthorizationToken": self.auth.video_token,
            "AuthorizationJwtoken": self.cam.jwtoken,
        }

    def move(self, direction, duration_ms=500):
        import requests
        dv = self.DIRECTION.get(direction, direction)
        ts = str(int(_time.time() * 1000))
        params = {
            "macId": self.cam.mac_id,
            "action": "start",
            "ctrlType": "0",
            "direction": dv,
            "time": ts,
            "nonce": ts + "41411901864",
        }
        params["sign"] = _sign(params)
        r = requests.get(self.url, params=params, headers=self._headers())
        ok = r.json().get("code") == "0"
        if ok:
            _time.sleep(duration_ms / 1000)
            self.stop()
        return ok

    def stop(self):
        import requests
        ts = str(int(_time.time() * 1000))
        params = {
            "macId": self.cam.mac_id,
            "action": "stop",
            "ctrlType": "0",
            "direction": "1",
            "time": ts,
            "nonce": ts + "41411901864",
        }
        params["sign"] = _sign(params)
        r = requests.get(self.url, params=params, headers=self._headers())
        return r.json().get("code") == "0"

    def zoom(self, direction="in", duration_ms=300):
        import requests
        dv = "5" if direction == "in" else "6"
        ts = str(int(_time.time() * 1000))
        params = {
            "macId": self.cam.mac_id, "action": "start", "ctrlType": "0",
            "direction": dv, "time": ts, "nonce": ts + "41411901864",
        }
        params["sign"] = _sign(params)
        r = requests.get(self.url, params=params, headers=self._headers())
        ok = r.json().get("code") == "0"
        if ok:
            _time.sleep(duration_ms / 1000)
            self.stop()
        return ok
