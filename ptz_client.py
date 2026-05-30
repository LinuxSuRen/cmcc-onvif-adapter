#!/usr/bin/env python3
"""ONVIF PTZ 控制客户端 - 直连 CMCC ONVIF Adapter"""

import requests

ONVIF_URL = "http://192.168.1.138:8089/onvif/device_service"

SOAP = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope"'
    ' xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl"'
    ' xmlns:tt="http://www.onvif.org/ver10/schema">'
    '<SOAP-ENV:Body>{body}</SOAP-ENV:Body>'
    '</SOAP-ENV:Envelope>'
)


def continuous_move(pan=0, tilt=0, zoom=0):
    body = (
        '<tptz:ContinuousMove>'
        '<tptz:ProfileToken>main</tptz:ProfileToken>'
        '<tptz:Velocity>'
        f'<tt:PanTilt x="{pan}" y="{tilt}"/>'
        f'<tt:Zoom x="{zoom}"/>'
        '</tptz:Velocity>'
        '</tptz:ContinuousMove>'
    )
    r = requests.post(
        ONVIF_URL, data=SOAP.format(body=body),
        headers={"SOAPAction": "http://www.onvif.org/ver20/ptz/wsdl/ContinuousMove",
                 "Content-Type": "application/soap+xml"}
    )
    print(r.status_code, r.text[:200] if r.text else "OK")


def stop():
    body = (
        '<tptz:Stop>'
        '<tptz:ProfileToken>main</tptz:ProfileToken>'
        '<tptz:PanTilt>true</tptz:PanTilt>'
        '<tptz:Zoom>true</tptz:Zoom>'
        '</tptz:Stop>'
    )
    r = requests.post(
        ONVIF_URL, data=SOAP.format(body=body),
        headers={"SOAPAction": "http://www.onvif.org/ver20/ptz/wsdl/Stop",
                 "Content-Type": "application/soap+xml"}
    )
    print(r.status_code, r.text[:200] if r.text else "OK")


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "left"
    if cmd in ("left", "l"):
        continuous_move(pan=-0.5)
        import time; time.sleep(0.8); stop()
    elif cmd in ("right", "r"):
        continuous_move(pan=0.5)
        import time; time.sleep(0.8); stop()
    elif cmd in ("up", "u"):
        continuous_move(tilt=0.5)
        import time; time.sleep(0.8); stop()
    elif cmd in ("down", "d"):
        continuous_move(tilt=-0.5)
        import time; time.sleep(0.8); stop()
    elif cmd == "stop":
        stop()
    elif cmd in ("zoomin", "zi"):
        continuous_move(zoom=0.5)
        import time; time.sleep(0.5); stop()
    elif cmd in ("zoomout", "zo"):
        continuous_move(zoom=-0.5)
        import time; time.sleep(0.5); stop()
    else:
        print("Usage: python3 ptz_client.py [left|right|up|down|stop|zoomin|zoomout]")
