"""Integration tests for API endpoints (MOCK_AWG=true, SQLite in temp dir)."""


# ─── Health ───────────────────────────────────────────────────────────────────

def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["mock"] is True


# ─── Auth ─────────────────────────────────────────────────────────────────────

def test_login_success(client):
    r = client.post("/api/login", json={"username": "admin", "password": "password"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_login_wrong_password(client):
    r = client.post("/api/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_clients_unauth(clean_client):
    r = clean_client.get("/api/clients")
    assert r.status_code == 401


# ─── Clients CRUD ─────────────────────────────────────────────────────────────

def test_clients_empty(client, auth):
    r = client.get("/api/clients", headers=auth)
    assert r.status_code == 200
    assert "clients" in r.json()


def test_create_client(client, auth):
    r = client.post("/api/clients", json={"name": "TestClient", "term": "1m"}, headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "TestClient"
    assert data["publicKey"]
    assert data["clientId"]
    assert data["config"]


def test_create_client_no_name(client, auth):
    r = client.post("/api/clients", json={"name": "", "term": "1m"}, headers=auth)
    assert r.status_code == 400


def test_create_client_with_contact(client, auth):
    r = client.post(
        "/api/clients",
        json={"name": "ContactClient", "term": "1m", "contact": "test@example.com"},
        headers=auth,
    )
    assert r.status_code == 200
    assert r.json()["contact"] == "test@example.com"


def test_create_client_forever(client, auth):
    r = client.post("/api/clients", json={"name": "AdminClient", "term": "admin"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["expiresAt"] == ""


def test_update_client_name(client, auth):
    create = client.post("/api/clients", json={"name": "OldName", "term": "1m"}, headers=auth)
    pk = create.json()["publicKey"]
    r = client.patch("/api/clients", params={"public_key": pk}, json={"name": "NewName"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["name"] == "NewName"


def test_update_client_contact(client, auth):
    create = client.post("/api/clients", json={"name": "ContactUpdate", "term": "1m"}, headers=auth)
    pk = create.json()["publicKey"]
    r = client.patch("/api/clients", params={"public_key": pk}, json={"contact": "new@email.com"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["contact"] == "new@email.com"


def test_delete_client(client, auth):
    create = client.post("/api/clients", json={"name": "ToDelete", "term": "1m"}, headers=auth)
    pk = create.json()["publicKey"]
    r = client.delete("/api/clients", params={"public_key": pk}, headers=auth)
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_delete_nonexistent_client(client, auth):
    r = client.delete("/api/clients", params={"public_key": "nonexistentkey=="}, headers=auth)
    assert r.status_code == 404


def test_client_config_download(client, auth):
    create = client.post("/api/clients", json={"name": "ConfigClient", "term": "1m"}, headers=auth)
    pk = create.json()["publicKey"]
    r = client.get(f"/api/client-config?public_key={pk}", headers=auth)
    assert r.status_code == 200
    assert "[Interface]" in r.text


# ─── Servers ──────────────────────────────────────────────────────────────────

def test_servers_list(client, auth):
    r = client.get("/api/servers", headers=auth)
    assert r.status_code == 200
    servers = r.json()["servers"]
    assert any(s["kind"] == "local" for s in servers)


def test_create_server_missing_token(client, auth):
    r = client.post(
        "/api/servers",
        json={"name": "VPS 1", "baseUrl": "http://1.2.3.4:8080", "token": ""},
        headers=auth,
    )
    assert r.status_code == 400


def test_create_and_delete_server(client, auth):
    r = client.post(
        "/api/servers",
        json={"name": "VPS Test", "baseUrl": "http://10.0.0.1:8080", "token": "secret"},
        headers=auth,
    )
    assert r.status_code == 200
    server_id = r.json()["server"]["id"]

    r = client.delete(f"/api/servers/{server_id}", headers=auth)
    assert r.status_code == 200


# ─── Orders ───────────────────────────────────────────────────────────────────

def test_orders_list(client, auth):
    r = client.get("/api/orders", headers=auth)
    assert r.status_code == 200
    assert "orders" in r.json()


def test_create_order(client, auth):
    r = client.post(
        "/api/orders",
        json={"login": "user123", "email": "user@example.com", "term": "1 месяц"},
    )
    assert r.status_code == 200
    order = r.json()["order"]
    assert order["login"] == "user123"
    assert order["status"] in ("issued", "pending")


def test_create_order_missing_login(client, auth):
    r = client.post("/api/orders", json={"login": "", "email": "x@x.com"})
    assert r.status_code == 400


def test_delete_order(client, auth):
    create = client.post("/api/orders", json={"login": "todel", "email": "x@x.com"})
    order_id = create.json()["order"]["id"]
    r = client.delete(f"/api/orders/{order_id}", headers=auth)
    assert r.status_code == 200


# ─── CSV export ───────────────────────────────────────────────────────────────

def test_export_csv_unauth(clean_client):
    r = clean_client.get("/api/clients/export.csv")
    assert r.status_code == 401


def test_export_csv(client, auth):
    client.post("/api/clients", json={"name": "CsvClient", "term": "1m"}, headers=auth)
    r = client.get("/api/clients/export.csv", headers=auth)
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("name,")
    assert len(lines) >= 2  # header + at least one client


# ─── Audit log ────────────────────────────────────────────────────────────────

def test_audit_log_unauth(clean_client):
    r = clean_client.get("/api/audit-log")
    assert r.status_code == 401


def test_audit_log_has_entries(client, auth):
    # Previous tests created clients → audit log should have entries
    r = client.get("/api/audit-log", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert "entries" in data
    assert "total" in data
    assert data["total"] >= 0


def test_audit_log_pagination(client, auth):
    r = client.get("/api/audit-log?limit=2&offset=0", headers=auth)
    assert r.status_code == 200
    assert len(r.json()["entries"]) <= 2


def test_audit_log_entry_structure(client, auth):
    r = client.get("/api/audit-log?limit=1", headers=auth)
    entries = r.json()["entries"]
    if entries:
        e = entries[0]
        assert "id" in e
        assert "timestamp" in e
        assert "action" in e
        assert "entityType" in e
        assert "entityId" in e
        assert "details" in e


def test_clear_audit_log(client, auth):
    client.post("/api/clients", json={"name": "ClearTest", "term": "1m"}, headers=auth)
    r = client.delete("/api/audit-log", headers=auth)
    assert r.status_code == 200
    r = client.get("/api/audit-log", headers=auth)
    assert r.json()["total"] == 0


# ─── Portal ───────────────────────────────────────────────────────────────────

def test_portal_lookup_by_id_not_found(client):
    r = client.get("/api/portal/lookup-by-id?client_id=nosuchid")
    assert r.status_code == 200
    assert r.json()["client"] is None


def test_portal_lookup_by_id_found(client, auth):
    create = client.post(
        "/api/clients",
        json={"name": "PortalClient", "term": "1m", "contact": "portal@test.com"},
        headers=auth,
    )
    client_id = create.json()["clientId"]
    r = client.get(f"/api/portal/lookup-by-id?client_id={client_id}")
    assert r.status_code == 200
    data = r.json()["client"]
    assert data is not None
    assert data["clientId"] == client_id
    assert data["status"] == "active"


# ─── Portal verify ────────────────────────────────────────────────────────────

def test_portal_verify_success(client, auth):
    create = client.post(
        "/api/clients",
        json={"name": "VerifyClient", "term": "1m", "contact": "verify@test.com"},
        headers=auth,
    )
    client_id = create.json()["clientId"]
    r = client.get(f"/api/portal/verify?client_id={client_id}&contact=verify@test.com")
    assert r.status_code == 200
    data = r.json()["client"]
    assert data["clientId"] == client_id
    assert data["status"] == "active"


def test_portal_verify_wrong_email(client, auth):
    create = client.post(
        "/api/clients",
        json={"name": "VerifyBad", "term": "1m", "contact": "real@test.com"},
        headers=auth,
    )
    client_id = create.json()["clientId"]
    r = client.get(f"/api/portal/verify?client_id={client_id}&contact=wrong@test.com")
    assert r.status_code == 401


def test_portal_verify_unknown_id(client):
    r = client.get("/api/portal/verify?client_id=nosuchid&contact=any@test.com")
    assert r.status_code == 401
