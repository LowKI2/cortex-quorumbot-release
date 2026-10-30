"""Version und Pfade – gemeinsam für Python-Variante und Windows-exe."""
from __future__ import annotations

import sys
from pathlib import Path

VERSION = "0.5.2"
RELEASE_REPO = "LowKI2/cortex-quorumbot-release"
ASSET_PYTHON = "CortexQuorumBot.zip"
ASSET_EXE = "CortexQuorumBot-Windows.zip"
EXE_NAME = "CortexQuorumBot.exe"


def frozen() -> bool:
    """True in der exe (PyInstaller)."""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Ordner, in dem das Programm liegt (bei der exe: neben der exe, nicht im Entpack-Ordner)."""
    return Path(sys.executable).resolve().parent if frozen() else Path(__file__).resolve().parent


def variant() -> str:
    return "exe" if frozen() else "python"


def asset_name() -> str:
    return ASSET_EXE if frozen() else ASSET_PYTHON


def command(sub: str, *args: str) -> list[str]:
    """Aufruf eines Programmteils (bot, konfigurator, wissen-ordner …) – in beiden Varianten gleich nutzbar."""
    if frozen():
        return [sys.executable, sub, *args]
    script = {"bot": "bot.py", "konfigurator": "konfigurator.py", "wissen-ordner": "wissen_ordner.py",
              "pruefen": "pruefen.py", "update": "updater.py"}[sub]
    return [sys.executable, str(app_dir() / script), *args]
