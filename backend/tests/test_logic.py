"""Unit tests for pure logic functions (no network, no subprocess)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from datetime import date, timedelta
from fastapi import HTTPException

from app.main import (
    next_ip,
    expiration_date,
    parse_peers,
    parse_interface,
    normalize_term,
    safe_name,
    is_expired_date,
    add_months,
    client_name_from_config,
)


# ─── next_ip ──────────────────────────────────────────────────────────────────

def test_next_ip_no_peers():
    ip = next_ip("10.8.1.1/24", [])
    assert ip == "10.8.1.2"


def test_next_ip_skips_used():
    peers = [{"AllowedIPs": "10.8.1.2/32"}, {"AllowedIPs": "10.8.1.3/32"}]
    assert next_ip("10.8.1.1/24", peers) == "10.8.1.4"


def test_next_ip_skips_interface():
    # .1 is the interface address — should never be assigned
    assert next_ip("10.8.1.1/24", []) == "10.8.1.2"


def test_next_ip_multiple_allowed_ips():
    peers = [{"AllowedIPs": "10.8.1.2/32, 10.8.1.3/32"}]
    assert next_ip("10.8.1.1/24", peers) == "10.8.1.4"


# ─── expiration_date ──────────────────────────────────────────────────────────

def test_expiration_1d():
    exp = expiration_date("1d")
    assert exp == (date.today() + timedelta(days=1)).isoformat()


def test_expiration_1m():
    exp = expiration_date("1m")
    today = date.today()
    expected = add_months(today, 1).isoformat()
    assert exp == expected


def test_expiration_1y():
    exp = expiration_date("1y")
    today = date.today()
    assert exp == add_months(today, 12).isoformat()


def test_expiration_admin_returns_empty():
    assert expiration_date("admin") == ""


def test_expiration_forever_returns_empty():
    assert expiration_date("forever") == ""


def test_expiration_invalid_raises():
    with pytest.raises(HTTPException) as exc:
        expiration_date("invalid_term")
    assert exc.value.status_code == 400


# ─── parse_interface ──────────────────────────────────────────────────────────

_SAMPLE_CFG = """
[Interface]
PrivateKey = abc123
Address = 10.8.1.1/24
ListenPort = 51820
Jc = 4

[Peer]
# Name: Test
PublicKey = pubkey1
AllowedIPs = 10.8.1.2/32
"""


def test_parse_interface_keys():
    iface = parse_interface(_SAMPLE_CFG)
    assert iface["PrivateKey"] == "abc123"
    assert iface["Address"] == "10.8.1.1/24"
    assert iface["ListenPort"] == "51820"
    assert iface["Jc"] == "4"


# ─── parse_peers ──────────────────────────────────────────────────────────────

def test_parse_peers_basic():
    peers = parse_peers(_SAMPLE_CFG)
    assert len(peers) == 1
    assert peers[0]["name"] == "Test"
    assert peers[0]["PublicKey"] == "pubkey1"
    assert peers[0]["AllowedIPs"] == "10.8.1.2/32"


def test_parse_peers_empty():
    assert parse_peers("[Interface]\nPrivateKey = x") == []


def test_parse_peers_with_expiry():
    cfg = """
[Interface]
PrivateKey = x

[Peer]
# Name: Expired
# Expires: 2020-01-01
PublicKey = pk2
AllowedIPs = 10.8.1.3/32
"""
    peers = parse_peers(cfg)
    assert peers[0]["expiresAt"] == "2020-01-01"


def test_parse_peers_with_id_and_created():
    cfg = """
[Interface]
PrivateKey = x

[Peer]
# Name: IDTest
# ID: abc12345
# Created: 2025-01-15
PublicKey = pk3
AllowedIPs = 10.8.1.4/32
"""
    peers = parse_peers(cfg)
    assert peers[0]["clientId"] == "abc12345"
    assert peers[0]["createdAt"] == "2025-01-15"


# ─── normalize_term ───────────────────────────────────────────────────────────

def test_normalize_term_short_codes():
    for code in ["1d", "3d", "7d", "15d", "1m", "3m", "6m", "1y", "admin", "forever"]:
        assert normalize_term(code) == code


def test_normalize_term_russian():
    assert normalize_term("1 день") == "1d"
    assert normalize_term("1 месяц") == "1m"
    assert normalize_term("1 год") == "1y"


def test_normalize_term_english():
    assert normalize_term("1 month") == "1m"
    assert normalize_term("1 year") == "1y"


def test_normalize_term_unknown_defaults_to_1m():
    assert normalize_term("garbage") == "1m"


# ─── safe_name ────────────────────────────────────────────────────────────────

def test_safe_name_basic():
    assert safe_name("iPhone Evgeny") == "iPhone_Evgeny"


def test_safe_name_special_chars():
    result = safe_name("user@domain.com")
    assert "@" not in result


def test_safe_name_allowed_chars():
    assert safe_name("My-Device_v2.0") == "My-Device_v2.0"


# ─── is_expired_date ─────────────────────────────────────────────────────────

def test_is_expired_past():
    assert is_expired_date("2020-01-01") is True


def test_is_expired_future():
    future = (date.today() + timedelta(days=30)).isoformat()
    assert is_expired_date(future) is False


def test_is_expired_empty():
    assert is_expired_date("") is False
    assert is_expired_date(None) is False


# ─── client_name_from_config ──────────────────────────────────────────────────

def test_client_name_from_name_comment():
    cfg = "# Name: MyPhone\n[Interface]\nPrivateKey = x"
    assert client_name_from_config(cfg) == "MyPhone"


def test_client_name_fallback_to_empty():
    assert client_name_from_config("[Interface]\nPrivateKey = x") == ""
