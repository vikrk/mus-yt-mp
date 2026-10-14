import base64,urllib.parse

def _maybe_b64_vless(text):
    t = "".join(text.split())
    if "vless://" in text: return text
    for dec in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            out = dec(t + "="*(-len(t)%4)).decode("utf-8","ignore")
            if "vless://" in out or "vpn://" in out or "[Interface]" in out: return out
        except Exception: pass
    return text

def _q1(qs, key, default=""):
    v = qs.get(key); return v[0] if v else default

def vless_outbound(link, tag, mss=0):
    try:
        u = urllib.parse.urlparse(link)
        if u.scheme != "vless": return None
        uuid = urllib.parse.unquote(u.username or ""); host = u.hostname or ""
        port = 443 if u.port is None else u.port
        if not uuid or not host or port<1 or port>65535: return None
        qs = urllib.parse.parse_qs(u.query)
        net = _q1(qs,"type","tcp") or "tcp";  net = "tcp" if net=="raw" else net
        sec = _q1(qs,"security","none") or "none"
        if net not in ("tcp","grpc","ws","xhttp","splithttp"): return None
        if sec not in ("tls","reality"): return None
        if sec=="reality" and net not in ("tcp","grpc","xhttp"): return None
        sni=_q1(qs,"sni") or _q1(qs,"host") or host; fp=_q1(qs,"fp","chrome") or "chrome"
        flow=_q1(qs,"flow",""); alpn=_q1(qs,"alpn","")
        user={"id":uuid,"encryption":"none"}
        if flow and net=="tcp": user["flow"]=flow
        stream={"network":net,"security":sec}
        if sec=="reality":
            stream["realitySettings"]={"serverName":sni,"fingerprint":fp,"publicKey":_q1(qs,"pbk"),"shortId":_q1(qs,"sid"),"spiderX":_q1(qs,"spx","/") or "/"}
        elif sec=="tls":
            tls={"serverName":sni,"fingerprint":fp}
            if _q1(qs,"allowInsecure","0") in ("1","true"): return None
            if alpn: tls["alpn"]=[a for a in alpn.replace("%2C",",").split(",") if a]
            stream["tlsSettings"]=tls
        if net=="tcp": stream["tcpSettings"]={"header":{"type":"none"}}
        elif net=="grpc": stream["grpcSettings"]={"serviceName":_q1(qs,"serviceName"),"multiMode":_q1(qs,"mode")=="multi"}
        elif net=="ws": stream["wsSettings"]={"path":_q1(qs,"path","/") or "/","headers":{"Host":_q1(qs,"host") or sni}}
        elif net in ("xhttp","splithttp"):
            stream["network"]="xhttp"; stream["xhttpSettings"]={"path":_q1(qs,"path","/") or "/","host":_q1(qs,"host") or sni,"mode":_q1(qs,"mode","auto") or "auto"}
        stream["sockopt"]={"domainStrategy":"ForceIPv4","tcpKeepAliveIdle":100,"tcpKeepAliveInterval":15,"tcpNoDelay":True}
        if mss and mss>0: stream["sockopt"]["tcpMaxSeg"]=mss
        return {"tag":tag,"protocol":"vless","settings":{"vnext":[{"address":host,"port":port,"users":[user]}]},"streamSettings":stream}
    except Exception as e:
        return None
