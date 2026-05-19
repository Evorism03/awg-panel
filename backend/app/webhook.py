import hashlib
import hmac
import json
import threading
import urllib.request
from datetime import datetime, timezone

from .config import WEBHOOK_SECRET, WEBHOOK_URL


def send(event: str, data: dict):
    """Fire-and-forget webhook delivery in a background thread."""
    if not WEBHOOK_URL:
        return
    threading.Thread(target=_deliver, args=(event, data), daemon=True).start()


def _deliver(event: str, data: dict):
    urls = [u.strip() for u in WEBHOOK_URL.split(",") if u.strip()]
    payload = json.dumps(
        {
            "event": event,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "data": data,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    for url in urls:
        _post_once(url, payload)


def _post_once(url: str, payload: bytes):
    headers = {"Content-Type": "application/json"}
    if WEBHOOK_SECRET:
        sig = hmac.new(WEBHOOK_SECRET.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        headers["X-AWG-Signature"] = f"sha256={sig}"
    try:
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception:
        pass
