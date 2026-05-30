# CMCC V31S Camera Controller

中国移动和家亲 CMCC V31S 智能摄像头云台控制工具，基于逆向 API 实现。

## 功能

- 云台控制（上下左右）
- 直播流获取（FLV）
- 截图
- ONVIF 服务（可被 NVR/Blue Iris/Home Assistant 自动发现）
- Docker 支持

## 安装

```bash
pip install -r requirements.txt
```

## 使用

### 交互式控制台

```bash
python3 main.py 手机号 密码
```

| 命令 | 功能 |
|------|------|
| `left` / `right` | 左右转动 |
| `up` / `down` | 上下转动 |
| `stop` | 停止转动 |
| `live` | 获取直播流 URL |
| `live_ffplay` | ffplay 播放 |
| `snap` | 截图保存 |
| `onvif` | 启动 ONVIF 服务 |
| `info` | 设备信息 |
| `exit` | 退出 |

### Python API

```python
from auth import HJQAuth
from stream import get_live_url, take_snapshot
from ptz import PTZController

auth = HJQAuth("手机号", "密码")
auth.login()
auth.get_video_auth()
cam = auth.get_cameras()[0]

# 云台控制
ptz = PTZController(auth, cam)
ptz.move("left")
ptz.move("up")

# 直播流
url = get_live_url(auth, cam)

# 截图
take_snapshot(auth, cam, "/tmp/snap.jpg")
```

### ONVIF 服务

```bash
python3 main.py 手机号 密码
📷> onvif
```

| 端点 | 地址 |
|------|------|
| ONVIF | `http://192.168.1.138:8089/onvif/device_service` |
| MJPEG | `http://192.168.1.138:8555/stream` |

### Docker

```bash
docker compose up -d
```

## 协议

CMCC V31S 使用和家亲云端 API，通过抓包逆向获得：

```
GET https://accessnb.region.video.komect.com:2443/dcs/device/ptzControl
  ?macId=...
  &action=start
  &ctrlType=0
  &direction=1     # 1=上 2=下 3=左 4=右
  &time=...
  &nonce=...
  &sign=MD5(sorted_params + path + secret)

直播流:
{baseUrl}/dcs/device/getLiveAddress → FLV URL
```

## 文件结构

```
cmcc-camera-demo/
├── auth.py          # 登录鉴权
├── stream.py        # 直播流 + 截图
├── ptz.py           # 云台控制
├── main.py          # 交互式控制台
├── onvif/
│   └── __init__.py  # ONVIF 服务端
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 致谢

- [XiaoMiku01/hass-hjq](https://github.com/XiaoMiku01/hass-hjq) - 和家亲 HA 集成
- [cx3Y/hejiaqin](https://github.com/cx3Y/hejiaqin) - Andlink 设备控制 API
