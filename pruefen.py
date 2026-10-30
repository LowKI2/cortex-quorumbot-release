"""Selbsttest für Cortex QuorumBot.

Start:  python pruefen.py [config.yaml] [--ohne-anfrage]
Prüft Python, Pakete, Konfiguration, Discord-Zugang und Modell und sagt, was zu tun ist.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ICON = {"ok": "[ OK ]", "warn": "[HINW]", "fail": "[FEHL]", "skip": "[ -- ]"}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Selbsttest für Cortex QuorumBot")
    ap.add_argument("config", nargs="?", default="config.yaml")
    ap.add_argument("--ohne-anfrage", action="store_true", help="keine echte Modell-Anfrage senden")
    args = ap.parse_args()

    from checks import Result, check_packages, check_python, summary
    base = [check_python(), check_packages()]
    if any(r.status == "fail" for r in base):
        for r in base:
            print(f"{ICON[r.status]} {r.name}: {r.detail}" + (f"\n        → {r.fix}" if r.fix else ""))
        return 1

    from dotenv import load_dotenv

    from checks import load_env, run_all
    from config import Config
    cfg_path = Path(args.config).resolve()
    if not cfg_path.exists():
        print(f"{ICON['fail']} Konfiguration: {cfg_path.name} fehlt\n        → konfigurator.bat starten und den Assistenten durchlaufen.")
        return 1
    env_path = cfg_path.parent / ".env"
    load_dotenv(env_path, override=True)
    cfg = Config(cfg_path)
    print(f"Cortex QuorumBot – Selbsttest ({cfg.get('bot.name')}, {cfg.get('llm.provider')})\n")
    results: list[Result] = run_all(cfg, load_env(env_path), with_request=not args.ohne_anfrage)
    for r in results:
        print(f"{ICON[r.status]} {r.name}: {r.detail}" + (f"\n        → {r.fix}" if r.fix else ""))
    print("\n" + summary(results))
    return 1 if any(r.status == "fail" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
