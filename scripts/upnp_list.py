# Ask the router (UPnP IGD) which ports it forwards from the internet to the LAN
import re
import socket
import urllib.request

MSG = ("M-SEARCH * HTTP/1.1\r\nHOST:239.255.255.250:1900\r\nMAN:\"ssdp:discover\"\r\nMX:2\r\n"
       "ST:urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n")

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(3)
s.sendto(MSG.encode(), ("239.255.255.250", 1900))
try:
    data = s.recv(4096).decode(errors="ignore")
except Exception as e:
    print("no UPnP gateway answered (UPnP likely off):", e)
    raise SystemExit

loc = re.search(r"(?i)location:\s*(\S+)", data).group(1)
xml = urllib.request.urlopen(loc, timeout=5).read().decode(errors="ignore")
base = re.match(r"(https?://[^/]+)", loc).group(1)
svc = None
for st in ("WANIPConnection:2", "WANIPConnection:1", "WANPPPConnection:1"):
    m = re.search(r"<serviceType>urn:schemas-upnp-org:service:" + st +
                  r"</serviceType>.*?<controlURL>([^<]+)</controlURL>", xml, re.S)
    if m:
        svc = ("urn:schemas-upnp-org:service:" + st, base + m.group(1))
        break
print("UPnP gateway:", loc, "service:", svc[0] if svc else None)

ENV = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
       's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
       '<u:GetGenericPortMappingEntry xmlns:u="{0}"><NewPortMappingIndex>{1}</NewPortMappingIndex>'
       '</u:GetGenericPortMappingEntry></s:Body></s:Envelope>')


def tag(xml_text, name):
    m = re.search("<{0}>([^<]*)</{0}>".format(name), xml_text)
    return m.group(1) if m else ""


n = 0
for i in range(64):
    req = urllib.request.Request(svc[1], ENV.format(svc[0], i).encode(), {
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPAction": '"{0}#GetGenericPortMappingEntry"'.format(svc[0])})
    try:
        r = urllib.request.urlopen(req, timeout=5).read().decode(errors="ignore")
    except Exception:
        break
    n += 1
    print("  {} ext {} -> {}:{}  ({})".format(tag(r, "NewProtocol"), tag(r, "NewExternalPort"),
          tag(r, "NewInternalClient"), tag(r, "NewInternalPort"), tag(r, "NewPortMappingDescription")))
print("forwarded entries:", n)
