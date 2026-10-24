"""Grundeinstellungen: Datenordner und Versionsnummer."""
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv('DATA_DIR', BASE / 'data'))


def version():
    try:
        return (BASE / 'VERSION').read_text().strip()
    except Exception:
        return '0'


def init():
    DATA.mkdir(parents=True, exist_ok=True)
