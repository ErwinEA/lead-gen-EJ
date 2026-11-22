from pathlib import Path
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def load() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text())
