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

### 方法：中间人代理抓包

CMCC V31S 不开放本地端口，PTZ 控制协议无法从源码或文档中找到。
通过 **mitmproxy** 对和家亲 App 进行 HTTPS 中间人代理，捕获 App 与云端之间的完整通信。

```bash
# 1. 启动代理（Mac）
mitmdump -p 8080 --ssl-insecure -s ws_dump.py

# 2. 手机配置 WiFi 代理 → Mac IP:8080
# 3. 手机安装 mitmproxy CA 证书（浏览器打开 mitm.it）
# 4. 打开和家亲 App → 操作云台方向
# 5. 从代理日志提取 PTZ 请求
```

### 抓到的 PTZ API

```
GET https://accessnb.region.video.komect.com:2443/dcs/device/ptzControl
  ?macId=3169200129111116783201649
  &action=start          ← 开始转动
  &ctrlType=0            ← 控制类型（0=云台）
  &direction=3           ← 1=上 2=下 3=左 4=右
  &time=...
  &nonce=...
  &sign=MD5(sorted_params + path + secret)
```

缺失任意参数均返回 400 或"参数错误"——`action` 和 `ctrlType` 两个字段是抓包前不可能猜到的。

### 鉴权链

```
登录 (base.hjq.komect.com) → hjq_token + passId
  → 视频鉴权 (video.komect.com) → video_token
    → 设备列表 → jwtoken
      → DCS API 调用
```

### 抓包辅助脚本

`ws_dump.py` — mitmproxy addon，用于捕获 WebSocket 消息内容（xlink.hjq.komect.com 的设备控制通道）。

## 致谢

[XiaoMiku01/hass-hjq](https://github.com/XiaoMiku01/hass-hjq) · [cx3Y/hejiaqin](https://github.com/cx3Y/hejiaqin)
