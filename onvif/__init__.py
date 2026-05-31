"""ONVIF Adapter for CMCC V31S"""

import asyncio, hashlib, logging, os, random, socket, struct, subprocess, sys
import threading, time, uuid, xml.etree.ElementTree as ET
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("onvif")

from onvif.discovery import run as discovery_run
from onvif.rtsp_relay import start_rtsp_relay as _relay_start, stop_relay, get_rtsp_url, get_mode

HOST_IP = "192.168.1.138"
ONVIF_PORT = 8089
DEVICE_NAME = "CMCC-V31S"
MANUFACTURER = "CMCC"
MODEL = "V31S"
DEVICE_UUID = str(uuid.uuid4())
SCOPES = ["onvif://www.onvif.org/type/video_encoder",
          "onvif://www.onvif.org/type/audio_encoder",
          "onvif://www.onvif.org/type/ptz",
          "onvif://www.onvif.org/type/audio_output",
          "onvif://www.onvif.org/Profile/Streaming"]
UUID_URN = f"urn:uuid:{DEVICE_UUID}"
PROFILE_TOKEN = "main"
VIDEO_SRC_TOKEN = "vs"
VIDEO_ENC_TOKEN = "ve"
PTZ_NODE_TOKEN = "ptz"
PTZ_CONFIG_TOKEN = "ptzcfg"
AUDIO_SRC_TOKEN = "as"
AUDIO_ENC_TOKEN = "ae"
AUDIO_OUTPUT_TOKEN = "spk"
RTSP_PORT = 8554
STREAM_URL = None
SNAPSHOT_URL = None  # static URL string, or callable returning a fresh URL
_snapshot_cache = b""
_snapshot_lock = threading.Lock()
PTZ_CONTROLLER = None


def _get_snapshot_url():
    """Resolve SNAPSHOT_URL: callable or static string."""
    if SNAPSHOT_URL is None:
        return None
    if callable(SNAPSHOT_URL):
        return SNAPSHOT_URL()
    return SNAPSHOT_URL
_onvif_ready = threading.Event()


def soap_response(body):
    return ('<?xml version="1.0" encoding="utf-8"?>'
            '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope"'
            ' xmlns:tds="http://www.onvif.org/ver10/device/wsdl"'
            ' xmlns:trt="http://www.onvif.org/ver10/media/wsdl"'
            ' xmlns:tr2="http://www.onvif.org/ver20/media/wsdl"'
            ' xmlns:tdio="http://www.onvif.org/ver10/deviceIO/wsdl"'
            ' xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl"'
            ' xmlns:tt="http://www.onvif.org/ver10/schema">'
            f'<SOAP-ENV:Body>{body}</SOAP-ENV:Body>'
            '</SOAP-ENV:Envelope>').encode()


class ONVIFHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", errors="ignore")
        action = self.headers.get("SOAPAction", "").strip('"')
        op = action.split("/")[-1] if action else ""
        log.debug(op)
        resp = self._handle(op, body)
        self.send_response(200)
        self.send_header("Content-Type", "application/soap+xml; charset=utf-8")
        self.send_header("Content-Length", len(resp))
        self.end_headers()
        self.wfile.write(resp)

    def do_GET(self):
        if self.path == "/snapshot.jpg" and _snapshot_cache:
            with _snapshot_lock:
                data = _snapshot_cache
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", len(data))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/xml")
        self.end_headers()
        self.wfile.write(b"<Envelope/>")

    def _handle(self, op, body):
        h = {
            "GetServices": lambda: soap_response(
                f"<tds:GetServicesResponse>"
                f'<tds:Service><tds:Namespace>http://www.onvif.org/ver10/device/wsdl</tds:Namespace>'
                f'<tds:XAddr>http://{HOST_IP}:{ONVIF_PORT}/onvif/device_service</tds:XAddr>'
                f'<tds:Version><tt:Major>2</tt:Major><tt:Minor>4</tt:Minor></tds:Version>'
                f"</tds:Service>"
                f'<tds:Service><tds:Namespace>http://www.onvif.org/ver10/media/wsdl</tds:Namespace>'
                f'<tds:XAddr>http://{HOST_IP}:{ONVIF_PORT}/onvif/device_service</tds:XAddr>'
                f'<tds:Version><tt:Major>2</tt:Major><tt:Minor>4</tt:Minor></tds:Version>'
                f"</tds:Service>"
                f'<tds:Service><tds:Namespace>http://www.onvif.org/ver20/ptz/wsdl</tds:Namespace>'
                f'<tds:XAddr>http://{HOST_IP}:{ONVIF_PORT}/onvif/device_service</tds:XAddr>'
                f'<tds:Version><tt:Major>2</tt:Major><tt:Minor>4</tt:Minor></tds:Version>'
                f"</tds:Service>"
                f'<tds:Service><tds:Namespace>http://www.onvif.org/ver10/deviceIO/wsdl</tds:Namespace>'
                f'<tds:XAddr>http://{HOST_IP}:{ONVIF_PORT}/onvif/device_service</tds:XAddr>'
                f'<tds:Version><tt:Major>2</tt:Major><tt:Minor>4</tt:Minor></tds:Version>'
                f"</tds:Service></tds:GetServicesResponse>"
            ),
            "GetServiceCapabilities": lambda: soap_response("<tds:GetServiceCapabilitiesResponse/>"),
            "GetCapabilities": lambda: soap_response("<tds:GetCapabilitiesResponse/>"),
            "GetDeviceInformation": lambda: soap_response(
                f"<tds:GetDeviceInformationResponse>"
                f"<tds:Manufacturer>{MANUFACTURER}</tds:Manufacturer>"
                f"<tds:Model>{MODEL}</tds:Model>"
                f"<tds:FirmwareVersion>1.0</tds:FirmwareVersion>"
                f"<tds:SerialNumber>{DEVICE_UUID[:8]}</tds:SerialNumber>"
                f"<tds:HardwareId>v1</tds:HardwareId>"
                f"</tds:GetDeviceInformationResponse>"
            ),
            "GetSystemDateAndTime": lambda: soap_response("<tds:GetSystemDateAndTimeResponse/>"),
            "GetNetworkInterfaces": lambda: soap_response("<tds:GetNetworkInterfacesResponse/>"),
            "GetScopes": lambda: soap_response(
                "<tds:GetScopesResponse>" + "".join(f"<tds:Scopes>{s}</tds:Scopes>" for s in SCOPES) + "</tds:GetScopesResponse>"
            ),
            "GetProfiles": lambda: soap_response(
                f'<trt:GetProfilesResponse><trt:Profiles token="{PROFILE_TOKEN}" fixed="true">'
                f"<tt:Name>Main</tt:Name>"
                f'<tt:VideoSourceConfiguration token="{VIDEO_SRC_TOKEN}"><tt:Name>VS</tt:Name>'
                f'<tt:SourceToken>{VIDEO_SRC_TOKEN}</tt:SourceToken>'
                f'<tt:Bounds x="0" y="0" width="1920" height="1080"/></tt:VideoSourceConfiguration>'
                f'<tt:VideoEncoderConfiguration token="{VIDEO_ENC_TOKEN}"><tt:Name>H264</tt:Name>'
                f'<tt:Encoding>H264</tt:Encoding>'
                f'<tt:Resolution><tt:Width>1920</tt:Width><tt:Height>1080</tt:Height></tt:Resolution>'
                f'<tt:Quality>10</tt:Quality></tt:VideoEncoderConfiguration>'
                f'<tt:PTZConfiguration token="{PTZ_CONFIG_TOKEN}"><tt:Name>PTZ</tt:Name>'
                f'<tt:NodeToken>{PTZ_NODE_TOKEN}</tt:NodeToken></tt:PTZConfiguration>'
                f'<tt:AudioSourceConfiguration token="{AUDIO_SRC_TOKEN}"><tt:Name>Mic</tt:Name>'
                f'<tt:SourceToken>{AUDIO_SRC_TOKEN}</tt:SourceToken>'
                f"</tt:AudioSourceConfiguration>"
                f'<tt:AudioEncoderConfiguration token="{AUDIO_ENC_TOKEN}"><tt:Name>G711</tt:Name>'
                f'<tt:Encoding>PCMU</tt:Encoding>'
                f'<tt:Bitrate>64</tt:Bitrate>'
                f'<tt:SampleRate>8000</tt:SampleRate>'
                f'<tt:SessionTimeout>PT5S</tt:SessionTimeout>'
                f"</tt:AudioEncoderConfiguration>"
                f"</trt:Profiles></trt:GetProfilesResponse>"
            ),
            "GetVideoSources": lambda: soap_response(
                f'<trt:GetVideoSourcesResponse><trt:VideoSources token="{VIDEO_SRC_TOKEN}">'
                f'<tt:Framerate>30</tt:Framerate>'
                f'<tt:Resolution><tt:Width>1920</tt:Width><tt:Height>1080</tt:Height></tt:Resolution>'
                f"</trt:VideoSources></trt:GetVideoSourcesResponse>"
            ),
            "GetStreamUri": lambda: soap_response(
                f'<trt:GetStreamUriResponse><trt:MediaUri>'
                f'<tt:Uri>rtsp://{HOST_IP}:{RTSP_PORT}/camera</tt:Uri>'
                f'<tt:InvalidAfterConnect>false</tt:InvalidAfterConnect>'
                f'<tt:InvalidAfterReboot>false</tt:InvalidAfterReboot>'
                f'<tt:Timeout>PT0S</tt:Timeout></trt:MediaUri></trt:GetStreamUriResponse>'
            ),
            "GetSnapshotUri": lambda: soap_response(
                f'<trt:GetSnapshotUriResponse><trt:MediaUri>'
                f'<tt:Uri>http://{HOST_IP}:{ONVIF_PORT}/snapshot.jpg</tt:Uri>'
                f'</trt:MediaUri></trt:GetSnapshotUriResponse>'
            ),
            "GetNodes": lambda: soap_response(
                f'<tptz:GetNodesResponse><tptz:PTZNode token="{PTZ_NODE_TOKEN}" FixedHomePosition="false">'
                f"<tt:Name>PTZ</tt:Name>"
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
            ),
            "GetConfigurations": lambda: soap_response(
                f'<tptz:GetConfigurationsResponse><tptz:PTZConfiguration token="{PTZ_CONFIG_TOKEN}">'
                f"<tt:Name>Default</tt:Name><tt:NodeToken>{PTZ_NODE_TOKEN}</tt:NodeToken>"
                f"<tt:DefaultContinuousPanTiltVelocitySpace>"
                f"http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace"
                f"</tt:DefaultContinuousPanTiltVelocitySpace>"
                f"<tt:DefaultPTZSpeed><tt:PanTilt x=\"0.5\" y=\"0.5\"/><tt:Zoom x=\"0.5\"/></tt:DefaultPTZSpeed>"
                f"<tt:DefaultPTZTimeout>PT5S</tt:DefaultPTZTimeout>"
                f"</tptz:PTZConfiguration></tptz:GetConfigurationsResponse>"
            ),
            "GetConfigurationOptions": lambda: soap_response("<tptz:GetConfigurationOptionsResponse/>"),
            "GetPresets": lambda: soap_response("<tptz:GetPresetsResponse/>"),
            "GetStatus": lambda: soap_response(
                "<tptz:GetStatusResponse><tptz:PTZStatus>"
                '<tt:Position><tt:PanTilt x="0" y="0"/><tt:Zoom x="0"/></tt:Position>'
                "</tptz:PTZStatus></tptz:GetStatusResponse>"
            ),
            "ContinuousMove": lambda: self._continuous_move(body),
            "Stop": lambda: self._ptz_stop(),
            "GetAudioSources": lambda: soap_response(
                f'<trt:GetAudioSourcesResponse>'
                f'<trt:AudioSources token="{AUDIO_SRC_TOKEN}">'
                f'<tt:Channels>1</tt:Channels>'
                f"</trt:AudioSources></trt:GetAudioSourcesResponse>"
            ),
            "GetAudioEncoderConfigurations": lambda: soap_response(
                f'<trt:GetAudioEncoderConfigurationsResponse>'
                f'<trt:Configurations token="{AUDIO_ENC_TOKEN}"><tt:Name>G711</tt:Name>'
                f'<tt:Encoding>PCMU</tt:Encoding>'
                f'<tt:Bitrate>64</tt:Bitrate>'
                f'<tt:SampleRate>8000</tt:SampleRate>'
                f"</trt:Configurations></trt:GetAudioEncoderConfigurationsResponse>"
            ),
            "GetAudioSourceConfiguration": lambda: soap_response(
                f'<trt:GetAudioSourceConfigurationResponse>'
                f'<trt:Configurations token="{AUDIO_SRC_TOKEN}"><tt:Name>Mic</tt:Name>'
                f'<tt:SourceToken>{AUDIO_SRC_TOKEN}</tt:SourceToken>'
                f"</trt:Configurations></trt:GetAudioSourceConfigurationResponse>"
            ),
            "GetAudioEncoderConfiguration": lambda: soap_response(
                f'<trt:GetAudioEncoderConfigurationResponse>'
                f'<trt:Configurations token="{AUDIO_ENC_TOKEN}"><tt:Name>G711</tt:Name>'
                f'<tt:Encoding>PCMU</tt:Encoding>'
                f'<tt:Bitrate>64</tt:Bitrate>'
                f'<tt:SampleRate>8000</tt:SampleRate>'
                f"</trt:Configurations></trt:GetAudioEncoderConfigurationResponse>"
            ),
            "GetAudioOutputs": lambda: soap_response(
                f'<tdio:GetAudioOutputsResponse>'
                f'<tdio:AudioOutputs token="{AUDIO_OUTPUT_TOKEN}">'
                f"</tdio:AudioOutputs></tdio:GetAudioOutputsResponse>"
            ),
            "GetAudioOutputConfiguration": lambda: soap_response(
                f'<tdio:GetAudioOutputConfigurationResponse>'
                f'<tdio:Configurations token="{AUDIO_OUTPUT_TOKEN}"><tt:Name>Speaker</tt:Name>'
                f'<tt:OutputLevel>50</tt:OutputLevel>'
                f"</tdio:Configurations></tdio:GetAudioOutputConfigurationResponse>"
            ),
            "GetCompatibleAudioEncoderConfigurations": lambda: soap_response(
                f'<trt:GetCompatibleAudioEncoderConfigurationsResponse>'
                f'<trt:Configurations token="{AUDIO_ENC_TOKEN}"><tt:Name>G711</tt:Name>'
                f'<tt:Encoding>PCMU</tt:Encoding>'
                f'<tt:Bitrate>64</tt:Bitrate>'
                f'<tt:SampleRate>8000</tt:SampleRate>'
                f"</trt:Configurations></trt:GetCompatibleAudioEncoderConfigurationsResponse>"
            ),
            "GetCompatibleAudioSourceConfigurations": lambda: soap_response(
                f'<trt:GetCompatibleAudioSourceConfigurationsResponse>'
                f'<trt:Configurations token="{AUDIO_SRC_TOKEN}"><tt:Name>Mic</tt:Name>'
                f'<tt:SourceToken>{AUDIO_SRC_TOKEN}</tt:SourceToken>'
                f"</trt:Configurations></trt:GetCompatibleAudioSourceConfigurationsResponse>"
            ),
        }
        handler = h.get(op, lambda: soap_response(f"<Response/>"))
        return handler()

    def _continuous_move(self, body):
        if PTZ_CONTROLLER is None:
            return soap_response("<tptz:ContinuousMoveResponse/>")
        try:
            root = ET.fromstring(body)
            ns = {"tt": "http://www.onvif.org/ver10/schema"}
            vel = root.find(".//tt:Velocity", ns)
            if vel is not None:
                pt_elem = vel.find("tt:PanTilt", ns)
                pan = float(pt_elem.get("x", "0")) if pt_elem is not None else 0
                tilt = float(pt_elem.get("y", "0")) if pt_elem is not None else 0
                if abs(pan) > 0.1:
                    threading.Thread(target=lambda: PTZ_CONTROLLER.move("left" if pan < 0 else "right", 800), daemon=True).start()
                elif abs(tilt) > 0.1:
                    threading.Thread(target=lambda: PTZ_CONTROLLER.move("up" if tilt > 0 else "down", 800), daemon=True).start()
        except Exception as e:
            log.error(f"PTZ err: {e}")
        return soap_response("<tptz:ContinuousMoveResponse/>")

    def _ptz_stop(self):
        if PTZ_CONTROLLER:
            threading.Thread(target=PTZ_CONTROLLER.stop, daemon=True).start()
        return soap_response("<tptz:StopResponse/>")


def start_onvif_server(host="0.0.0.0", port=ONVIF_PORT):
    """Start ONVIF SOAP server, trying ports {port}, {port-1}, ... until one works."""
    actual_port = port
    while actual_port >= port - 10:
        try:
            server = HTTPServer((host, actual_port), ONVIFHandler)
            global ONVIF_PORT
            ONVIF_PORT = actual_port
            _onvif_ready.set()
            log.info(f"ONVIF http://{HOST_IP}:{actual_port}/onvif/device_service")
            server.serve_forever()
            return
        except OSError:
            log.warning(f"Port {actual_port} in use, trying {actual_port - 1}")
            actual_port -= 1
    raise OSError(f"No available port in range {port-10}-{port}")


def start_rtsp_relay(flv_url, mjpeg_port=8555):
    _relay_start(flv_url, mjpeg_port)
    mode = get_mode()
    if mode == "rtsp":
        log.info(f"RTSP relay at rtsp://{HOST_IP}:{RTSP_PORT}/camera")
    else:
        log.info(f"MJPEG relay (fallback) at http://{HOST_IP}:{mjpeg_port}/stream — audio/backchannel unavailable")
    if SNAPSHOT_URL:
        threading.Thread(target=_snapshot_refresh_loop, daemon=True).start()


def _snapshot_refresh_loop():
    """Background thread: refresh cached snapshot every 5 seconds."""
    global _snapshot_cache
    log.info("Snapshot cache refresh started")
    fail_count = 0
    while True:
        url = _get_snapshot_url()
        if not url:
            time.sleep(5)
            continue
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", url, "-vframes", "1",
                 "-f", "image2", "pipe:1"],
                capture_output=True, timeout=15)
            if result.returncode == 0 and result.stdout:
                with _snapshot_lock:
                    _snapshot_cache = result.stdout
                if fail_count > 0:
                    log.info(f"Snapshot refresh recovered after {fail_count} failures")
                fail_count = 0
            else:
                fail_count += 1
                stderr = result.stderr.decode(errors="ignore")[-200:] if result.stderr else "no output"
                log.warning(f"Snapshot ffmpeg failed (rc={result.returncode}, #{fail_count}): {stderr}")
        except Exception as e:
            fail_count += 1
            log.warning(f"Snapshot refresh error #{fail_count}: {e}")
        time.sleep(5)
