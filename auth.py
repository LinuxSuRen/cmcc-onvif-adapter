"""和家亲云端鉴权模块 - 三层 Token 认证"""

import hashlib
import time
import urllib.parse
from dataclasses import dataclass
from typing import Optional

try:
    import requests
except ImportError:
    raise ImportError("pip install requests")

SECRET_KEY = "r8rw4d1kjwqgqqto9dwsq3ew0ip2np1b"


def _md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()


def make_sign(params: dict, api_url: str) -> str:
    ordered = (k + str(params[k]) for k in sorted(params))
    raw = "".join(ordered) + urllib.parse.urlparse(api_url).path + SECRET_KEY
    return _md5(raw)


@dataclass
class CameraInfo:
    mac_id: str
    mac_name: str
    base_url: str
    jwtoken: str


class HJQAuth:
    def __init__(self, phone: str, password: str):
        self.phone = phone
        self.password = password
        self.hjq_token: Optional[str] = None
        self.pass_id: Optional[str] = None
        self.video_token: Optional[str] = None
        self.session = requests.Session()

    # ── Step 1 ──────────────────────────────────────
    def login(self) -> bool:
        url = "https://base.hjq.komect.com/base/user/passwdLogin"
        body = {
            "virtualAuthdata": _md5(self.password),
            "authType": "10",
            "userAccount": self.phone,
            "authdata": _sha1("fetion.com.cn:" + self.password),
        }
        r = self.session.post(url, json=body, headers={"Content-Type": "application/json"})
        if "Set-Cookie" not in r.headers:
            print(f"❌ 登录失败: {r.text[:120]}")
            return False
        self.hjq_token = r.headers["Set-Cookie"].split("=")[1].split(";")[0]
        self.pass_id = r.json()["data"]["passId"]
        return True

    # ── Step 2 ──────────────────────────────────────
    def get_video_auth(self) -> bool:
        if self.video_token:
            return True
        url = "https://video.komect.com/user/login/loginByHJQToken"
        ts = str(int(time.time() * 1000))
        params = {
            "HJQToken": self.hjq_token,
            "nonce": ts + "abcde",
            "passId": self.pass_id,
            "time": ts,
            "userId": self.phone,
        }
        params["sign"] = make_sign(params, url)
        r = self.session.post(
            url,
            data=params,
            headers={
                "AppName": "hejiaqin", "DeviceId": "abc",
                "DeviceType": "ANDROID",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        data = r.json()
        if "data" not in data or "token" not in data["data"]:
            print(f"❌ 视频鉴权失败: {r.text[:120]}")
            return False
        self.video_token = data["data"]["token"]
        return True

    # ── Step 3 ──────────────────────────────────────
    def get_cameras(self) -> list[CameraInfo]:
        url = "https://video.komect.com/camera/core/api/bind/queryList"
        ts = str(int(time.time() * 1000))
        params = {
            "nonce": ts + "m5kjt", "number": "100", "page": "1",
            "time": ts, "user_id": self.phone,
        }
        params["sign"] = make_sign(params, url)
        r = self.session.get(
            url, params=params,
            headers={
                "AppName": "hejiaqin", "DeviceId": "abc",
                "Version": "6.11.1", "DeviceType": "ANDROID",
                "AuthorizationToken": self.video_token,
            },
        )
        data = r.json()
        if "data" not in data:
            print(f"❌ 获取设备列表失败: {data.get('msg', r.text[:120])}")
            return []
        return [CameraInfo(
            mac_id=c["mac_id"], mac_name=c["mac_name"],
            base_url=c["baseUrl"], jwtoken=c["jwtoken"],
        ) for c in data["data"]]

    def camera_headers(self, cam: CameraInfo) -> dict:
        return {
            "AppName": "hejiaqin", "DeviceId": "abc",
            "Version": "6.11.1", "DeviceType": "ANDROID",
            "AuthorizationToken": self.video_token,
            "AuthorizationJwtoken": cam.jwtoken,
        }

    def camera_signed_params(self, cam: CameraInfo, api_url: str, **extra) -> dict:
        ts = str(int(time.time() * 1000))
        params = {"macId": cam.mac_id, "time": ts, "nonce": ts + "gs08t", **extra}
        params["sign"] = make_sign(params, api_url)
        return params
