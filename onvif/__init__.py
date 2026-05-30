"""ONVIF 服务 - 将 CMCC V31S 暴露为标准 ONVIF 摄像头

支持:
- WS-Discovery 自动发现
- PTZ 云台控制
- RTSP 直播流 (via go2rtc)
- 截图

启动: python3 onvif_server.py
"""

import asyncio
import hashlib
import logging
import os
import random
import socket
import struct
import subprocess
import sys
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("onvif")

# ── 配置 ──────────────────────────────────────────
HOST_IP = "192.168.1.138"
ONVIF_PORT = 8089
RTSP_PORT = 8554
DEVICE_NAME = "CMCC-V31S"
MANUFACTURER = "CMCC"
MODEL = "V31S"
DEVICE_UUID = str(uuid.uuid4())
SCOPES = ["onvif://www.onvif.org/type/video_encoder",
          "onvif://www.onvif.org/type/ptz",
          "onvif://www.onvif.org/Profile/Streaming"]

# 直播流 URL (由 main.py 设置)
STREAM_URL = None
# PTZ 控制器 (由 main.py 设置)
PTZ_CONTROLLER = None

# ── WS-Discovery ──────────────────────────────────
MULTICAST_ADDR = "239.255.255.250"
MULTICAST_PORT = 3702
UUID_URN = f"urn:uuid:{DEVICE_UUID}"

WS_DISCOVERY_RESPONSE = """<?xml version="1.0" encoding="utf-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope"
                   xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
                   xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
                   xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <SOAP-ENV:Header>
    <wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/ProbeMatches</wsa:Action>
    <wsa:RelatesTo>{relates_to}</wsa:RelatesTo>
    <wsa:To>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:To>
  </SOAP-ENV:Header>
  <SOAP-ENV:Body>
    <d:ProbeMatches>
      <d:ProbeMatch>
        <wsa:EndpointReference><wsa:Address>{uuid}</wsa:Address></wsa:EndpointReference>
        <d:Types>dn:NetworkVideoTransmitter</d:Types>
        <d:Scopes>{scopes}</d:Scopes>
        <d:XAddrs>http://{host}:{port}/onvif/device_service</d:XAddrs>
        <d:MetadataVersion>1</d:MetadataVersion>
      </d:ProbeMatch>
    </d:ProbeMatches>
  </SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""


def ws_discovery_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", MULTICAST_PORT))
    mreq = struct.pack("4s4s", socket.inet_aton(MULTICAST_ADDR), socket.inet_aton("0.0.0.0"))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    sock.settimeout(2)
    log.info(f"WS-Discovery listening on {MULTICAST_PORT}")

    while True:
        try:
            data, addr = sock.recvfrom(4096)
            text = data.decode("utf-8", errors="ignore")
            if "Probe" in text and "NetworkVideoTransmitter" not in text:
                continue

            # Extract MessageID
            msg_id = "unknown"
            for line in text.split("\r\n"):
                if "MessageID" in line:
                    msg_id = line.split(":")[-1].strip()
                    break

            resp = WS_DISCOVERY_RESPONSE.format(
                relates_to=msg_id,
                uuid=UUID_URN,
                scopes=" ".join(SCOPES),
                host=HOST_IP,
                port=ONVIF_PORT,
            )
            sock.sendto(resp.encode(), addr)
            log.info(f"ProbeMatch sent to {addr}")
        except socket.timeout:
            continue
        except Exception as e:
            log.error(f"Discovery error: {e}")


# ── ONVIF SOAP Server ─────────────────────────────
ONVIF_NS = {
    "tds": "http://www.onvif.org/ver10/device/wsdl",
    "trt": "http://www.onvif.org/ver10/media/wsdl",
    "tptz": "http://www.onvif.org/ver20/ptz/wsdl",
    "tt": "http://www.onvif.org/ver10/schema",
}

PROFILE_TOKEN = "main_profile"
VIDEO_SRC_TOKEN = "video_src"
VIDEO_ENC_TOKEN = "video_enc"
PTZ_NODE_TOKEN = "ptz_node"
PTZ_CONFIG_TOKEN = "ptz_config"
AUDIO_SRC_TOKEN = "audio_src"

SOAP_ENVELOPE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope"'
    ' xmlns:tds="http://www.onvif.org/ver10/device/wsdl"'
    ' xmlns:trt="http://www.onvif.org/ver10/media/wsdl"'
    ' xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl"'
    ' xmlns:tt="http://www.onvif.org/ver10/schema">'
    "<SOAP-ENV:Body>{body}</SOAP-ENV:Body>"
    "</SOAP-ENV:Envelope>"
)


def soap_response(body):
    return SOAP_ENVELOPE.format(body=body).encode()


class ONVIFHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.debug(fmt % args)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", errors="ignore")
        action = self.headers.get("SOAPAction", "").strip('"')

        resp = self._handle(action, body)
        self.send_response(200)
        self.send_header("Content-Type", "application/soap+xml; charset=utf-8")
        self.send_header("Content-Length", len(resp))
        self.end_headers()
        self.wfile.write(resp)

    def do_GET(self):
        if self.path == "/onvif/device_service":
            self.send_response(200)
            self.send_header("Content-Type", "text/xml")
            self.end_headers()
            self.wfile.write(b"<Envelope/>")
        else:
            self.send_response(404)
            self.end_headers()

    def _handle(self, action, body):
        log.info(f"SOAP: {action.split('/')[-1] if action else '???'}")

        handlers = {
            "GetServices": self._get_services,
            "GetServiceCapabilities": self._get_service_capabilities,
            "GetDeviceInformation": self._get_device_info,
            "GetSystemDateAndTime": self._get_time,
            "GetNetworkInterfaces": self._get_network,
            "GetScopes": self._get_scopes,
            "GetCapabilities": self._get_capabilities,
            "GetProfiles": self._get_profiles,
            "GetProfile": self._get_profile,
            "GetStreamUri": self._get_stream_uri,
            "GetVideoSources": self._get_video_sources,
            "GetVideoSourceConfiguration": self._get_video_src_config,
            "GetVideoEncoderConfiguration": self._get_video_enc_config,
            "GetSnapshotUri": self._get_snapshot_uri,
            "GetNodes": self._get_ptz_nodes,
            "GetNode": self._get_ptz_node,
            "GetConfigurations": self._get_ptz_configs,
            "GetConfiguration": self._get_ptz_config,
            "GetConfigurationOptions": self._get_ptz_config_options,
            "ContinuousMove": self._continuous_move,
            "Stop": self._ptz_stop,
            "GetStatus": self._ptz_status,
            "GetPresets": self._get_presets,
        }

        op = action.split("/")[-1] if action else ""
        handler = handlers.get(op)
        if handler:
            return handler(body)
        return soap_response(f"<tds:{op}Response/>")

    def _get_device_info(self, body):
        return soap_response(
            f"<tds:GetDeviceInformationResponse>"
            f"<tds:Manufacturer>{MANUFACTURER}</tds:Manufacturer>"
            f"<tds:Model>{MODEL}</tds:Model>"
            f"<tds:FirmwareVersion>1.0</tds:FirmwareVersion>"
            f"<tds:SerialNumber>{DEVICE_UUID[:8]}</tds:SerialNumber>"
            f"<tds:HardwareId>v1</tds:HardwareId>"
            f"</tds:GetDeviceInformationResponse>"
        )

    def _get_services(self, body):
        return soap_response(
            "<tds:GetServicesResponse><tds:Service>"
            "<tds:Namespace>http://www.onvif.org/ver10/device/wsdl</tds:Namespace>"
            f"<tds:XAddr>http://{HOST_IP}:{ONVIF_PORT}/onvif/device_service</tds:XAddr>"
            "<tds:Version><tt:Major>2</tt:Major><tt:Minor>4</tt:Minor></tds:Version>"
            "</tds:Service><tds:Service>"
            "<tds:Namespace>http://www.onvif.org/ver10/media/wsdl</tds:Namespace>"
            f"<tds:XAddr>http://{HOST_IP}:{ONVIF_PORT}/onvif/device_service</tds:XAddr>"
            "<tds:Version><tt:Major>2</tt:Major><tt:Minor>4</tt:Minor></tds:Version>"
            "</tds:Service><tds:Service>"
            "<tds:Namespace>http://www.onvif.org/ver20/ptz/wsdl</tds:Namespace>"
            f"<tds:XAddr>http://{HOST_IP}:{ONVIF_PORT}/onvif/device_service</tds:XAddr>"
            "<tds:Version><tt:Major>2</tt:Major><tt:Minor>4</tt:Minor></tds:Version>"
            "</tds:Service></tds:GetServicesResponse>"
        )

    _get_service_capabilities = _get_services
    _get_capabilities = _get_services
    _get_time = lambda s, b: soap_response("<tds:GetSystemDateAndTimeResponse/>")
    _get_network = lambda s, b: soap_response("<tds:GetNetworkInterfacesResponse/>")
    _get_scopes = lambda s, b: soap_response(
        "<tds:GetScopesResponse>"
        + "".join(f"<tds:Scopes>{s}</tds:Scopes>" for s in SCOPES)
        + "</tds:GetScopesResponse>"
    )

    def _get_profiles(self, body):
        return soap_response(
            f"<trt:GetProfilesResponse>"
            f'<trt:Profiles token="{PROFILE_TOKEN}" fixed="true">'
            f"<tt:Name>Main</tt:Name>"
            f'<tt:VideoSourceConfiguration token="{VIDEO_SRC_TOKEN}">'
            f"<tt:Name>VideoSrc</tt:Name>"
            f"<tt:SourceToken>{VIDEO_SRC_TOKEN}</tt:SourceToken>"
            f"<tt:Bounds x=\"0\" y=\"0\" width=\"1920\" height=\"1080\"/>"
            f"</tt:VideoSourceConfiguration>"
            f'<tt:VideoEncoderConfiguration token="{VIDEO_ENC_TOKEN}">'
            f"<tt:Name>H264</tt:Name>"
            f"<tt:Encoding>H264</tt:Encoding>"
            f"<tt:Resolution><tt:Width>1920</tt:Width><tt:Height>1080</tt:Height></tt:Resolution>"
            f"<tt:Quality>10</tt:Quality>"
            f"</tt:VideoEncoderConfiguration>"
            f'<tt:PTZConfiguration token="{PTZ_CONFIG_TOKEN}">'
            f"<tt:Name>PTZ</tt:Name>"
            f"<tt:NodeToken>{PTZ_NODE_TOKEN}</tt:NodeToken>"
            f"</tt:PTZConfiguration>"
            f"</trt:Profiles>"
            f"</trt:GetProfilesResponse>"
        )

    _get_profile = _get_profiles
    _get_video_sources = lambda s, b: soap_response(
        f'<trt:GetVideoSourcesResponse><trt:VideoSources token="{VIDEO_SRC_TOKEN}">'
        f"<tt:Framerate>30</tt:Framerate>"
        f"<tt:Resolution><tt:Width>1920</tt:Width><tt:Height>1080</tt:Height></tt:Resolution>"
        f"</trt:VideoSources></trt:GetVideoSourcesResponse>"
    )
    _get_video_src_config = lambda s, b: soap_response(
        f'<trt:GetVideoSourceConfigurationResponse>'
        f'<trt:Configuration token="{VIDEO_SRC_TOKEN}">'
        f"<tt:Name>VideoSrc</tt:Name><tt:SourceToken>{VIDEO_SRC_TOKEN}</tt:SourceToken>"
        f"<tt:Bounds x=\"0\" y=\"0\" width=\"1920\" height=\"1080\"/>"
        f"</trt:Configuration></trt:GetVideoSourceConfigurationResponse>"
    )
    _get_video_enc_config = lambda s, b: soap_response(
        f'<trt:GetVideoEncoderConfigurationResponse>'
        f'<trt:Configuration token="{VIDEO_ENC_TOKEN}">'
        f"<tt:Name>H264</tt:Name><tt:Encoding>H264</tt:Encoding>"
        f"<tt:Resolution><tt:Width>1920</tt:Width><tt:Height>1080</tt:Height></tt:Resolution>"
        f"<tt:Quality>10</tt:Quality>"
        f"</trt:Configuration></trt:GetVideoEncoderConfigurationResponse>"
    )

    def _get_stream_uri(self, body):
        uri = f"rtsp://{HOST_IP}:{RTSP_PORT}/cmcc_v31s"
        return soap_response(
            f"<trt:GetStreamUriResponse>"
            f"<trt:MediaUri><tt:Uri>{uri}</tt:Uri>"
            f"<tt:InvalidAfterConnect>false</tt:InvalidAfterConnect>"
            f"<tt:InvalidAfterReboot>false</tt:InvalidAfterReboot>"
            f"<tt:Timeout>PT0S</tt:Timeout></trt:MediaUri>"
            f"</trt:GetStreamUriResponse>"
        )

    def _get_snapshot_uri(self, body):
        uri = f"http://{HOST_IP}:{ONVIF_PORT}/snapshot.jpg"
        return soap_response(
            f"<trt:GetSnapshotUriResponse>"
            f"<trt:MediaUri><tt:Uri>{uri}</tt:Uri></trt:MediaUri>"
            f"</trt:GetSnapshotUriResponse>"
        )

    _get_ptz_nodes = lambda s, b: soap_response(
        f"<tptz:GetNodesResponse>"
        f'<tptz:PTZNode token="{PTZ_NODE_TOKEN}" FixedHomePosition="false">'
        f"<tt:Name>PTZ Node</tt:Name>"
        f"<tt:SupportedPTZSpaces>"
        f"<tt:ContinuousPanTiltVelocitySpace>"
        f"<tt:XRange><tt:Min>-1</tt:Min><tt:Max>1</tt:Max></tt:XRange>"
        f"<tt:YRange><tt:Min>-1</tt:Min><tt:Max>1</tt:Max></tt:YRange>"
        f"</tt:ContinuousPanTiltVelocitySpace>"
        f"<tt:ContinuousZoomVelocitySpace>"
        f"<tt:XRange><tt:Min>-1</tt:Min><tt:Max>1</tt:Max></tt:XRange>"
        f"</tt:ContinuousZoomVelocitySpace>"
        f"</tt:SupportedPTZSpaces>"
        f"<tt:MaximumNumberOfPresets>10</tt:MaximumNumberOfPresets>"
        f"<tt:HomeSupported>true</tt:HomeSupported>"
        f"</tptz:PTZNode></tptz:GetNodesResponse>"
    )
    _get_ptz_node = _get_ptz_nodes

    _get_ptz_configs = lambda s, b: soap_response(
        f"<tptz:GetConfigurationsResponse>"
        f'<tptz:PTZConfiguration token="{PTZ_CONFIG_TOKEN}">'
        f"<tt:Name>Default</tt:Name>"
        f"<tt:NodeToken>{PTZ_NODE_TOKEN}</tt:NodeToken>"
        f"<tt:DefaultContinuousPanTiltVelocitySpace>"
        f"http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace"
        f"</tt:DefaultContinuousPanTiltVelocitySpace>"
        f"<tt:DefaultContinuousZoomVelocitySpace>"
        f"http://www.onvif.org/ver10/tptz/ZoomSpaces/VelocityGenericSpace"
        f"</tt:DefaultContinuousZoomVelocitySpace>"
        f"<tt:DefaultPTZSpeed>"
        f"<tt:PanTilt x=\"0.5\" y=\"0.5\"/><tt:Zoom x=\"0.5\"/>"
        f"</tt:DefaultPTZSpeed>"
        f"<tt:DefaultPTZTimeout>PT5S</tt:DefaultPTZTimeout>"
        f"</tptz:PTZConfiguration></tptz:GetConfigurationsResponse>"
    )
    _get_ptz_config = _get_ptz_configs

    _get_ptz_config_options = lambda s, b: soap_response(
        "<tptz:GetConfigurationOptionsResponse>"
        "<tptz:PTZConfigurationOptions>"
        "<tt:PTZTimeout><tt:Min>PT1S</tt:Min><tt:Max>PT60S</tt:Max></tt:PTZTimeout>"
        "</tptz:PTZConfigurationOptions>"
        "</tptz:GetConfigurationOptionsResponse>"
    )
    _get_presets = lambda s, b: soap_response("<tptz:GetPresetsResponse/>")
    _ptz_status = lambda s, b: soap_response(
        "<tptz:GetStatusResponse>"
        "<tptz:PTZStatus>"
        "<tt:Position><tt:PanTilt x=\"0\" y=\"0\"/><tt:Zoom x=\"0\"/></tt:Position>"
        "</tptz:PTZStatus></tptz:GetStatusResponse>"
    )

    def _continuous_move(self, body):
        """ONVIF ContinuousMove → 云台控制"""
        if PTZ_CONTROLLER is None:
            return soap_response("<tptz:ContinuousMoveResponse/>")

        try:
            root = ET.fromstring(body)
            ns = {"tptz": "http://www.onvif.org/ver20/ptz/wsdl",
                  "tt": "http://www.onvif.org/ver10/schema"}
            vel = root.find(".//tt:Velocity", ns)
            if vel is not None:
                pan_tilt = vel.find("tt:PanTilt", ns)
                zoom = vel.find("tt:Zoom", ns)
                pan = float(pan_tilt.get("x", "0")) if pan_tilt is not None else 0
                tilt = float(pan_tilt.get("y", "0")) if pan_tilt is not None else 0
                z = float(zoom.get("x", "0")) if zoom is not None else 0

                if abs(pan) > 0.1:
                    threading.Thread(target=lambda: PTZ_CONTROLLER.move("left" if pan < 0 else "right", 800), daemon=True).start()
                elif abs(tilt) > 0.1:
                    threading.Thread(target=lambda: PTZ_CONTROLLER.move("up" if tilt > 0 else "down", 800), daemon=True).start()
                elif abs(z) > 0.1:
                    threading.Thread(target=lambda: PTZ_CONTROLLER.zoom("in" if z > 0 else "out", 500), daemon=True).start()
        except Exception as e:
            log.error(f"PTZ parse error: {e}")

        return soap_response("<tptz:ContinuousMoveResponse/>")

    def _ptz_stop(self, body):
        if PTZ_CONTROLLER:
            threading.Thread(target=PTZ_CONTROLLER.stop, daemon=True).start()
        return soap_response("<tptz:StopResponse/>")


# ── Snapshot endpoint ─────────────────────────────
def snapshot_bytes():
    """生成当前截图"""
    if STREAM_URL is None:
        return None
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", STREAM_URL, "-vframes", "1", "-f", "image2", "pipe:1"],
            capture_output=True, timeout=10,
        )
        return result.stdout if result.returncode == 0 else None
    except Exception:
        return None


class SnapshotHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/snapshot.jpg":
            img = snapshot_bytes()
            if img:
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", len(img))
                self.end_headers()
                self.wfile.write(img)
            else:
                self.send_response(503)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()


# ── 启动 ──────────────────────────────────────────
def start_onvif_server(host="0.0.0.0", port=ONVIF_PORT):
    server = HTTPServer((host, port), ONVIFHandler)
    log.info(f"ONVIF SOAP server on http://{HOST_IP}:{port}/onvif/device_service")

    # 也启动 snapshot 服务 (在同一个端口)
    snapshot_server = HTTPServer(("0.0.0.0", port + 1), SnapshotHandler)
    threading.Thread(target=snapshot_server.serve_forever, daemon=True).start()

    server.serve_forever()


def start_rtsp_relay(flv_url, mjpeg_port=8555):
    proc = subprocess.Popen(
        ["ffmpeg", "-re", "-i", flv_url,
         "-c:v", "mjpeg", "-q:v", "5", "-f", "mpjpeg",
         f"http://0.0.0.0:{mjpeg_port}/stream"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    log.info(f"MJPEG relay on http://{HOST_IP}:{mjpeg_port}/stream")
    return proc


def main():
    """独立启动 ONVIF 服务"""
    global STREAM_URL, PTZ_CONTROLLER
    sys.path.insert(0, os.path.dirname(__file__))
    from auth import HJQAuth
    from stream import get_live_url
    from ptz import PTZController

    phone = sys.argv[1] if len(sys.argv) > 1 else None
    pwd = sys.argv[2] if len(sys.argv) > 2 else None
    if not phone:
        phone = input("手机号: ")
        pwd = input("密码: ")

    auth = HJQAuth(phone, pwd)
    auth.login()
    auth.get_video_auth()
    cam = auth.get_cameras()[0]
    PTZ_CONTROLLER = PTZController(auth, cam)
    STREAM_URL = get_live_url(auth, cam)

    if not STREAM_URL:
        log.error("无法获取直播流")
        return

    # 启动 RTSP 转发
    rtsp_proc = start_go2rtc(STREAM_URL)
    time.sleep(2)

    # 启动 WS-Discovery
    threading.Thread(target=ws_discovery_server, daemon=True).start()

    # 启动 ONVIF SOAP
    start_onvif_server()


if __name__ == "__main__":
    main()
