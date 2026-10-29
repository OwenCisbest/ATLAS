from pathlib import Path
import sys


def asset_path(name: str) -> Path:
    """Resolve bundled assets independently of the user's working directory."""
    root = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]
    return root / 'assets' / name
