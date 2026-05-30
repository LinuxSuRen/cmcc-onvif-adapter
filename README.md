# CMCC V31S ONVIF Adapter

将中国移动和家亲 CMCC V31S 云端摄像头暴露为标准 ONVIF 设备。

## 为什么

CMCC V31S 是纯云端摄像头 — 无 RTSP、无 ONVIF、无本地端口。标准 NVR/监控软件无法接入。

此 Adapter 将云端 API 转换为标准 ONVIF 协议：

- ONVIF WS-Discovery 自动发现
- ONVIF PTZ 云台控制
- MJPEG 视频流
- ONVIF Snapshot 截图

## 快速开始

```bash
pip install -r requirements.txt
python3 main.py 手机号 密码
```

## ONVIF 协议栈

| 协议 | 实现 |
|------|------|
| WS-Discovery | UDP 3702 组播 |
| Device Service | GetDeviceInformation, GetServices, GetScopes |
| Media Service | GetProfiles, GetStreamUri, GetSnapshotUri |
| PTZ Service | ContinuousMove, Stop, GetNodes, GetConfigurations |

启动后在局域网任意 ONVIF 客户端中自动发现。

## API

```python
from auth import HJQAuth
from stream import get_live_url, take_snapshot
from ptz import PTZController

auth = HJQAuth("手机号", "密码")
auth.login(); auth.get_video_auth()
cam = auth.get_cameras()[0]

ptz = PTZController(auth, cam)
ptz.move("left")
ptz.move("up")

url = get_live_url(auth, cam)
take_snapshot(auth, cam, "/tmp/snap.jpg")
```

## Docker

```bash
docker compose up -d
```

## 协议逆向

```
PTZ:
GET accessnb.region.video.komect.com:2443/dcs/device/ptzControl
  ?macId=...&action=start&ctrlType=0&direction=1
  direction: 1=上 2=下 3=左 4=右

直播流:
{baseUrl}/dcs/device/getLiveAddress → FLV

鉴权:
base.hjq.komect.com → token → video.komect.com → auth → stream
```

## 致谢

[XiaoMiku01/hass-hjq](https://github.com/XiaoMiku01/hass-hjq) · [cx3Y/hejiaqin](https://github.com/cx3Y/hejiaqin)
