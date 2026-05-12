import os

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "change-me")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
AWG_INTERFACE = os.getenv("AWG_INTERFACE", "awg0")
AWG_CONFIG_PATH = os.getenv("AWG_CONFIG_PATH", "/etc/amnezia/amneziawg/awg0.conf")
MOCK_AWG = os.getenv("MOCK_AWG", "false").lower() in {"1", "true", "yes", "on"}
AWG_BIN = os.getenv("AWG_BIN", "awg")
AWG_DOCKER_CONTAINER = os.getenv("AWG_DOCKER_CONTAINER", "")
AWG_CONTAINER_CONFIG_PATH = os.getenv("AWG_CONTAINER_CONFIG_PATH", AWG_CONFIG_PATH)
CLIENTS_DIR = os.getenv("CLIENTS_DIR", "/data/clients")
SERVER_ENDPOINT = os.getenv("SERVER_ENDPOINT", "1.2.3.4:51820")
CLIENT_DNS = os.getenv("CLIENT_DNS", "1.1.1.1")
CLIENT_ALLOWED_IPS = os.getenv("CLIENT_ALLOWED_IPS", "0.0.0.0/0, ::/0")
CLIENT_PERSISTENT_KEEPALIVE = os.getenv("CLIENT_PERSISTENT_KEEPALIVE", "25")
RELOAD_COMMAND = os.getenv("RELOAD_COMMAND", "systemctl restart awg-quick@awg0.service")
