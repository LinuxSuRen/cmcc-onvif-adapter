#!/usr/bin/env python3
"""ONVIF WS-Discovery 发现工具"""

import socket
import struct

MCAST = "239.255.255.250"
PORT = 3702

probe = """<?xml version="1.0" encoding="utf-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope"
                   xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
                   xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
  <SOAP-ENV:Header>
    <wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</wsa:Action>
    <wsa:MessageID>uuid:discover-1</wsa:MessageID>
    <wsa:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>
  </SOAP-ENV:Header>
  <SOAP-ENV:Body><d:Probe/></SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.settimeout(5)
sock.sendto(probe.encode(), (MCAST, PORT))

print("📡 Scanning for ONVIF devices...\n")
while True:
    try:
        data, addr = sock.recvfrom(8192)
        text = data.decode("utf-8", errors="ignore")
        import re
        addrs = re.findall(r'<d:XAddrs[^>]*>([^<]+)', text)
        types = re.findall(r'<d:Types[^>]*>([^<]+)', text)
        scopes = re.findall(r'<d:Scopes[^>]*>([^<]+)', text)
        print(f"✅ {addr[0]}")
        for a in addrs:
            print(f"   XAddrs: {a}")
        if scopes:
            print(f"   Scopes: {scopes[0][:120]}")
        print()
    except socket.timeout:
        break

sock.close()
print("Done")
