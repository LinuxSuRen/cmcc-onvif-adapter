import socket, struct, re, uuid, logging, time

log = logging.getLogger("onvif.disc")
MCAST = "239.255.255.250"
PORT = 3702

HELLO = """<?xml version="1.0" encoding="utf-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope"
                   xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
                   xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
                   xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <SOAP-ENV:Header>
    <wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Hello</wsa:Action>
    <wsa:MessageID>uuid:{mid}</wsa:MessageID>
    <wsa:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>
    <d:AppSequence InstanceId="1" MessageNumber="{seq}"/>
  </SOAP-ENV:Header>
  <SOAP-ENV:Body>
    <d:Hello>
      <wsa:EndpointReference><wsa:Address>{uuid}</wsa:Address></wsa:EndpointReference>
      <d:Types>dn:NetworkVideoTransmitter</d:Types>
      <d:Scopes>{scopes}</d:Scopes>
      <d:XAddrs>http://{host}:{port}/onvif/device_service</d:XAddrs>
      <d:MetadataVersion>1</d:MetadataVersion>
    </d:Hello>
  </SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""


def _multicast_sender():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
    return sock


def _broadcast_hello(dev_uuid, scopes, host_ip, onvif_port):
    sock = _multicast_sender()
    seq = 0
    log.info(f"WS-Discovery Hello broadcast mode (port {PORT} busy)")
    while True:
        msg = HELLO.format(
            mid=uuid.uuid4(), seq=seq, uuid=dev_uuid,
            scopes=" ".join(scopes), host=host_ip, port=onvif_port,
        )
        sock.sendto(msg.encode(), (MCAST, PORT))
        seq += 1
        time.sleep(30)

PROBE_MATCH = """<?xml version="1.0" encoding="utf-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope"
                   xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
                   xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
                   xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <SOAP-ENV:Header>
    <wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/ProbeMatches</wsa:Action>
    <wsa:RelatesTo>{rid}</wsa:RelatesTo>
    <wsa:To>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:To>
    <wsa:MessageID>uuid:{mid}</wsa:MessageID>
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


def run(dev_uuid, scopes, host_ip="192.168.1.138", onvif_port=8089):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except AttributeError:
        pass

    port = PORT
    while port <= PORT + 5:
        try:
            sock.bind(("0.0.0.0", port))
            break
        except OSError:
            port += 1
    else:
        log.warning(f"WS-Discovery ports {PORT}-{PORT+5} in use, switching to Hello broadcast")
        _broadcast_hello(dev_uuid, scopes, host_ip, onvif_port)
        return

    mreq = struct.pack("4s4s", socket.inet_aton(MCAST), socket.inet_aton("0.0.0.0"))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    sock.settimeout(5)
    log.info(f"WS-Discovery udp/{port}")
    while True:
        try:
            data, addr = sock.recvfrom(8192)
            text = data.decode("utf-8", errors="ignore")
            if "Probe" not in text:
                continue
            m = re.search(r'<[^:]*:MessageID[^>]*>([^<]+)', text)
            rid = m.group(1) if m else "unknown"
            resp = PROBE_MATCH.format(
                rid=rid, mid=uuid.uuid4(), uuid=dev_uuid,
                scopes=" ".join(scopes), host=host_ip, port=onvif_port,
            )
            sock.sendto(resp.encode(), addr)
            log.info(f"ProbeMatch -> {addr}")
        except socket.timeout:
            continue
