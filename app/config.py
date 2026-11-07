"""Local configuration. All persistent application state stays under data/."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env() -> None:
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('\"\''))


load_env()
DATA_DIR = Path(os.environ.get('PLANT_DATA_DIR', ROOT / 'data')).resolve()
MODEL_DIR = Path(os.environ.get('PLANT_MODEL_DIR', ROOT / 'models')).resolve()
OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', '')
OLLAMA_VISION_MODEL = os.environ.get('OLLAMA_VISION_MODEL', '')
OLLAMA_TIMEOUT = float(os.environ.get('OLLAMA_TIMEOUT', '240'))
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
