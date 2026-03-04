import os
from typing import Optional

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
PORT_FILE = os.path.join(DATA_DIR, "port.txt")
ACTUAL_PORT: Optional[int] = None

os.makedirs(DATA_DIR, exist_ok=True)


def save_port(port: int):
    global ACTUAL_PORT
    ACTUAL_PORT = port
    with open(PORT_FILE, "w", encoding="utf-8") as f:
        f.write(str(port))


def load_port() -> Optional[int]:
    if os.path.exists(PORT_FILE):
        try:
            with open(PORT_FILE, "r", encoding="utf-8") as f:
                return int(f.read().strip())
        except (ValueError, IOError):
            pass
    return None


def get_actual_port() -> Optional[int]:
    return ACTUAL_PORT
