"""Windows-exe bauen (nur unter Windows, im .venv):

    pip install pyinstaller pywebview
    python tools/build_exe.py

Ergebnis: dist/exe/CortexQuorumBot.exe (eine Datei, enthält Python, alle Pakete und den Konfigurator).
Danach: python tools/build_release.py vX.Y.Z  → packt zusätzlich CortexQuorumBot-Windows.zip.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.platform != "win32":
        sys.exit("Die exe kann nur unter Windows gebaut werden.")
    out = ROOT / "dist" / "exe"
    work = ROOT / "build"
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
           "--name", "CortexQuorumBot", "--distpath", str(out), "--workpath", str(work), "--specpath", str(work),
           "--add-data", f"{ROOT / 'konfigurator.html'};.",
           "--add-data", f"{ROOT / 'assets'};assets",
           "--collect-submodules", "discord", "--collect-data", "discord",   # inkl. Opus-DLL für Sprache
           "--collect-all", "webview", "--collect-all", "nacl", "--collect-all", "davey",
           "--hidden-import", "truststore",
           str(ROOT / "quorumbot.py")]
    icon = ROOT / "tools" / "icon.ico"
    if icon.exists():
        cmd[cmd.index("--onefile") + 1:cmd.index("--onefile") + 1] = ["--icon", str(icon)]
    subprocess.run(cmd, check=True, cwd=ROOT)
    shutil.rmtree(work, ignore_errors=True)
    exe = out / "CortexQuorumBot.exe"
    print(f"{exe}: {exe.stat().st_size // (1024 * 1024)} MB")


if __name__ == "__main__":
    main()
