import json
import os
import sqlite3
from datetime import datetime, timezone

_DB_PATH: str = ""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str):
    global _DB_PATH
    _DB_PATH = db_path
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    _create_schema()


def _create_schema():
    conn = _connect()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS clients_meta (
                public_key   TEXT PRIMARY KEY,
                client_id    TEXT DEFAULT '',
                contact      TEXT DEFAULT '',
                created_at   TEXT DEFAULT '',
                config_patched INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS expired_clients (
                public_key TEXT PRIMARY KEY,
                data       TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS servers (
                id        TEXT PRIMARY KEY,
                name      TEXT NOT NULL,
                base_url  TEXT NOT NULL,
                token     TEXT DEFAULT '',
                max_users INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS orders (
                id         TEXT PRIMARY KEY,
                data       TEXT NOT NULL,
                created_at TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT NOT NULL,
                action      TEXT NOT NULL,
                entity_type TEXT DEFAULT '',
                entity_id   TEXT DEFAULT '',
                details     TEXT DEFAULT ''
            );
        """)
    finally:
        conn.close()


def migrate_from_json(
    expired_path: str,
    meta_path: str,
    servers_json_path: str,
    orders_json_path: str,
    local_server_json_path: str,
):
    """Import existing JSON files into SQLite on first run (tables empty → import)."""
    conn = _connect()
    try:
        if conn.execute("SELECT COUNT(*) FROM clients_meta").fetchone()[0] == 0:
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    for pk, m in meta.items():
                        conn.execute(
                            "INSERT OR IGNORE INTO clients_meta "
                            "(public_key, client_id, contact, created_at, config_patched) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (pk, m.get("id", ""), m.get("contact", ""),
                             m.get("createdAt", ""), 1 if m.get("configPatched") else 0),
                        )
                except Exception:
                    pass

        if conn.execute("SELECT COUNT(*) FROM expired_clients").fetchone()[0] == 0:
            if os.path.exists(expired_path):
                try:
                    with open(expired_path, "r", encoding="utf-8") as f:
                        expired = json.load(f)
                    for pk, data in expired.items():
                        conn.execute(
                            "INSERT OR IGNORE INTO expired_clients (public_key, data) VALUES (?, ?)",
                            (pk, json.dumps(data, ensure_ascii=False)),
                        )
                except Exception:
                    pass

        if conn.execute("SELECT COUNT(*) FROM servers").fetchone()[0] == 0:
            if os.path.exists(servers_json_path):
                try:
                    with open(servers_json_path, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    srv_list = raw if isinstance(raw, list) else raw.get("servers", [])
                    for s in srv_list:
                        if isinstance(s, dict):
                            conn.execute(
                                "INSERT OR IGNORE INTO servers "
                                "(id, name, base_url, token, max_users) VALUES (?, ?, ?, ?, ?)",
                                (s.get("id", ""), s.get("name", ""), s.get("baseUrl", ""),
                                 s.get("token", ""), s.get("maxUsers") or 0),
                            )
                except Exception:
                    pass

        if conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0:
            if os.path.exists(orders_json_path):
                try:
                    with open(orders_json_path, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    ord_list = raw if isinstance(raw, list) else raw.get("orders", [])
                    for o in ord_list:
                        if isinstance(o, dict):
                            conn.execute(
                                "INSERT OR IGNORE INTO orders (id, data, created_at) VALUES (?, ?, ?)",
                                (o.get("id", ""), json.dumps(o, ensure_ascii=False),
                                 o.get("createdAt", "")),
                            )
                except Exception:
                    pass

        if conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0:
            if os.path.exists(local_server_json_path):
                try:
                    with open(local_server_json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        for k, v in data.items():
                            conn.execute(
                                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                                (f"local_server.{k}", str(v)),
                            )
                except Exception:
                    pass

        conn.commit()
    finally:
        conn.close()


def prune_orphan_meta(active_keys: set, expired_keys: set) -> int:
    """Remove clients_meta rows whose peer is neither active in AWG config nor expired."""
    conn = _connect()
    try:
        rows = conn.execute("SELECT public_key FROM clients_meta").fetchall()
        orphans = [r[0] for r in rows if r[0] not in active_keys and r[0] not in expired_keys]
        for pk in orphans:
            conn.execute("DELETE FROM clients_meta WHERE public_key = ?", (pk,))
        conn.commit()
        return len(orphans)
    finally:
        conn.close()


# ─── clients_meta ──────────────────────────────────────────────────────────────

def load_clients_meta() -> dict:
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM clients_meta").fetchall()
        return {
            row["public_key"]: {
                "id": row["client_id"],
                "contact": row["contact"],
                "createdAt": row["created_at"],
                "configPatched": bool(row["config_patched"]),
            }
            for row in rows
        }
    finally:
        conn.close()


def save_clients_meta(meta: dict):
    conn = _connect()
    try:
        existing = {r[0] for r in conn.execute("SELECT public_key FROM clients_meta").fetchall()}
        for pk in existing - set(meta):
            conn.execute("DELETE FROM clients_meta WHERE public_key = ?", (pk,))
        for pk, m in meta.items():
            conn.execute(
                "INSERT INTO clients_meta (public_key, client_id, contact, created_at, config_patched) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(public_key) DO UPDATE SET "
                "client_id=excluded.client_id, contact=excluded.contact, "
                "created_at=excluded.created_at, config_patched=excluded.config_patched",
                (pk, m.get("id", ""), m.get("contact", ""),
                 m.get("createdAt", ""), 1 if m.get("configPatched") else 0),
            )
        conn.commit()
    finally:
        conn.close()


# ─── expired_clients ───────────────────────────────────────────────────────────

def load_expired_clients() -> dict:
    conn = _connect()
    try:
        rows = conn.execute("SELECT public_key, data FROM expired_clients").fetchall()
        return {row["public_key"]: json.loads(row["data"]) for row in rows}
    finally:
        conn.close()


def save_expired_clients(clients: dict):
    conn = _connect()
    try:
        existing = {r[0] for r in conn.execute("SELECT public_key FROM expired_clients").fetchall()}
        for pk in existing - set(clients):
            conn.execute("DELETE FROM expired_clients WHERE public_key = ?", (pk,))
        for pk, data in clients.items():
            conn.execute(
                "INSERT INTO expired_clients (public_key, data) VALUES (?, ?) "
                "ON CONFLICT(public_key) DO UPDATE SET data=excluded.data",
                (pk, json.dumps(data, ensure_ascii=False)),
            )
        conn.commit()
    finally:
        conn.close()


# ─── servers ───────────────────────────────────────────────────────────────────

def load_servers() -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM servers").fetchall()
        return [
            {"id": r["id"], "name": r["name"], "baseUrl": r["base_url"],
             "token": r["token"], "maxUsers": r["max_users"]}
            for r in rows
        ]
    finally:
        conn.close()


def save_servers(servers: list[dict]):
    conn = _connect()
    try:
        conn.execute("DELETE FROM servers")
        for s in servers:
            conn.execute(
                "INSERT INTO servers (id, name, base_url, token, max_users) VALUES (?, ?, ?, ?, ?)",
                (s.get("id", ""), s.get("name", ""), s.get("baseUrl", ""),
                 s.get("token", ""), s.get("maxUsers") or 0),
            )
        conn.commit()
    finally:
        conn.close()


# ─── orders ────────────────────────────────────────────────────────────────────

def load_orders() -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT data FROM orders ORDER BY created_at DESC, rowid DESC"
        ).fetchall()
        return [json.loads(r["data"]) for r in rows]
    finally:
        conn.close()


def save_orders(orders: list[dict]):
    conn = _connect()
    try:
        conn.execute("DELETE FROM orders")
        for o in orders:
            conn.execute(
                "INSERT INTO orders (id, data, created_at) VALUES (?, ?, ?)",
                (o.get("id", ""), json.dumps(o, ensure_ascii=False), o.get("createdAt", "")),
            )
        conn.commit()
    finally:
        conn.close()


# ─── local server settings ────────────────────────────────────────────────────

def load_local_server_settings() -> dict:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT key, value FROM settings WHERE key LIKE 'local_server.%'"
        ).fetchall()
        result = {}
        for row in rows:
            k = row["key"][len("local_server."):]
            v: str | int = row["value"]
            if k == "maxUsers":
                try:
                    v = int(v)
                except (ValueError, TypeError):
                    v = 0
            result[k] = v
        return result
    finally:
        conn.close()


def save_local_server_settings(settings: dict):
    conn = _connect()
    try:
        conn.execute("DELETE FROM settings WHERE key LIKE 'local_server.%'")
        for k, v in settings.items():
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                (f"local_server.{k}", str(v)),
            )
        conn.commit()
    finally:
        conn.close()


# ─── audit_log ────────────────────────────────────────────────────────────────

def write_audit_log(action: str, entity_type: str = "", entity_id: str = "", details: dict | None = None):
    try:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO audit_log (timestamp, action, entity_type, entity_id, details) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    action,
                    entity_type,
                    entity_id,
                    json.dumps(details or {}, ensure_ascii=False),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def load_audit_log(limit: int = 100, offset: int = 0) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, timestamp, action, entity_type, entity_id, details "
            "FROM audit_log ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "timestamp": r["timestamp"],
                "action": r["action"],
                "entityType": r["entity_type"],
                "entityId": r["entity_id"],
                "details": json.loads(r["details"]) if r["details"] else {},
            }
            for r in rows
        ]
    finally:
        conn.close()


def clear_audit_log():
    conn = _connect()
    try:
        conn.execute("DELETE FROM audit_log")
        conn.commit()
    finally:
        conn.close()


def count_audit_log() -> int:
    conn = _connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    finally:
        conn.close()
