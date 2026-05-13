from fastapi import Cookie, FastAPI, HTTPException, Header, Response
from fastapi import Query
from pydantic import BaseModel
import base64, configparser, ipaddress, json, os, re, secrets, shutil, subprocess, time
from threading import RLock
from datetime import date, datetime, timedelta
import urllib.request
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from .config import *

app = FastAPI(title="AmneziaWG Admin")
data_lock = RLock()

class ClientCreate(BaseModel):
    name: str
    term: str = "1m"

class ClientImport(BaseModel):
    name: str = ""
    config: str

class ClientUpdate(BaseModel):
    name: str

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


def awg(args: list[str], input_text: str | None = None) -> str:
    if MOCK_AWG:
        if args in [["genkey"], ["genpsk"]]:
            return mock_key()
        if args == ["pubkey"]:
            return mock_key()
        if args[:2] == ["show", AWG_INTERFACE]:
            return "mock\tlatest-handshake\ttransfer-rx\ttransfer-tx"
    cmd = [AWG_BIN, *args]
    if AWG_DOCKER_CONTAINER:
        cmd = ["docker", "exec", "-i", AWG_DOCKER_CONTAINER, AWG_BIN, *args]
    try:
        return subprocess.check_output(cmd, input=input_text, stderr=subprocess.STDOUT, text=True).strip()
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=e.output.strip() or str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail=f"Command not found: {cmd[0]}")


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


def read_awg_file(host_path: str, container_path: str) -> str | None:
    try:
        if AWG_DOCKER_CONTAINER:
            return docker_exec(["sh", "-c", f"test -f {container_path} && cat {container_path}"])
        if os.path.exists(host_path):
            with open(host_path, "r", encoding="utf-8") as f:
                return f.read()
    except Exception:
        return None
    return None


def write_awg_file(host_path: str, container_path: str, text: str):
    if AWG_DOCKER_CONTAINER:
        docker_exec(["sh", "-c", f"test ! -f {container_path} || cp {container_path} {container_path}.bak.{int(time.time())}"])
        docker_exec(["sh", "-c", f"cat > {container_path}"], text.rstrip() + "\n")
        return
    os.makedirs(os.path.dirname(host_path), exist_ok=True)
    if os.path.exists(host_path):
        shutil.copy2(host_path, f"{host_path}.bak.{int(time.time())}")
    with open(host_path, "w", encoding="utf-8") as f:
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
        for line in chunk.splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()
        peers.append(data)
    return peers


def expired_clients_path() -> str:
    os.makedirs(CLIENTS_DIR, exist_ok=True)
    return f"{CLIENTS_DIR}/expired-clients.json"


def load_expired_clients() -> dict:
    path = expired_clients_path()
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_expired_clients(clients: dict):
    with open(expired_clients_path(), "w", encoding="utf-8") as f:
        json.dump(clients, f, ensure_ascii=False, indent=2, sort_keys=True)


def servers_path() -> str:
    os.makedirs(os.path.dirname(SERVERS_PATH), exist_ok=True)
    return SERVERS_PATH


def load_servers() -> list[dict]:
    path = servers_path()
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("servers", [])
    if not isinstance(data, list):
        return []
    return [server for server in data if isinstance(server, dict)]


def save_servers(servers: list[dict]):
    with open(servers_path(), "w", encoding="utf-8") as f:
        json.dump(servers, f, ensure_ascii=False, indent=2, sort_keys=True)


def load_local_server_settings() -> dict:
    os.makedirs(os.path.dirname(LOCAL_SERVER_PATH), exist_ok=True)
    if not os.path.exists(LOCAL_SERVER_PATH):
        return {}
    with open(LOCAL_SERVER_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def save_local_server_settings(settings: dict):
    os.makedirs(os.path.dirname(LOCAL_SERVER_PATH), exist_ok=True)
    with open(LOCAL_SERVER_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2, sort_keys=True)


def orders_path() -> str:
    os.makedirs(os.path.dirname(ORDERS_PATH), exist_ok=True)
    return ORDERS_PATH


def load_orders() -> list[dict]:
    path = orders_path()
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("orders", [])
    if not isinstance(data, list):
        return []
    return [order for order in data if isinstance(order, dict)]


def save_orders(orders: list[dict]):
    with open(orders_path(), "w", encoding="utf-8") as f:
        json.dump(orders, f, ensure_ascii=False, indent=2, sort_keys=True)


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
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                return "online"
    except Exception:
        return "offline"
    return "offline"


def list_servers(include_local: bool = True) -> list[dict]:
    result = []
    if include_local:
        result.append(local_server_identity())
    for server in load_servers():
        item = server_identity(server)
        item["status"] = probe_panel(server)
        item["kind"] = "remote"
        result.append(item)
    return result


def local_clients_payload() -> dict:
    local_name = local_server_identity()["name"]
    expired_clients = attach_client_source(apply_client_table_names(enforce_expired_clients()), LOCAL_SERVER_ID, local_name)
    peers = attach_client_source(apply_client_table_names(parse_peers(read_cfg())), LOCAL_SERVER_ID, local_name)
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


def panel_request(server: dict, method: str, path: str, body: bytes | None = None, content_type: str = "application/json") -> tuple[int, bytes, str]:
    headers = {}
    token = server.get("token", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = content_type
    url = f"{server['baseUrl'].rstrip('/')}/api{path}"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read(), resp.headers.get_content_type()
    except HTTPError as e:
        return e.code, e.read(), e.headers.get_content_type() if e.headers else "text/plain"
    except URLError as e:
        raise HTTPException(status_code=502, detail=f"Panel unreachable: {e.reason}")


def panel_json(server: dict, method: str, path: str, payload: dict | None = None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    status, raw, content_type = panel_request(server, method, path, body=body)
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
    return sorted(
        clients.values(),
        key=lambda client: (client.get("expiresAt", ""), client.get("name", "")),
    )


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
    if term == "admin":
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


CLIENT_TABLE_OUTER_KEY_FIELD = "__awgPanelTableKey"
CLIENT_TABLE_PUBLIC_KEY_FIELDS = [
    "PublicKey",
    "publicKey",
    "public_key",
    "clientPublicKey",
    "client_public_key",
    "clientId",
    "client_id",
]
CLIENT_TABLE_NAME_FIELDS = [
    "name",
    "clientName",
    "client_name",
    "displayName",
    "display_name",
    "Name",
    "username",
    "userName",
    "description",
    "Description",
    "comment",
    "label",
    "title",
]
CLIENT_TABLE_ADDRESS_FIELDS = [
    "AllowedIPs",
    "allowedIPs",
    "allowedIps",
    "allowed_ips",
    "address",
    "Address",
    "clientAddress",
    "client_address",
    "ip",
    "clientIp",
]
CLIENT_TABLE_CREATED_FIELDS = [
    "createdAt",
    "created_at",
    "created",
    "creationDate",
    "creation_date",
    "createdDate",
    "dateCreated",
    "timestamp",
]


def client_table_load():
    raw = read_awg_file(AWG_CLIENTS_TABLE_PATH, AWG_CONTAINER_CLIENTS_TABLE_PATH)
    if raw is None or not raw.strip():
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def client_table_save(data):
    if data is None:
        return
    write_awg_file(
        AWG_CLIENTS_TABLE_PATH,
        AWG_CONTAINER_CLIENTS_TABLE_PATH,
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
    )


def client_table_entries(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("clients"), list):
            return data["clients"]
        if isinstance(data.get("data"), list):
            return data["data"]
        entries = []
        for key, value in data.items():
            if not isinstance(value, dict):
                continue
            entry = dict(value)
            entry.setdefault(CLIENT_TABLE_OUTER_KEY_FIELD, str(key))
            entries.append(entry)
        return entries
    return []


def client_table_value(entry: dict, fields: list[str]) -> str:
    if not isinstance(entry, dict):
        return ""
    for field in fields:
        value = entry.get(field)
        if value is not None and str(value).strip():
            return str(value).strip()
    for value in entry.values():
        if isinstance(value, dict):
            nested = client_table_value(value, fields)
            if nested:
                return nested
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    nested = client_table_value(item, fields)
                    if nested:
                        return nested
    return ""


def client_table_config_ips(entry: dict) -> set[str]:
    ips = set()

    def scan(value):
        if isinstance(value, dict):
            for item in value.values():
                scan(item)
            return
        if isinstance(value, list):
            for item in value:
                scan(item)
            return
        if not isinstance(value, str) or "=" not in value:
            return
        for key in ["Address", "AllowedIPs"]:
            for match in re.finditer(rf"(?m)^\s*{key}\s*=\s*(.+?)\s*$", value):
                for part in match.group(1).split(","):
                    part = part.strip()
                    if part:
                        ips.add(part.split("/")[0])

    scan(entry)
    return ips


def client_table_address_matches(entry: dict, allowed_ips: str) -> bool:
    if not allowed_ips:
        return False
    target_ips = {part.strip().split("/")[0] for part in allowed_ips.split(",") if part.strip()}
    entry_value = client_table_value(entry, CLIENT_TABLE_ADDRESS_FIELDS)
    entry_ips = {part.strip().split("/")[0] for part in entry_value.split(",") if part.strip()}
    entry_ips |= client_table_config_ips(entry)
    return bool(target_ips and entry_ips and target_ips & entry_ips)


def apply_client_table_names(clients: list[dict]) -> list[dict]:
    data = client_table_load()
    entries = client_table_entries(data)
    if not entries:
        return clients
    for client in clients:
        public_key = client.get("PublicKey", "").strip()
        allowed_ips = client.get("AllowedIPs", "").strip()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_public_key = client_table_value(entry, CLIENT_TABLE_PUBLIC_KEY_FIELDS)
            if entry_public_key and entry_public_key != public_key:
                continue
            if not entry_public_key and not client_table_address_matches(entry, allowed_ips):
                continue
            name = client_table_value(entry, CLIENT_TABLE_NAME_FIELDS) or entry.get(CLIENT_TABLE_OUTER_KEY_FIELD, "").strip()
            if name:
                client["name"] = name
            created_at = client_table_value(entry, CLIENT_TABLE_CREATED_FIELDS)
            if created_at:
                client["createdAt"] = created_at
            break
    return clients


def client_table_upsert(public_key: str, name: str, allowed_ips: str = ""):
    data = client_table_load()
    if data is None:
        return
    if not isinstance(data, (list, dict)):
        data = []
    if isinstance(data, dict) and not isinstance(data.get("clients"), list) and not isinstance(data.get("data"), list):
        entry = data.get(public_key)
        if not isinstance(entry, dict):
            for value in data.values():
                if not isinstance(value, dict):
                    continue
                if client_table_value(value, CLIENT_TABLE_PUBLIC_KEY_FIELDS) == public_key or client_table_address_matches(value, allowed_ips):
                    entry = value
                    break
        if isinstance(entry, dict):
            entry["name"] = name
            entry.setdefault("PublicKey", public_key)
            entry.setdefault("createdAt", date.today().isoformat())
            if allowed_ips:
                entry.setdefault("AllowedIPs", allowed_ips)
        else:
            data[public_key] = {"PublicKey": public_key, "name": name, "AllowedIPs": allowed_ips, "createdAt": date.today().isoformat()}
        client_table_save(data)
        return
    entries = client_table_entries(data)
    target = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if client_table_value(entry, CLIENT_TABLE_PUBLIC_KEY_FIELDS) == public_key:
            target = entry
            break
        if not client_table_value(entry, CLIENT_TABLE_PUBLIC_KEY_FIELDS) and client_table_address_matches(entry, allowed_ips):
            target = entry
            break
    if target is None:
        target = {"PublicKey": public_key, "createdAt": date.today().isoformat()}
        entries.append(target)
    target["name"] = name
    target.setdefault("PublicKey", public_key)
    target.setdefault("createdAt", date.today().isoformat())
    if allowed_ips:
        target.setdefault("AllowedIPs", allowed_ips)
    client_table_save(data)


def client_table_delete(public_key: str, allowed_ips: str = ""):
    data = client_table_load()
    if data is None:
        return
    if isinstance(data, dict) and public_key in data:
        data.pop(public_key, None)
        client_table_save(data)
        return
    if isinstance(data, dict) and not isinstance(data.get("clients"), list) and not isinstance(data.get("data"), list):
        for key, value in list(data.items()):
            if not isinstance(value, dict):
                continue
            if client_table_value(value, CLIENT_TABLE_PUBLIC_KEY_FIELDS) == public_key or client_table_address_matches(value, allowed_ips):
                data.pop(key, None)
                client_table_save(data)
                return
    entries = client_table_entries(data)
    for index, entry in enumerate(list(entries)):
        if not isinstance(entry, dict):
            continue
        if client_table_value(entry, CLIENT_TABLE_PUBLIC_KEY_FIELDS) == public_key or client_table_address_matches(entry, allowed_ips):
            entries.pop(index)
            client_table_save(data)
            return


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


def reload_service():
    if MOCK_AWG or not RELOAD_COMMAND:
        return
    result = subprocess.run(RELOAD_COMMAND, shell=True, text=True, capture_output=True)
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=(result.stderr or result.stdout or "Reload failed").strip())

@app.get("/api/health")
def health():
    return {"ok": True, "interface": AWG_INTERFACE, "mock": MOCK_AWG}

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
        term = body.term.strip() or "1 месяц"
        if not login:
            raise HTTPException(400, "Login is required")
        if not email:
            raise HTTPException(400, "Email is required")
        order = {
            "id": secrets.token_hex(8),
            "login": login,
            "email": email,
            "term": term,
            "status": "active",
            "created": datetime.now().isoformat(timespec="seconds"),
            "createdAt": datetime.now().isoformat(timespec="seconds"),
        }
        orders = load_orders()
        orders.insert(0, order)
        save_orders(orders)
        return {"order": order}


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
        peer_block = f"""

[Peer]
# Name: {name}
{expires_line}PublicKey = {public_key}
PresharedKey = {psk}
AllowedIPs = {ip}/32
"""
        write_cfg(text.rstrip() + peer_block)
        client_table_upsert(public_key, name, f"{ip}/32")
        reload_service()
        server_public = awg(["pubkey"], input_text=interface["PrivateKey"])
        cfg = client_config(private_key, ip, server_public, {"PresharedKey": psk}, interface)
        store_client_export(public_key, name, cfg)
        return {
            "name": name,
            "publicKey": public_key,
            "address": f"{ip}/32",
            "expiresAt": expires_at,
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
        store_client_export(public_key, name, config_text)
        client_table_upsert(public_key, name)
        return {
            "name": name,
            "publicKey": public_key,
            "config": config_text.rstrip() + "\n",
            "configUrl": f"/api/client-config?public_key={public_key}",
        }

def delete_client_by_key(public_key: str, server_id: str | None = None):
    server = get_server(server_id)
    if server is not None:
        return panel_json(server, "DELETE", f"/clients?public_key={quote(public_key.strip(), safe='')}")
    with data_lock:
        expired = load_expired_clients()
        expired_removed = expired.pop(public_key.strip(), None)
        if expired_removed is not None:
            save_expired_clients(expired)
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
        client_table_delete(target, removed_allowed_ips)
        if found:
            reload_service()
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
        return panel_json(server, "PATCH", f"/clients?public_key={quote(public_key.strip(), safe='')}", payload=body.model_dump())
    with data_lock:
        new_name = body.name.strip()
        if not new_name:
            raise HTTPException(400, "Client name is required")
        target = public_key.strip()
        expired = load_expired_clients()
        if target in expired:
            old_name = expired[target].get("name", "")
            expired[target]["name"] = new_name
            save_expired_clients(expired)
            rename_stored_client_export(target, old_name, new_name)
            client_table_upsert(target, new_name, expired[target].get("AllowedIPs", ""))
            return {"ok": True, "publicKey": target, "name": new_name}
        result = rename_peer_block(read_cfg(), target, new_name)
        if result is None:
            raise HTTPException(status_code=404, detail="Client not found")
        next_text, old_name = result
        write_cfg(next_text)
        rename_stored_client_export(target, old_name, new_name)
        updated_peer = peer_from_block(next((chunk for chunk in re.split(r"\n(?=\[Peer\])", next_text) if target in chunk), ""))
        client_table_upsert(target, new_name, updated_peer.get("AllowedIPs", ""))
        reload_service()
        return {"ok": True, "publicKey": target, "name": new_name}


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
