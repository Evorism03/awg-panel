from fastapi import Cookie, FastAPI, HTTPException, Header, Response
from fastapi import Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import asyncio, base64, configparser, csv, hashlib, io, ipaddress, json, os, re, secrets, shutil, subprocess, time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from threading import RLock
from datetime import date, datetime, timedelta
import urllib.request
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from .config import *
from . import db as _db
from . import webhook as _wh

_sse_queues: list = []

def _get_cfg_hash() -> str:
    try:
        if AWG_DOCKER_CONTAINER:
            return ""
        with open(AWG_CONFIG_PATH, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception:
        return ""

def _get_dump_hash() -> str:
    try:
        if MOCK_AWG:
            return ""
        bin_ = _resolve_awg_bin()
        cmd = [bin_, "show", AWG_INTERFACE, "dump"]
        if AWG_DOCKER_CONTAINER:
            cmd = ["docker", "exec", "-i", AWG_DOCKER_CONTAINER, bin_, "show", AWG_INTERFACE, "dump"]
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True).strip()
        return hashlib.md5(out.encode()).hexdigest()
    except Exception:
        return ""

async def _sse_monitor():
    last_cfg = await asyncio.to_thread(_get_cfg_hash)
    last_dump = await asyncio.to_thread(_get_dump_hash)
    while True:
        await asyncio.sleep(3)
        try:
            cfg = await asyncio.to_thread(_get_cfg_hash)
            dump = await asyncio.to_thread(_get_dump_hash)
            if cfg != last_cfg or dump != last_dump:
                last_cfg, last_dump = cfg, dump
                for q in list(_sse_queues):
                    q.put_nowait("clients")
        except Exception:
            pass


async def _expiry_enforcer():
    """Check and block expired clients every hour."""
    while True:
        await asyncio.sleep(3600)
        try:
            await asyncio.to_thread(enforce_expired_clients)
        except Exception:
            pass


@asynccontextmanager
async def lifespan(_app):
    _db.init_db(DB_PATH)
    _db.migrate_from_json(
        expired_path=f"{CLIENTS_DIR}/expired-clients.json",
        meta_path=f"{CLIENTS_DIR}/clients-meta.json",
        servers_json_path=SERVERS_PATH,
        orders_json_path=ORDERS_PATH,
        local_server_json_path=LOCAL_SERVER_PATH,
    )
    # Enforce expiry once at startup to catch clients that expired while the server was down
    try:
        enforce_expired_clients()
    except Exception:
        pass
    # Remove meta entries whose peer is gone from AWG config and not expired (stale after AWG reset)
    try:
        active = {p.get("PublicKey", "").strip() for p in parse_peers(read_cfg())}
        expired_keys = set(load_expired_clients().keys())
        _db.prune_orphan_meta(active, expired_keys)
    except Exception:
        pass
    task = asyncio.create_task(_sse_monitor())
    expiry_task = asyncio.create_task(_expiry_enforcer())
    yield
    task.cancel()
    expiry_task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    try:
        await expiry_task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="AmneziaWG Admin", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=512)
data_lock = RLock()

class ClientCreate(BaseModel):
    name: str
    term: str = "1m"
    contact: str = ""

class ClientImport(BaseModel):
    name: str = ""
    config: str
    contact: str = ""

class ClientUpdate(BaseModel):
    name: str | None = None
    contact: str | None = None

class LoginRequest(BaseModel):
    username: str
    password: str

class ServerCreate(BaseModel):
    name: str
    baseUrl: str
    token: str = ""
    maxUsers: int | None = None

class ServerUpdate(BaseModel):
    name: str | None = None
    baseUrl: str | None = None
    token: str | None = None
    maxUsers: int | None = None

class OrderCreate(BaseModel):
    login: str
    email: str
    term: str = "1 месяц"

class OrderUpdate(BaseModel):
    status: str | None = None

class ClientRenew(BaseModel):
    term: str = "1m"

class ClientExpiry(BaseModel):
    expiresAt: str | None = None

def auth(authorization: str | None, awg_panel_session: str | None):
    bearer_ok = authorization == f"Bearer {ADMIN_TOKEN}"
    cookie_ok = awg_panel_session == ADMIN_TOKEN
    if not bearer_ok and not cookie_ok:
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


_resolved_awg_bin: str | None = None

def _resolve_awg_bin() -> str:
    """Return the awg binary to use, auto-detecting inside AWG_DOCKER_CONTAINER if needed."""
    global _resolved_awg_bin
    if _resolved_awg_bin:
        return _resolved_awg_bin
    if not AWG_DOCKER_CONTAINER or AWG_BIN != "awg":
        _resolved_awg_bin = AWG_BIN
        return _resolved_awg_bin
    for candidate in ["awg", "/usr/bin/awg", "/usr/local/bin/awg"]:
        try:
            result = subprocess.run(
                ["docker", "exec", AWG_DOCKER_CONTAINER, "sh", "-c", f"command -v {candidate}"],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0 and result.stdout.strip():
                _resolved_awg_bin = result.stdout.strip()
                return _resolved_awg_bin
        except Exception:
            continue
    _resolved_awg_bin = AWG_BIN
    return _resolved_awg_bin


def awg(args: list[str], input_text: str | None = None) -> str:
    if MOCK_AWG:
        if args in [["genkey"], ["genpsk"]]:
            return mock_key()
        if args == ["pubkey"]:
            return mock_key()
        if args[:2] == ["show", AWG_INTERFACE]:
            return "mock\tlatest-handshake\ttransfer-rx\ttransfer-tx"
    bin_ = _resolve_awg_bin()
    cmd = [bin_, *args]
    if AWG_DOCKER_CONTAINER:
        cmd = ["docker", "exec", "-i", AWG_DOCKER_CONTAINER, bin_, *args]
    try:
        return subprocess.check_output(cmd, input=input_text, stderr=subprocess.STDOUT, text=True).strip()
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=e.output.strip() or str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail=f"Command not found: {cmd[0]}")


def remove_runtime_peer(public_key: str):
    if not public_key or MOCK_AWG:
        return
    try:
        awg(["set", AWG_INTERFACE, "peer", public_key, "remove"])
    except Exception:
        pass


def docker_exec(args: list[str], input_text: str | None = None) -> str:
    try:
        return subprocess.check_output(
            ["docker", "exec", "-i", AWG_DOCKER_CONTAINER, *args],
            input=input_text,
            stderr=subprocess.STDOUT,
            text=True,
        ).strip()
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=e.output.strip() or str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Command not found: docker")


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
    if AWG_DOCKER_CONTAINER:
        return docker_exec(["cat", AWG_CONTAINER_CONFIG_PATH])
    with open(AWG_CONFIG_PATH, "r", encoding="utf-8") as f:
        return f.read()


def write_cfg(text: str):
    backup = f"{AWG_CONFIG_PATH}.bak.{int(time.time())}"
    if AWG_DOCKER_CONTAINER:
        container_backup = f"{AWG_CONTAINER_CONFIG_PATH}.bak.{int(time.time())}"
        docker_exec(["cp", AWG_CONTAINER_CONFIG_PATH, container_backup])
        docker_exec(["sh", "-c", f"cat > {AWG_CONTAINER_CONFIG_PATH}"], text.rstrip() + "\n")
        return
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
        expires = re.search(r"#\s*Expires:\s*(.+)", chunk)
        if expires:
            data["expiresAt"] = expires.group(1).strip()
        id_m = re.search(r"#\s*ID:\s*(.+)", chunk)
        if id_m:
            data["clientId"] = id_m.group(1).strip()
        created_m = re.search(r"#\s*Created:\s*(.+)", chunk)
        if created_m:
            data["createdAt"] = created_m.group(1).strip()
        for line in chunk.splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()
        peers.append(data)
    return peers


def expired_clients_path() -> str:
    os.makedirs(CLIENTS_DIR, exist_ok=True)
    return DB_PATH


load_expired_clients = _db.load_expired_clients
save_expired_clients = _db.save_expired_clients
load_clients_meta = _db.load_clients_meta
save_clients_meta = _db.save_clients_meta


def attach_meta_to_peers(peers: list[dict]) -> list[dict]:
    meta = load_clients_meta()
    changed = False
    today = date.today().isoformat()
    for peer in peers:
        pk = peer.get("PublicKey", "").strip()
        if not pk:
            continue
        m = meta.get(pk, {})
        # conf > meta > generate new
        client_id = peer.get("clientId") or m.get("id") or ""
        if not client_id:
            client_id = secrets.token_hex(4)
            changed = True
        peer["clientId"] = client_id
        peer.setdefault("contact", m.get("contact", ""))
        if m.get("id") != client_id:
            m["id"] = client_id
            meta[pk] = m
            changed = True
        # createdAt: peer block > meta > today (written once, never overwritten)
        created_at = peer.get("createdAt") or m.get("createdAt") or today
        peer["createdAt"] = created_at
        if m.get("createdAt") != created_at:
            m["createdAt"] = created_at
            meta[pk] = m
            changed = True
        # Patch stored config to include # Client ID: so portal download works for old clients
        if not m.get("configPatched"):
            export = load_client_export(pk)
            if export is not None and f"# Client ID: {client_id}" not in export:
                store_client_export(pk, peer.get("name", ""), f"# Client ID: {client_id}\n{export.lstrip()}")
            m["configPatched"] = True
            meta[pk] = m
            changed = True
    if changed:
        save_clients_meta(meta)
    return peers


load_servers = _db.load_servers
save_servers = _db.save_servers
load_local_server_settings = _db.load_local_server_settings
save_local_server_settings = _db.save_local_server_settings
load_orders = _db.load_orders
save_orders = _db.save_orders


def normalize_panel_url(value: str) -> str:
    url = value.strip().rstrip("/")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = f"http://{url}"
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(400, "Invalid panel URL")
    return url


def normalize_max_users(value: int | None) -> int:
    if value is None:
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def server_identity(server: dict) -> dict:
    return {
        "id": server.get("id", ""),
        "name": server.get("name", ""),
        "baseUrl": server.get("baseUrl", ""),
        "token": server.get("token", ""),
        "maxUsers": normalize_max_users(server.get("maxUsers")),
    }


def local_server_identity() -> dict:
    settings = load_local_server_settings()
    return {
        "id": LOCAL_SERVER_ID,
        "name": settings.get("name") or LOCAL_SERVER_NAME,
        "baseUrl": "local",
        "token": "",
        "maxUsers": normalize_max_users(settings.get("maxUsers")),
        "kind": "local",
        "status": "online",
    }


def attach_client_source(clients: list[dict], server_id: str, server_name: str) -> list[dict]:
    for client in clients:
        client["serverId"] = server_id
        client["serverName"] = server_name
    return clients


def probe_panel(server: dict) -> str:
    try:
        req = urllib.request.Request(f"{server['baseUrl'].rstrip('/')}/api/health", method="GET")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                return "online"
    except Exception:
        return "offline"
    return "offline"


def list_servers(include_local: bool = True) -> list[dict]:
    result = []
    if include_local:
        result.append(local_server_identity())
    remote_servers = load_servers()
    if not remote_servers:
        return result
    with ThreadPoolExecutor(max_workers=min(8, len(remote_servers))) as pool:
        probes = [(server, pool.submit(probe_panel, server)) for server in remote_servers]
    for server, future in probes:
        item = server_identity(server)
        try:
            item["status"] = future.result()
        except Exception:
            item["status"] = "offline"
        item["kind"] = "remote"
        result.append(item)
    return result


def create_client_local(name: str, term: str, contact: str) -> dict:
    text = read_cfg()
    interface = parse_interface(text)
    peers = parse_peers(text)
    private_key = awg(["genkey"])
    public_key = awg(["pubkey"], input_text=private_key)
    expired = load_expired_clients()
    expired.pop(public_key, None)
    save_expired_clients(expired)
    psk = awg(["genpsk"])
    ip = next_ip(interface.get("Address", "10.8.1.1/24"), peers)
    expires_at = expiration_date(term)
    expires_line = f"# Expires: {expires_at}\n" if expires_at else ""
    client_id = secrets.token_hex(4)
    created_at = date.today().isoformat()
    peer_block = f"\n\n[Peer]\n# Name: {name}\n# ID: {client_id}\n# Created: {created_at}\n{expires_line}PublicKey = {public_key}\nPresharedKey = {psk}\nAllowedIPs = {ip}/32\n"
    write_cfg(text.rstrip() + peer_block)
    reload_async()
    meta = load_clients_meta()
    meta[public_key] = {"id": client_id, "contact": contact.strip()}
    save_clients_meta(meta)
    server_public = awg(["pubkey"], input_text=interface["PrivateKey"])
    cfg = f"# Client ID: {client_id}\n" + client_config(private_key, ip, server_public, {"PresharedKey": psk}, interface)
    store_client_export(public_key, name, cfg)
    _db.write_audit_log("client.create", "client", public_key, {"name": name, "clientId": client_id, "contact": contact.strip()})
    _wh.send("client.created", {"name": name, "publicKey": public_key, "clientId": client_id, "contact": contact.strip(), "expiresAt": expires_at})
    return {"name": name, "publicKey": public_key, "clientId": client_id,
            "contact": contact.strip(), "address": f"{ip}/32", "expiresAt": expires_at, "createdAt": created_at, "config": cfg}


def count_server_active_clients(server: dict) -> int:
    try:
        if server.get("kind") == "local" or server.get("id") == LOCAL_SERVER_ID:
            return len(parse_peers(read_cfg()))
        payload = panel_json(server, "GET", "/clients", timeout=5)
        return len([c for c in payload.get("clients", []) if not c.get("blocked")])
    except Exception:
        return -1


def find_available_server() -> dict | None:
    candidates = []
    for server in list_servers(include_local=True):
        if server.get("kind") != "local" and server.get("status") != "online":
            continue
        max_users = normalize_max_users(server.get("maxUsers"))
        count = count_server_active_clients(server)
        if count < 0:
            continue
        available = (max_users - count) if max_users > 0 else 999999
        if available > 0:
            candidates.append((available, server))
    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][1]


def process_order_internal(order: dict) -> dict:
    term_code = normalize_term(order.get("term", ""))
    name = (order.get("login") or f"order-{order['id'][:8]}").strip()
    contact = (order.get("email") or "").strip()
    server = find_available_server()
    if server is None:
        return {**order, "status": "pending", "processingError": "No server with available slots"}
    is_local = server.get("kind") == "local" or server.get("id") == LOCAL_SERVER_ID
    try:
        if is_local:
            result = create_client_local(name, term_code, contact)
        else:
            result = panel_json(server, "POST", "/clients",
                                payload={"name": name, "term": term_code, "contact": contact},
                                timeout=20)
    except Exception as e:
        return {**order, "status": "pending", "processingError": str(e)}
    return {
        **order,
        "status": "issued",
        "clientPublicKey": result.get("publicKey", ""),
        "clientId": result.get("clientId", ""),
        "serverId": server.get("id", LOCAL_SERVER_ID),
        "serverName": server.get("name", LOCAL_SERVER_NAME),
        "processedAt": datetime.now().isoformat(timespec="seconds"),
    }


def local_clients_payload() -> dict:
    local_name = local_server_identity()["name"]
    expired_clients = attach_client_source(enforce_expired_clients(), LOCAL_SERVER_ID, local_name)
    peers = attach_client_source(parse_peers(read_cfg()), LOCAL_SERVER_ID, local_name)
    attach_meta_to_peers(peers)
    for peer in peers:
        peer["blocked"] = False
        peer["status"] = "active"
    dump = ""
    try:
        dump = awg(["show", AWG_INTERFACE, "dump"])
    except Exception:
        pass
    return {
        "clients": peers + expired_clients,
        "expiredClientsPath": expired_clients_path(),
        "dump": dump,
        "serverId": LOCAL_SERVER_ID,
        "serverName": local_name,
    }


def sync_local_clients() -> dict:
    with data_lock:
        enforce_expired_clients()
        payload = local_clients_payload()
        payload["synced"] = len(payload.get("clients", []))
        payload["sync"] = {
            "source": "awg",
            "configPath": AWG_CONTAINER_CONFIG_PATH if AWG_DOCKER_CONTAINER else AWG_CONFIG_PATH,
            "interface": AWG_INTERFACE,
        }
        return payload


def remote_clients_payload(server: dict) -> dict:
    payload = panel_json(server, "GET", "/clients")
    server_id = server.get("id", "")
    server_name = server.get("name", "")
    clients = payload.get("clients", [])
    attach_client_source(clients, server_id, server_name)
    payload["clients"] = clients
    payload["serverId"] = server_id
    payload["serverName"] = server_name
    return payload


def aggregate_clients_payload() -> dict:
    merged_clients = []
    merged_dumps = []
    local_payload = local_clients_payload()
    merged_clients.extend(local_payload.get("clients", []))
    if local_payload.get("dump"):
        merged_dumps.append(f"# {local_payload.get('serverName') or LOCAL_SERVER_NAME}\n{local_payload['dump']}")
    for server in load_servers():
        try:
            payload = remote_clients_payload(server)
        except Exception:
            continue
        merged_clients.extend(payload.get("clients", []))
        dump = payload.get("dump", "")
        if dump:
            merged_dumps.append(f"# {payload.get('serverName') or server.get('name', '')}\n{dump}")
    return {
        "clients": merged_clients,
        "expiredClientsPath": expired_clients_path(),
        "dump": "\n\n".join(merged_dumps),
        "serverId": "all",
        "serverName": "All servers",
    }


def aggregate_expired_clients_payload() -> dict:
    merged_clients = []
    merged_clients.extend(local_clients_payload().get("clients", []))
    for server in load_servers():
        try:
            payload = remote_clients_payload(server)
        except Exception:
            continue
        merged_clients.extend(payload.get("clients", []))
    expired = [client for client in merged_clients if client.get("blocked") or client.get("status") in {"not_renewed", "renewal_pending"}]
    return {"clients": expired, "path": expired_clients_path(), "serverId": "all", "serverName": "All servers"}


def get_server(server_id: str | None) -> dict | None:
    if not server_id or server_id == LOCAL_SERVER_ID:
        return None
    if server_id == "all":
        raise HTTPException(status_code=400, detail="Server id 'all' cannot be used for single-server operations")
    for server in load_servers():
        if server.get("id") == server_id:
            return server
    raise HTTPException(status_code=404, detail="Server not found")


TERM_DISPLAY_MAP: dict[str, str] = {
    "1 день": "1d",  "3 дня": "3d",  "7 дней": "7d",  "15 дней": "15d",
    "1 месяц": "1m", "3 месяца": "3m", "6 месяцев": "6m", "1 год": "1y",
    "1 day": "1d",   "3 days": "3d",  "7 days": "7d",  "15 days": "15d",
    "1 month": "1m", "3 months": "3m", "6 months": "6m", "1 year": "1y",
    "1d": "1d", "3d": "3d", "7d": "7d", "15d": "15d",
    "1m": "1m", "3m": "3m", "6m": "6m", "1y": "1y",
    "admin": "admin", "forever": "forever",
}

def normalize_term(term: str) -> str:
    return TERM_DISPLAY_MAP.get(term.strip(), "1m")


def panel_request(server: dict, method: str, path: str, body: bytes | None = None, content_type: str = "application/json", timeout: int = 15) -> tuple[int, bytes, str]:
    headers = {}
    token = server.get("token", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = content_type
    url = f"{server['baseUrl'].rstrip('/')}/api{path}"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), resp.headers.get_content_type()
    except HTTPError as e:
        return e.code, e.read(), e.headers.get_content_type() if e.headers else "text/plain"
    except URLError as e:
        raise HTTPException(status_code=502, detail=f"Panel unreachable: {e.reason}")


def panel_json(server: dict, method: str, path: str, payload: dict | None = None, timeout: int = 15):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    status, raw, content_type = panel_request(server, method, path, body=body, timeout=timeout)
    text = raw.decode("utf-8", errors="replace") if raw else ""
    if status >= 400:
        if status in {401, 403}:
            raise HTTPException(status_code=502, detail="Remote panel authorization failed. Check server token.")
        detail = text.strip() or "Remote panel error"
        raise HTTPException(status_code=status, detail=detail)
    if content_type == "application/json":
        return json.loads(text or "{}")
    return text


def panel_bytes(server: dict, method: str, path: str, payload: dict | None = None) -> bytes:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    status, raw, _ = panel_request(server, method, path, body=body)
    if status >= 400:
        if status in {401, 403}:
            raise HTTPException(status_code=502, detail="Remote panel authorization failed. Check server token.")
        detail = raw.decode("utf-8", errors="replace").strip() or "Remote panel error"
        raise HTTPException(status_code=status, detail=detail)
    return raw


def expired_clients_list() -> list[dict]:
    clients = load_expired_clients()
    result = sorted(
        clients.values(),
        key=lambda client: (client.get("expiresAt", ""), client.get("name", "")),
    )
    return attach_meta_to_peers(result)


def is_expired_date(value: str | None) -> bool:
    if not value:
        return False
    try:
        return date.today() > date.fromisoformat(value)
    except ValueError:
        return False


def peer_from_block(block: str) -> dict:
    parsed = parse_peers(block)
    return parsed[0] if parsed else {}


def enforce_expired_clients() -> list[dict]:
    with data_lock:
        text = read_cfg()
        chunks = re.split(r"\n(?=\[Peer\])", text)
        kept = []
        expired = load_expired_clients()
        changed = False
        for chunk in chunks:
            peer = peer_from_block(chunk) if chunk.strip().startswith("[Peer]") else {}
            public_key = peer.get("PublicKey", "").strip()
            if public_key and is_expired_date(peer.get("expiresAt")):
                previous = expired.get(public_key, {})
                peer["raw"] = chunk.strip()
                peer["blocked"] = True
                peer["status"] = "not_renewed"
                peer["reason"] = "subscription_expired"
                peer["blockedAt"] = previous.get("blockedAt") or date.today().isoformat()
                if public_key not in expired:
                    _db.write_audit_log("client.expire", "client", public_key, {"name": peer.get("name", ""), "expiresAt": peer.get("expiresAt", "")})
                    _wh.send("client.expired", {"publicKey": public_key, "name": peer.get("name", ""), "expiresAt": peer.get("expiresAt", "")})
                expired[public_key] = peer
                changed = True
                continue
            kept.append(chunk)
        if changed:
            write_cfg("\n".join(kept))
            save_expired_clients(expired)
            reload_service()
        return expired_clients_list()


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


def add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    month_days = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return value.replace(year=year, month=month, day=min(value.day, month_days[month - 1]))


def expiration_date(term: str) -> str:
    if term in {"admin", "forever"}:
        return ""
    today = date.today()
    terms = {
        "1d": today + timedelta(days=1),
        "3d": today + timedelta(days=3),
        "7d": today + timedelta(days=7),
        "15d": today + timedelta(days=15),
        "1m": add_months(today, 1),
        "3m": add_months(today, 3),
        "6m": add_months(today, 6),
        "1y": add_months(today, 12),
    }
    if term not in terms:
        raise HTTPException(400, "Invalid client term")
    return terms[term].isoformat()


def client_config(private_key: str, address: str, server_public: str, peer: dict, interface: dict) -> str:
    awg_extra = []
    for key in ["Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4", "I1", "I2", "I3", "I4", "I5"]:
        if key in interface:
            awg_extra.append(f"{key} = {interface[key]}")
    extra = "\n".join(awg_extra)
    return f"""[Interface]
PrivateKey = {private_key}
Address = {address}/32
MTU = {interface.get('MTU', '1280')}
DNS = {CLIENT_DNS}
{extra}

[Peer]
PublicKey = {server_public}
PresharedKey = {peer['PresharedKey']}
AllowedIPs = {CLIENT_ALLOWED_IPS}
Endpoint = {SERVER_ENDPOINT}
PersistentKeepalive = {CLIENT_PERSISTENT_KEEPALIVE}
""".strip() + "\n"


def client_config_for_amnezia(config_text: str) -> tuple[configparser.SectionProxy, configparser.SectionProxy, str, str]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read_string(config_text)
    if not parser.has_section("Interface") or not parser.has_section("Peer"):
        raise HTTPException(400, "Config must contain [Interface] and [Peer] sections")
    interface = parser["Interface"]
    peer = parser["Peer"]
    dns_value = interface.get("DNS", CLIENT_DNS)
    dns_parts = [part.strip() for part in dns_value.split(",") if part.strip()]
    dns1 = dns_parts[0] if dns_parts else CLIENT_DNS
    dns2 = dns_parts[1] if len(dns_parts) > 1 else dns1
    return interface, peer, dns1, dns2


def strip_amnezia_r_tag(value: str) -> str:
    return re.sub(r"^<r\s*\d+>", "", value.strip())


def safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip())


def client_export_path(public_key: str) -> str:
    os.makedirs(CLIENTS_DIR, exist_ok=True)
    return f"{CLIENTS_DIR}/{safe_name(public_key)}.conf"


def store_client_export(public_key: str, name: str, config_text: str):
    public_path = client_export_path(public_key)
    with open(public_path, "w", encoding="utf-8") as f:
        f.write(config_text)
    named_path = f"{CLIENTS_DIR}/{safe_name(name)}.conf"
    if named_path != public_path:
        with open(named_path, "w", encoding="utf-8") as f:
            f.write(config_text)


def public_key_from_client_config(config_text: str) -> str:
    interface, _, _, _ = client_config_for_amnezia(config_text)
    private_key = interface.get("PrivateKey", "").strip()
    if not private_key:
        raise HTTPException(400, "Client config has no Interface.PrivateKey")
    return awg(["pubkey"], input_text=private_key)


def client_name_from_config(config_text: str) -> str:
    patterns = [
        r"(?im)^\s*#\s*Name:\s*(.+?)\s*$",
        r"(?im)^\s*#\s*Client:\s*(.+?)\s*$",
        r"(?im)^\s*Name\s*=\s*(.+?)\s*$",
        r"(?im)^\s*ClientName\s*=\s*(.+?)\s*$",
        r"(?im)^\s*Description\s*=\s*(.+?)\s*$",
    ]
    for pattern in patterns:
        match = re.search(pattern, config_text)
        if match:
            return match.group(1).strip().strip('"')
    return ""


def load_client_export(public_key: str) -> str | None:
    path = client_export_path(public_key)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return None


def rename_stored_client_export(public_key: str, old_name: str, new_name: str):
    export_path = client_export_path(public_key)
    cfg = load_client_export(public_key)
    if cfg is None:
        return
    new_named_path = f"{CLIENTS_DIR}/{safe_name(new_name)}.conf"
    if new_named_path != export_path:
        with open(new_named_path, "w", encoding="utf-8") as f:
            f.write(cfg)
    old_named_path = f"{CLIENTS_DIR}/{safe_name(old_name)}.conf" if old_name else ""
    if old_named_path and old_named_path not in {export_path, new_named_path} and os.path.exists(old_named_path):
        os.remove(old_named_path)


def rename_peer_block(text: str, public_key: str, new_name: str) -> tuple[str, str] | None:
    chunks = re.split(r"\n(?=\[Peer\])", text)
    next_chunks = []
    old_name = ""
    found = False
    for chunk in chunks:
        peer = peer_from_block(chunk) if chunk.strip().startswith("[Peer]") else {}
        if peer.get("PublicKey", "").strip() != public_key:
            next_chunks.append(chunk)
            continue
        old_name = peer.get("name", "")
        if re.search(r"(?m)^#\s*Name:\s*.*$", chunk):
            chunk = re.sub(r"(?m)^#\s*Name:\s*.*$", f"# Name: {new_name}", chunk, count=1)
        else:
            chunk = re.sub(r"(?m)^\[Peer\]\s*$", f"[Peer]\n# Name: {new_name}", chunk, count=1)
        next_chunks.append(chunk)
        found = True
    if not found:
        return None
    return "\n".join(next_chunks), old_name


def _build_syncconf(text: str) -> str:
    interface = parse_interface(text)
    lines = ["[Interface]\nPrivateKey = " + interface.get("PrivateKey", "")]
    for peer in parse_peers(text):
        peer_lines = ["[Peer]"]
        for key in ["PublicKey", "PresharedKey", "AllowedIPs", "Endpoint", "PersistentKeepalive"]:
            val = peer.get(key, "").strip()
            if val:
                peer_lines.append(f"{key} = {val}")
        lines.append("\n".join(peer_lines))
    return "\n\n".join(lines) + "\n"


def _try_syncconf() -> bool:
    try:
        stripped = _build_syncconf(read_cfg())
        bin_ = _resolve_awg_bin()
        if AWG_DOCKER_CONTAINER:
            cmd = ["docker", "exec", "-i", AWG_DOCKER_CONTAINER, bin_, "syncconf", AWG_INTERFACE, "/dev/stdin"]
        else:
            cmd = [bin_, "syncconf", AWG_INTERFACE, "/dev/stdin"]
        result = subprocess.run(cmd, input=stripped, text=True, capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


def reload_service():
    if MOCK_AWG or not RELOAD_COMMAND:
        return
    if _try_syncconf():
        return
    result = subprocess.run(RELOAD_COMMAND, shell=True, text=True, capture_output=True)
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=(result.stderr or result.stdout or "Reload failed").strip())

_reload_lock = __import__('threading').Lock()

def _reload_bg():
    if not _reload_lock.acquire(blocking=False):
        return
    try:
        reload_service()
    except Exception:
        pass
    finally:
        _reload_lock.release()

def reload_async():
    __import__('threading').Thread(target=_reload_bg, daemon=True).start()


def _process_pending_orders_bg():
    try:
        with data_lock:
            orders = load_orders()
            changed = False
            for index, order in enumerate(orders):
                if order.get("status") != "pending":
                    continue
                updated = process_order_internal(order)
                if updated.get("status") == "issued":
                    orders[index] = updated
                    changed = True
            if changed:
                save_orders(orders)
    except Exception:
        pass



@app.get("/api/events")
async def sse_events(
    authorization: str | None = Header(None),
    awg_panel_session: str | None = Cookie(None),
):
    auth(authorization, awg_panel_session)
    queue: asyncio.Queue = asyncio.Queue()
    _sse_queues.append(queue)

    async def stream():
        try:
            yield "data: connected\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                    yield f"event: {event}\ndata: 1\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            if queue in _sse_queues:
                _sse_queues.remove(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "interface": AWG_INTERFACE,
        "configPath": AWG_CONTAINER_CONFIG_PATH if AWG_DOCKER_CONTAINER else AWG_CONFIG_PATH,
        "mock": MOCK_AWG,
    }

@app.post("/api/login")
def login(body: LoginRequest, response: Response):
    password = ADMIN_PASSWORD or ADMIN_TOKEN
    user_ok = secrets.compare_digest(body.username, ADMIN_USERNAME)
    password_ok = secrets.compare_digest(body.password, password)
    if not user_ok or not password_ok:
        raise HTTPException(status_code=401, detail="Unauthorized")
    response.set_cookie(
        "awg_panel_session",
        ADMIN_TOKEN,
        httponly=True,
        samesite="strict",
        secure=False,
    )
    return {"ok": True}

@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie("awg_panel_session")
    return {"ok": True}

@app.get("/api/servers")
def servers(authorization: str | None = Header(None), awg_panel_session: str | None = Cookie(None)):
    auth(authorization, awg_panel_session)
    return {"servers": list_servers()}


@app.post("/api/sync")
def sync(
    authorization: str | None = Header(None),
    awg_panel_session: str | None = Cookie(None),
    server_id: str | None = Query(None),
):
    auth(authorization, awg_panel_session)
    if server_id == "all":
        result = {"ok": True, "local": sync_local_clients(), "remotes": []}
        for server in load_servers():
            try:
                result["remotes"].append(panel_json(server, "POST", "/sync"))
            except Exception as error:
                result["remotes"].append({
                    "serverId": server.get("id", ""),
                    "serverName": server.get("name", ""),
                    "error": str(error),
                })
        return result
    server = get_server(server_id)
    if server is not None:
        return panel_json(server, "POST", "/sync")
    return sync_local_clients()


@app.post("/api/servers")
def create_server(body: ServerCreate, authorization: str | None = Header(None), awg_panel_session: str | None = Cookie(None)):
    auth(authorization, awg_panel_session)
    with data_lock:
        name = body.name.strip()
        base_url = normalize_panel_url(body.baseUrl)
        token = body.token.strip()
        if not name:
            raise HTTPException(400, "Server name is required")
        if not token:
            raise HTTPException(400, "Server token is required")
        server = {
            "id": secrets.token_hex(8),
            "name": name,
            "baseUrl": base_url,
            "token": token,
            "maxUsers": normalize_max_users(body.maxUsers),
        }
        servers = load_servers()
        servers.append(server)
        save_servers(servers)
        _db.write_audit_log("server.create", "server", server["id"], {"name": name, "baseUrl": base_url})
        return {"server": {**server_identity(server), "kind": "remote", "status": probe_panel(server)}}


@app.put("/api/servers/{server_id}")
def update_server(server_id: str, body: ServerUpdate, authorization: str | None = Header(None), awg_panel_session: str | None = Cookie(None)):
    auth(authorization, awg_panel_session)
    with data_lock:
        if server_id == LOCAL_SERVER_ID:
            settings = load_local_server_settings()
            name = (body.name.strip() if body.name is not None else settings.get("name") or LOCAL_SERVER_NAME).strip()
            if not name:
                raise HTTPException(400, "Server name is required")
            next_settings = {
                "name": name,
                "maxUsers": normalize_max_users(body.maxUsers if body.maxUsers is not None else settings.get("maxUsers")),
            }
            save_local_server_settings(next_settings)
            return {"server": local_server_identity()}
        servers = load_servers()
        for index, server in enumerate(servers):
            if server.get("id") != server_id:
                continue
            updated = dict(server)
            if body.name is not None:
                updated["name"] = body.name.strip() or server.get("name", "")
            if body.baseUrl is not None:
                updated["baseUrl"] = normalize_panel_url(body.baseUrl)
            if body.token is not None:
                updated["token"] = body.token.strip()
            if body.maxUsers is not None:
                updated["maxUsers"] = normalize_max_users(body.maxUsers)
            if not updated.get("name"):
                raise HTTPException(400, "Server name is required")
            if not updated.get("baseUrl"):
                raise HTTPException(400, "Server URL is required")
            servers[index] = updated
            save_servers(servers)
            _db.write_audit_log("server.update", "server", server_id, {"name": updated.get("name", "")})
            return {"server": {**server_identity(updated), "kind": "remote", "status": probe_panel(updated)}}
        raise HTTPException(404, "Server not found")


@app.delete("/api/servers/{server_id}")
def delete_server(server_id: str, authorization: str | None = Header(None), awg_panel_session: str | None = Cookie(None)):
    auth(authorization, awg_panel_session)
    with data_lock:
        if server_id == LOCAL_SERVER_ID:
            raise HTTPException(400, "Local server cannot be deleted")
        servers = load_servers()
        next_servers = [server for server in servers if server.get("id") != server_id]
        if len(next_servers) == len(servers):
            raise HTTPException(404, "Server not found")
        save_servers(next_servers)
        _db.write_audit_log("server.delete", "server", server_id, {})
        return {"ok": True}


@app.get("/api/orders")
def orders(authorization: str | None = Header(None), awg_panel_session: str | None = Cookie(None)):
    auth(authorization, awg_panel_session)
    with data_lock:
        return {"orders": load_orders()}


@app.post("/api/orders")
def create_order(body: OrderCreate):
    with data_lock:
        login = body.login.strip()
        email = body.email.strip()
        term = body.term.strip() or "1m"
        if not login:
            raise HTTPException(400, "Login is required")
        if not email:
            raise HTTPException(400, "Email is required")
        order: dict = {
            "id": secrets.token_hex(8),
            "login": login,
            "email": email,
            "term": term,
            "status": "pending",
            "created": datetime.now().isoformat(timespec="seconds"),
            "createdAt": datetime.now().isoformat(timespec="seconds"),
        }
        order = process_order_internal(order)
        orders = load_orders()
        orders.insert(0, order)
        save_orders(orders)
        _db.write_audit_log("order.create", "order", order["id"], {"login": login, "email": email, "status": order.get("status", "")})
        if order.get("status") == "issued":
            _wh.send("order.issued", {"orderId": order["id"], "login": login, "email": email, "clientId": order.get("clientId", ""), "serverId": order.get("serverId", "")})
        else:
            _wh.send("order.created", {"orderId": order["id"], "login": login, "email": email, "status": order.get("status", "")})
        return {"order": order}


@app.post("/api/orders/{order_id}/process")
def process_order_endpoint(
    order_id: str,
    authorization: str | None = Header(None),
    awg_panel_session: str | None = Cookie(None),
):
    auth(authorization, awg_panel_session)
    with data_lock:
        orders = load_orders()
        for index, order in enumerate(orders):
            if order.get("id") != order_id:
                continue
            if order.get("status") == "issued":
                raise HTTPException(400, "Order already issued")
            updated = process_order_internal(order)
            orders[index] = updated
            save_orders(orders)
            _db.write_audit_log("order.process", "order", order_id, {"status": updated.get("status", "")})
            if updated.get("status") == "issued":
                _wh.send("order.issued", {"orderId": order_id, "clientId": updated.get("clientId", ""), "serverId": updated.get("serverId", "")})
            return {"order": updated}
        raise HTTPException(404, "Order not found")


@app.patch("/api/orders/{order_id}")
def update_order(order_id: str, body: OrderUpdate, authorization: str | None = Header(None), awg_panel_session: str | None = Cookie(None)):
    auth(authorization, awg_panel_session)
    with data_lock:
        orders = load_orders()
        for index, order in enumerate(orders):
            if order.get("id") != order_id:
                continue
            if body.status is not None:
                order["status"] = body.status.strip() or order.get("status", "active")
            orders[index] = order
            save_orders(orders)
            return {"order": order}
        raise HTTPException(404, "Order not found")


@app.delete("/api/orders/{order_id}")
def delete_order(order_id: str, authorization: str | None = Header(None), awg_panel_session: str | None = Cookie(None)):
    auth(authorization, awg_panel_session)
    with data_lock:
        orders = load_orders()
        next_orders = [order for order in orders if order.get("id") != order_id]
        if len(next_orders) == len(orders):
            raise HTTPException(404, "Order not found")
        save_orders(next_orders)
        _db.write_audit_log("order.delete", "order", order_id, {})
        return {"ok": True}


@app.get("/api/clients")
def clients(
    authorization: str | None = Header(None),
    awg_panel_session: str | None = Cookie(None),
    server_id: str | None = Query(None),
):
    auth(authorization, awg_panel_session)
    if server_id == "all":
        return aggregate_clients_payload()
    server = get_server(server_id)
    if server is not None:
        return panel_json(server, "GET", "/clients")
    return local_clients_payload()


@app.get("/api/expired-clients")
def expired_clients(
    authorization: str | None = Header(None),
    awg_panel_session: str | None = Cookie(None),
    server_id: str | None = Query(None),
):
    auth(authorization, awg_panel_session)
    if server_id == "all":
        return aggregate_expired_clients_payload()
    server = get_server(server_id)
    if server is not None:
        return panel_json(server, "GET", "/expired-clients")
    return {"clients": enforce_expired_clients(), "path": expired_clients_path()}

@app.post("/api/clients")
def create_client(
    body: ClientCreate,
    authorization: str | None = Header(None),
    awg_panel_session: str | None = Cookie(None),
    server_id: str | None = Query(None),
):
    auth(authorization, awg_panel_session)
    server = get_server(server_id)
    if server is not None:
        return panel_json(server, "POST", "/clients", payload=body.model_dump())
    with data_lock:
        name = body.name.strip()
        if not name:
            raise HTTPException(400, "Client name is required")
        text = read_cfg()
        interface = parse_interface(text)
        peers = parse_peers(text)
        private_key = awg(["genkey"])
        public_key = awg(["pubkey"], input_text=private_key)
        expired = load_expired_clients()
        expired.pop(public_key, None)
        save_expired_clients(expired)
        psk = awg(["genpsk"])
        ip = next_ip(interface.get("Address", "10.8.1.1/24"), peers)
        expires_at = expiration_date(body.term)
        expires_line = f"# Expires: {expires_at}\n" if expires_at else ""
        client_id = secrets.token_hex(4)
        created_at = date.today().isoformat()
        peer_block = f"""

[Peer]
# Name: {name}
# ID: {client_id}
# Created: {created_at}
{expires_line}PublicKey = {public_key}
PresharedKey = {psk}
AllowedIPs = {ip}/32
"""
        write_cfg(text.rstrip() + peer_block)
        reload_async()
        meta = load_clients_meta()
        meta[public_key] = {"id": client_id, "contact": body.contact.strip()}
        save_clients_meta(meta)
        server_public = awg(["pubkey"], input_text=interface["PrivateKey"])
        cfg = f"# Client ID: {client_id}\n" + client_config(private_key, ip, server_public, {"PresharedKey": psk}, interface)
        store_client_export(public_key, name, cfg)
        _db.write_audit_log("client.create", "client", public_key, {"name": name, "clientId": client_id, "contact": body.contact.strip()})
        _wh.send("client.created", {"name": name, "publicKey": public_key, "clientId": client_id, "contact": body.contact.strip(), "expiresAt": expires_at})
        return {
            "name": name,
            "publicKey": public_key,
            "clientId": client_id,
            "contact": body.contact.strip(),
            "address": f"{ip}/32",
            "expiresAt": expires_at,
            "createdAt": created_at,
            "config": cfg,
            "configUrl": f"/api/client-config?public_key={public_key}",
        }


@app.post("/api/client-import")
def import_client(
    body: ClientImport,
    authorization: str | None = Header(None),
    awg_panel_session: str | None = Cookie(None),
    server_id: str | None = Query(None),
):
    auth(authorization, awg_panel_session)
    server = get_server(server_id)
    if server is not None:
        return panel_json(server, "POST", "/client-import", payload=body.model_dump())
    with data_lock:
        config_text = body.config.strip()
        if not config_text:
            raise HTTPException(400, "Client config is required")
        public_key = public_key_from_client_config(config_text)
        expired = load_expired_clients()
        expired.pop(public_key, None)
        save_expired_clients(expired)
        name = body.name.strip() or client_name_from_config(config_text) or public_key
        meta = load_clients_meta()
        entry = meta.get(public_key, {})
        if body.contact.strip():
            entry["contact"] = body.contact.strip()
        meta[public_key] = entry
        save_clients_meta(meta)
        store_client_export(public_key, name, config_text)
        _db.write_audit_log("client.import", "client", public_key, {"name": name, "contact": entry.get("contact", "")})
        _wh.send("client.imported", {"name": name, "publicKey": public_key, "contact": entry.get("contact", "")})
        return {
            "name": name,
            "publicKey": public_key,
            "contact": entry.get("contact", ""),
            "config": config_text.rstrip() + "\n",
            "configUrl": f"/api/client-config?public_key={public_key}",
        }

def delete_client_by_key(public_key: str, server_id: str | None = None):
    server = get_server(server_id)
    if server is not None:
        return panel_json(server, "DELETE", f"/clients?public_key={quote(public_key.strip(), safe='')}")
    with data_lock:
        target_key = public_key.strip()
        expired = load_expired_clients()
        expired_removed = expired.pop(target_key, None)
        if expired_removed is not None:
            save_expired_clients(expired)
        meta = load_clients_meta()
        if target_key in meta:
            meta.pop(target_key)
            save_clients_meta(meta)
        text = read_cfg()
        target = public_key.strip()
        chunks = re.split(r"\n(?=\[Peer\])", text)
        kept = []
        found = False
        removed_name = ""
        removed_allowed_ips = ""
        for ch in chunks:
            if ch.strip().startswith("[Peer]"):
                peer_data = {}
                for line in ch.splitlines():
                    if "=" in line and not line.strip().startswith("#"):
                        k, v = line.split("=", 1)
                        peer_data[k.strip()] = v.strip()
                if peer_data.get("PublicKey", "").strip() == target:
                    found = True
                    removed_name = re.search(r"#\s*Name:\s*(.+)", ch)
                    removed_name = removed_name.group(1).strip() if removed_name else ""
                    removed_allowed_ips = peer_data.get("AllowedIPs", "")
                    continue
            kept.append(ch)
        export_path = client_export_path(target)
        export_existed = os.path.exists(export_path)
        if not found and expired_removed is None and not export_existed:
            raise HTTPException(404, "Peer not found")
        if found:
            write_cfg("\n".join(kept))
            remove_runtime_peer(target)
        if export_existed:
            os.remove(export_path)
        if expired_removed is not None and not removed_name:
            removed_name = expired_removed.get("name", "")
        if removed_name:
            named_path = f"{CLIENTS_DIR}/{safe_name(removed_name)}.conf"
            if named_path != export_path and os.path.exists(named_path):
                os.remove(named_path)
        if expired_removed is not None and not removed_allowed_ips:
            removed_allowed_ips = expired_removed.get("AllowedIPs", "")
        if found:
            reload_async()
            __import__('threading').Thread(target=_process_pending_orders_bg, daemon=True).start()
        _db.write_audit_log("client.delete", "client", target_key, {"name": removed_name or (expired_removed or {}).get("name", "")})
        _wh.send("client.deleted", {"publicKey": target_key, "name": removed_name or (expired_removed or {}).get("name", "")})
        return {"ok": True}


@app.delete("/api/clients")
def delete_client_query(
    public_key: str = Query(...),
    authorization: str | None = Header(None),
    awg_panel_session: str | None = Cookie(None),
    server_id: str | None = Query(None),
):
    auth(authorization, awg_panel_session)
    return delete_client_by_key(public_key, server_id)


@app.delete("/api/clients/{public_key}")
def delete_client(
    public_key: str,
    authorization: str | None = Header(None),
    awg_panel_session: str | None = Cookie(None),
    server_id: str | None = Query(None),
):
    auth(authorization, awg_panel_session)
    return delete_client_by_key(public_key, server_id)


def update_client_by_key(public_key: str, body: ClientUpdate, server_id: str | None = None):
    server = get_server(server_id)
    if server is not None:
        return panel_json(server, "PATCH", f"/clients?public_key={quote(public_key.strip(), safe='')}", payload=body.model_dump(exclude_none=True))
    with data_lock:
        target = public_key.strip()
        result = {"ok": True, "publicKey": target}

        if body.contact is not None:
            meta = load_clients_meta()
            entry = meta.get(target, {})
            entry["contact"] = body.contact.strip()
            meta[target] = entry
            save_clients_meta(meta)
            result["contact"] = body.contact.strip()
            _db.write_audit_log("client.update_contact", "client", target, {"contact": body.contact.strip()})

        if body.name is None:
            return result

        new_name = body.name.strip()
        if not new_name:
            raise HTTPException(400, "Client name is required")

        expired = load_expired_clients()
        if target in expired:
            old_name = expired[target].get("name", "")
            expired[target]["name"] = new_name
            save_expired_clients(expired)
            rename_stored_client_export(target, old_name, new_name)
            return {**result, "name": new_name}

        rename_result = rename_peer_block(read_cfg(), target, new_name)
        if rename_result is None:
            raise HTTPException(status_code=404, detail="Client not found")
        next_text, old_name = rename_result
        write_cfg(next_text)
        rename_stored_client_export(target, old_name, new_name)
        reload_async()
        _db.write_audit_log("client.rename", "client", target, {"oldName": old_name, "newName": new_name})
        return {**result, "name": new_name}


@app.patch("/api/clients")
def update_client_query(
    body: ClientUpdate,
    public_key: str = Query(...),
    authorization: str | None = Header(None),
    awg_panel_session: str | None = Cookie(None),
    server_id: str | None = Query(None),
):
    auth(authorization, awg_panel_session)
    return update_client_by_key(public_key, body, server_id)


@app.patch("/api/clients/{public_key}")
def update_client(
    public_key: str,
    body: ClientUpdate,
    authorization: str | None = Header(None),
    awg_panel_session: str | None = Cookie(None),
    server_id: str | None = Query(None),
):
    auth(authorization, awg_panel_session)
    return update_client_by_key(public_key, body, server_id)

@app.get("/api/client-config")
def client_config_export(
    public_key: str,
    authorization: str | None = Header(None),
    awg_panel_session: str | None = Cookie(None),
    server_id: str | None = Query(None),
):
    auth(authorization, awg_panel_session)
    server = get_server(server_id)
    if server is not None:
        raw = panel_bytes(server, "GET", f"/client-config?public_key={public_key}")
        return Response(content=raw, media_type="text/plain; charset=utf-8")
    cfg = load_client_export(public_key)
    if cfg is None:
        raise HTTPException(status_code=404, detail="Client config not found on server")
    return Response(content=cfg, media_type="text/plain; charset=utf-8")


# ─── Renew expired client ─────────────────────────────────────────────────────
def _renew_client_logic(public_key: str, body: ClientRenew, server_id: str | None):
    server = get_server(server_id)
    if server is not None:
        pk_enc = quote(public_key.strip(), safe="")
        return panel_json(server, "POST", f"/clients/renew?public_key={pk_enc}", payload=body.model_dump())
    with data_lock:
        target = public_key.strip()
        expired = load_expired_clients()
        if target not in expired:
            raise HTTPException(404, "Client not in expired list")
        client = expired[target]
        raw = client.get("raw", "").strip()
        if not raw:
            raise HTTPException(400, "No stored peer block for this client")
        new_expiry = expiration_date(body.term)
        if re.search(r"(?m)^#\s*Expires:.*$", raw):
            if new_expiry:
                raw = re.sub(r"(?m)^#\s*Expires:.*$", f"# Expires: {new_expiry}", raw)
            else:
                raw = re.sub(r"(?m)^#\s*Expires:.*\n?", "", raw)
        elif new_expiry:
            raw = re.sub(r"(?m)^\[Peer\]", f"[Peer]\n# Expires: {new_expiry}", raw, count=1)
        text = read_cfg()
        write_cfg(text.rstrip() + "\n\n" + raw + "\n")
        del expired[target]
        save_expired_clients(expired)
        reload_async()
        _db.write_audit_log("client.renew", "client", target, {"name": client.get("name", ""), "term": body.term, "expiresAt": new_expiry})
        _wh.send("client.renewed", {"publicKey": target, "name": client.get("name", ""), "term": body.term, "expiresAt": new_expiry})
        return {"ok": True, "publicKey": target, "expiresAt": new_expiry, "name": client.get("name", "")}


@app.post("/api/clients/renew")
def renew_client_query(
    body: ClientRenew,
    public_key: str = Query(...),
    authorization: str | None = Header(None),
    awg_panel_session: str | None = Cookie(None),
    server_id: str | None = Query(None),
):
    auth(authorization, awg_panel_session)
    return _renew_client_logic(public_key, body, server_id)


@app.post("/api/clients/{public_key}/renew")
def renew_client(
    public_key: str,
    body: ClientRenew,
    authorization: str | None = Header(None),
    awg_panel_session: str | None = Cookie(None),
    server_id: str | None = Query(None),
):
    auth(authorization, awg_panel_session)
    return _renew_client_logic(public_key, body, server_id)


# ─── Update client expiry ────────────────────────────────────────────────────
@app.patch("/api/clients/expiry")
def update_client_expiry(
    public_key: str = Query(...),
    body: ClientExpiry = ClientExpiry(),
    authorization: str | None = Header(None),
    awg_panel_session: str | None = Cookie(None),
    server_id: str | None = Query(None),
):
    auth(authorization, awg_panel_session)
    server = get_server(server_id)
    if server is not None:
        return panel_json(server, "PATCH", f"/clients/expiry?public_key={quote(public_key.strip(), safe='')}", payload=body.model_dump(exclude_none=True))
    with data_lock:
        target = public_key.strip()
        new_expiry = (body.expiresAt or "").strip()
        if new_expiry:
            try:
                date.fromisoformat(new_expiry)
            except ValueError:
                raise HTTPException(400, "Invalid date format. Use YYYY-MM-DD")
        text = read_cfg()
        chunks = re.split(r"\n(?=\[Peer\])", text)
        next_chunks = []
        found = False
        for chunk in chunks:
            peer = peer_from_block(chunk) if chunk.strip().startswith("[Peer]") else {}
            if peer.get("PublicKey", "").strip() != target:
                next_chunks.append(chunk)
                continue
            if re.search(r"(?m)^#\s*Expires:.*$", chunk):
                if new_expiry:
                    chunk = re.sub(r"(?m)^#\s*Expires:.*$", f"# Expires: {new_expiry}", chunk, count=1)
                else:
                    chunk = re.sub(r"(?m)^#\s*Expires:.*\n?", "", chunk)
            elif new_expiry:
                chunk = re.sub(r"(?m)^(PublicKey\s*=)", f"# Expires: {new_expiry}\n\\1", chunk, count=1)
            next_chunks.append(chunk)
            found = True
        if not found:
            raise HTTPException(404, "Client not found in active config")
        write_cfg("\n".join(next_chunks))
        reload_async()
        _db.write_audit_log("client.update_expiry", "client", target, {"expiresAt": new_expiry})
        return {"ok": True, "publicKey": target, "expiresAt": new_expiry}


# ─── Client portal (public, no auth) ─────────────────────────────────────────

def _find_pk_by_client_id(cid: str) -> str | None:
    """Return public key for the given client ID, searching meta → active peers → expired."""
    meta = load_clients_meta()
    pk = next((key for key, m in meta.items() if m.get("id", "") == cid), None)
    if pk:
        return pk
    # Fallback: search active peers in WG config (old clients may not be in meta)
    for peer in parse_peers(read_cfg()):
        if peer.get("clientId", "") == cid:
            return peer.get("PublicKey", "").strip() or None
    # Fallback: search expired clients
    for epk, exp in load_expired_clients().items():
        if exp.get("clientId", "") == cid:
            return epk
    return None


@app.get("/api/portal/lookup-by-id")
def portal_lookup_by_id(client_id: str = Query(...)):
    cid = client_id.strip()
    if not cid:
        raise HTTPException(400, "Client ID is required")
    pk = _find_pk_by_client_id(cid)
    if not pk:
        return {"client": None}
    peers_by_key = {p.get("PublicKey", "").strip(): p for p in parse_peers(read_cfg())}
    expired = load_expired_clients()
    peer = peers_by_key.get(pk)
    if peer:
        return {"client": {
            "name": peer.get("name", ""),
            "clientId": cid,
            "status": "active",
            "expiresAt": peer.get("expiresAt", ""),
            "hasConfig": os.path.exists(client_export_path(pk)),
        }}
    if pk in expired:
        exp = expired[pk]
        return {"client": {
            "name": exp.get("name", ""),
            "clientId": cid,
            "status": "expired",
            "expiresAt": exp.get("expiresAt", ""),
            "hasConfig": os.path.exists(client_export_path(pk)),
        }}
    return {"client": None}


@app.get("/api/portal/config-by-id")
def portal_config_by_id(client_id: str = Query(...)):
    cid = client_id.strip()
    if not cid:
        raise HTTPException(400, "Client ID is required")
    pk = _find_pk_by_client_id(cid)
    if not pk:
        raise HTTPException(404, "Client not found")
    cfg = load_client_export(pk)
    if not cfg:
        raise HTTPException(404, "Config not available. Contact your administrator.")
    return Response(content=cfg, media_type="text/plain; charset=utf-8")


@app.get("/api/portal/verify")
def portal_verify(client_id: str = Query(...), contact: str = Query(...)):
    cid = client_id.strip()
    contact_norm = contact.strip().lower()
    if not cid or not contact_norm:
        raise HTTPException(400, "Client ID and contact are required")
    pk = _find_pk_by_client_id(cid)
    if not pk:
        raise HTTPException(401, "Invalid credentials")
    meta = load_clients_meta()
    stored = meta.get(pk, {}).get("contact", "").strip().lower()
    if not stored or stored != contact_norm:
        raise HTTPException(401, "Invalid credentials")
    peers_by_key = {p.get("PublicKey", "").strip(): p for p in parse_peers(read_cfg())}
    expired = load_expired_clients()
    peer = peers_by_key.get(pk)
    if peer:
        return {"client": {
            "name": peer.get("name", ""),
            "clientId": cid,
            "status": "active",
            "expiresAt": peer.get("expiresAt", ""),
            "hasConfig": os.path.exists(client_export_path(pk)),
        }}
    if pk in expired:
        exp = expired[pk]
        return {"client": {
            "name": exp.get("name", ""),
            "clientId": cid,
            "status": "expired",
            "expiresAt": exp.get("expiresAt", ""),
            "hasConfig": os.path.exists(client_export_path(pk)),
        }}
    raise HTTPException(401, "Invalid credentials")


@app.get("/api/portal/lookup")
def portal_lookup(contact: str = Query(...)):
    contact_norm = contact.strip().lower()
    if not contact_norm:
        raise HTTPException(400, "Contact is required")
    meta = load_clients_meta()
    matching = {pk: m for pk, m in meta.items() if m.get("contact", "").strip().lower() == contact_norm}
    if not matching:
        return {"clients": []}
    peers_by_key = {p.get("PublicKey", "").strip(): p for p in parse_peers(read_cfg())}
    expired = load_expired_clients()
    result = []
    for pk, m in matching.items():
        peer = peers_by_key.get(pk)
        if peer:
            result.append({
                "name": peer.get("name", ""),
                "clientId": m.get("id", ""),
                "status": "active",
                "expiresAt": peer.get("expiresAt", ""),
                "hasConfig": os.path.exists(client_export_path(pk)),
            })
        elif pk in expired:
            exp = expired[pk]
            result.append({
                "name": exp.get("name", ""),
                "clientId": m.get("id", ""),
                "status": "expired",
                "expiresAt": exp.get("expiresAt", ""),
                "hasConfig": os.path.exists(client_export_path(pk)),
            })
    return {"clients": result}


@app.get("/api/portal/config")
def portal_config_download(contact: str = Query(...), client_id: str = Query(...)):
    contact_norm = contact.strip().lower()
    client_id = client_id.strip()
    if not contact_norm or not client_id:
        raise HTTPException(400, "Contact and client ID are required")
    meta = load_clients_meta()
    pk = next(
        (key for key, m in meta.items()
         if m.get("contact", "").strip().lower() == contact_norm and m.get("id", "") == client_id),
        None,
    )
    if not pk:
        raise HTTPException(404, "Client not found")
    cfg = load_client_export(pk)
    if not cfg:
        raise HTTPException(404, "Config not available. Contact your administrator.")
    return Response(content=cfg, media_type="text/plain; charset=utf-8")


# ─── CSV export ───────────────────────────────────────────────────────────────

@app.get("/api/clients/export.csv")
def export_clients_csv(
    authorization: str | None = Header(None),
    awg_panel_session: str | None = Cookie(None),
    server_id: str | None = Query(None),
):
    auth(authorization, awg_panel_session)
    if server_id == "all":
        payload = aggregate_clients_payload()
    else:
        server = get_server(server_id)
        payload = remote_clients_payload(server) if server is not None else local_clients_payload()
    clients = payload.get("clients", [])
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["name", "clientId", "contact", "address", "status",
                    "createdAt", "expiresAt", "publicKey", "serverName"],
        extrasaction="ignore",
    )
    writer.writeheader()
    for c in clients:
        writer.writerow({
            "name": c.get("name", ""),
            "clientId": c.get("clientId", ""),
            "contact": c.get("contact", ""),
            "address": c.get("AllowedIPs", ""),
            "status": "expired" if c.get("blocked") else "active",
            "createdAt": c.get("createdAt", ""),
            "expiresAt": c.get("expiresAt", ""),
            "publicKey": c.get("PublicKey", ""),
            "serverName": c.get("serverName", ""),
        })
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=clients.csv"},
    )


# ─── Audit log ────────────────────────────────────────────────────────────────

@app.get("/api/audit-log")
def get_audit_log(
    authorization: str | None = Header(None),
    awg_panel_session: str | None = Cookie(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    auth(authorization, awg_panel_session)
    return {
        "entries": _db.load_audit_log(limit, offset),
        "total": _db.count_audit_log(),
        "limit": limit,
        "offset": offset,
    }


@app.delete("/api/audit-log")
def clear_audit_log_endpoint(
    authorization: str | None = Header(None),
    awg_panel_session: str | None = Cookie(None),
):
    auth(authorization, awg_panel_session)
    _db.clear_audit_log()
    return {"ok": True}
