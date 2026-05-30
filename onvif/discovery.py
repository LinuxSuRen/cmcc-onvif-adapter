import socket
import struct
import logging
import threading
import re

log = logging.getLogger("onvif.disc")

MCAST = "239.255.255.250"
PORT = 3702
UUID = None
SCOPES = []
HOST_IP = "192.168.1.138"
ONVIF_PORT = 8089

PROBE_MATCH = """<?xml version="1.0" encoding="utf-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope"
                   xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
                   xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
                   xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <SOAP-ENV:Header>
    <wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/ProbeMatches</wsa:Action>
    <wsa:RelatesTo>{relates_to}</wsa:RelatesTo>
    <wsa:To>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:To>
    <wsa:MessageID>uuid:{msg_id}</wsa:MessageID>
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


def run(uuid, scopes, host_ip="192.168.1.138", onvif_port=8089):
    global UUID, SCOPES, HOST_IP, ONVIF_PORT
    UUID = uuid; SCOPES = scopes; HOST_IP = host_ip; ONVIF_PORT = onvif_port

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.bind(("0.0.0.0", PORT))
    mreq = struct.pack("4s4s", socket.inet_aton(MCAST), socket.inet_aton("0.0.0.0"))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    sock.settimeout(5)
    log.info(f"WS-Discovery on udp/{PORT}")

    import uuid as _uuid
    while True:
        try:
            data, addr = sock.recvfrom(8192)
            text = data.decode("utf-8", errors="ignore")
            if "Probe" not in text:
                continue
            msg_id = "unknown"
            m = re.search(r'<[^:]*:MessageID[^>]*>([^<]+)', text)
            if m:
                msg_id = m.group(1)
            resp = PROBE_MATCH.format(
                relates_to=msg_id, msg_id=_uuid.uuid4(),
                uuid=UUID, scopes=" ".join(SCOPES),
                host=HOST_IP, port=ONVIF_PORT,
            )
            sock.sendto(resp.encode(), addr)
            log.info(f"ProbeMatch -> {addr}")
        except socket.timeout:
            continue
        except Exception as e:
            log.error(f"Discovery err: {e}")
