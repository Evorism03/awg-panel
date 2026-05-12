from fastapi import FastAPI, HTTPException, Header, Response
from pydantic import BaseModel
import base64, io, ipaddress, os, re, secrets, shutil, subprocess, time
import qrcode
from .config import *

app = FastAPI(title="AmneziaWG Admin")

class ClientCreate(BaseModel):
    name: str


def auth(authorization: str | None):
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True).strip()
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=e.output.strip() or str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail=f"Command not found: {cmd[0]}")


def mock_key() -> str:
    return base64.b64encode(secrets.token_bytes(32)).decode()


def awg(args: list[str], input_text: str | None = None) -> str:
    if MOCK_AWG:
        if args in [["genkey"], ["genpsk"]]:
            return mock_key()
        if args == ["pubkey"]:
            return mock_key()
        if args[:2] == ["show", AWG_INTERFACE]:
            return "mock\tlatest-handshake\ttransfer-rx\ttransfer-tx"
    try:
        return subprocess.check_output([AWG_BIN, *args], input=input_text, stderr=subprocess.STDOUT, text=True).strip()
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=e.output.strip() or str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail=f"Command not found: {AWG_BIN}")


def ensure_mock_cfg():
    if not MOCK_AWG or os.path.exists(AWG_CONFIG_PATH):
        return
    os.makedirs(os.path.dirname(AWG_CONFIG_PATH), exist_ok=True)
    with open(AWG_CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write("""[Interface]
PrivateKey = mock-server-private-key
Address = 10.8.1.1/24
ListenPort = 51820
Jc = 4
Jmin = 40
Jmax = 70
S1 = 0
S2 = 0
H1 = 1
H2 = 2
H3 = 3
H4 = 4
""")


def read_cfg() -> str:
    ensure_mock_cfg()
    with open(AWG_CONFIG_PATH, "r", encoding="utf-8") as f:
        return f.read()


def write_cfg(text: str):
    backup = f"{AWG_CONFIG_PATH}.bak.{int(time.time())}"
    shutil.copy2(AWG_CONFIG_PATH, backup)
    with open(AWG_CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(text.rstrip() + "\n")


def parse_interface(text: str) -> dict:
    m = re.search(r"\[Interface\](.*?)(?=\n\[Peer\]|\Z)", text, re.S)
    if not m:
        raise HTTPException(500, "No [Interface] section")
    data = {}
    for line in m.group(1).splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
    return data


def parse_peers(text: str) -> list[dict]:
    chunks = re.split(r"\n(?=\[Peer\])", text)
    peers = []
    for chunk in chunks:
        if not chunk.strip().startswith("[Peer]"):
            continue
        name = ""
        cm = re.search(r"#\s*Name:\s*(.+)", chunk)
        if cm:
            name = cm.group(1).strip()
        data = {"name": name, "raw": chunk.strip()}
        for line in chunk.splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()
        peers.append(data)
    return peers


def next_ip(interface_address: str, peers: list[dict]) -> str:
    cidr = interface_address.split(",")[0].strip()
    net = ipaddress.ip_network(cidr, strict=False)
    used = set()
    for p in peers:
        for ip in p.get("AllowedIPs", "").split(","):
            ip = ip.strip()
            if ip:
                used.add(str(ipaddress.ip_interface(ip).ip))
    for host in net.hosts():
        s = str(host)
        if s != str(ipaddress.ip_interface(cidr).ip) and s not in used:
            return s
    raise HTTPException(500, "No free client IP")


def client_config(private_key: str, address: str, server_public: str, peer: dict, interface: dict) -> str:
    awg_extra = []
    for key in ["Jc", "Jmin", "Jmax", "S1", "S2", "H1", "H2", "H3", "H4"]:
        if key in interface:
            awg_extra.append(f"{key} = {interface[key]}")
    extra = "\n".join(awg_extra)
    return f"""[Interface]
PrivateKey = {private_key}
Address = {address}/32
DNS = {CLIENT_DNS}
{extra}

[Peer]
PublicKey = {server_public}
PresharedKey = {peer['PresharedKey']}
AllowedIPs = {CLIENT_ALLOWED_IPS}
Endpoint = {SERVER_ENDPOINT}
PersistentKeepalive = {CLIENT_PERSISTENT_KEEPALIVE}
""".strip() + "\n"


def reload_service():
    if MOCK_AWG or not RELOAD_COMMAND:
        return
    result = subprocess.run(RELOAD_COMMAND, shell=True, text=True, capture_output=True)
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=(result.stderr or result.stdout or "Reload failed").strip())

@app.get("/api/health")
def health():
    return {"ok": True, "interface": AWG_INTERFACE, "mock": MOCK_AWG}

@app.get("/api/clients")
def clients(authorization: str | None = Header(None)):
    auth(authorization)
    peers = parse_peers(read_cfg())
    dump = ""
    try:
        dump = awg(["show", AWG_INTERFACE, "dump"])
    except Exception:
        pass
    return {"clients": peers, "dump": dump}

@app.post("/api/clients")
def create_client(body: ClientCreate, authorization: str | None = Header(None)):
    auth(authorization)
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Client name is required")
    text = read_cfg()
    interface = parse_interface(text)
    peers = parse_peers(text)
    private_key = awg(["genkey"])
    public_key = awg(["pubkey"], input_text=private_key)
    psk = awg(["genpsk"])
    ip = next_ip(interface.get("Address", "10.8.1.1/24"), peers)
    peer_block = f"""

[Peer]
# Name: {name}
PublicKey = {public_key}
PresharedKey = {psk}
AllowedIPs = {ip}/32
"""
    write_cfg(text.rstrip() + peer_block)
    reload_service()
    server_public = awg(["pubkey"], input_text=interface["PrivateKey"])
    cfg = client_config(private_key, ip, server_public, {"PresharedKey": psk}, interface)
    os.makedirs(CLIENTS_DIR, exist_ok=True)
    path = f"{CLIENTS_DIR}/{re.sub(r'[^a-zA-Z0-9_.-]+','_',name)}.conf"
    with open(path, "w", encoding="utf-8") as f:
        f.write(cfg)
    return {"name": name, "publicKey": public_key, "address": f"{ip}/32", "config": cfg}

@app.delete("/api/clients/{public_key}")
def delete_client(public_key: str, authorization: str | None = Header(None)):
    auth(authorization)
    text = read_cfg()
    chunks = re.split(r"\n(?=\[Peer\])", text)
    kept = []
    found = False
    for ch in chunks:
        if ch.strip().startswith("[Peer]") and f"PublicKey = {public_key}" in ch:
            found = True
            continue
        kept.append(ch)
    if not found:
        raise HTTPException(404, "Peer not found")
    write_cfg("\n".join(kept))
    reload_service()
    return {"ok": True}

@app.post("/api/qrcode")
def qr(payload: dict, authorization: str | None = Header(None)):
    auth(authorization)
    img = qrcode.make(payload.get("config", ""))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")
