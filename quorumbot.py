"""Einstieg der Windows-exe (CortexQuorumBot.exe).

    CortexQuorumBot.exe                      Konfigurator (eigenes Fenster)
    CortexQuorumBot.exe konfigurator [...]   dito, mit Optionen
    CortexQuorumBot.exe bot [config.yaml]    Bot starten
    CortexQuorumBot.exe pruefen [...]        Selbsttest
    CortexQuorumBot.exe update [--install|--rollback]
    CortexQuorumBot.exe wissen-ordner ...    Lese-Server für Wissensordner (startet Claude Code selbst)

In der Python-Variante werden stattdessen die einzelnen .py-Dateien direkt gestartet.
"""
from __future__ import annotations

import os
import sys

COMMANDS = ("konfigurator", "bot", "pruefen", "update", "wissen-ordner")


def main():
    from version import app_dir
    args = sys.argv[1:]
    sub = args[0] if args and args[0] in COMMANDS else "konfigurator"
    rest = args[1:] if args and args[0] in COMMANDS else args
    if sub != "wissen-ordner":
        os.chdir(app_dir())                       # config.yaml und .env liegen neben der exe
    sys.argv = [f"{sys.argv[0]} {sub}", *rest]
    if sub == "konfigurator":
        import konfigurator
        konfigurator.main()
    elif sub == "bot":
        import bot
        bot.main()
    elif sub == "pruefen":
        import pruefen
        sys.exit(pruefen.main())
    elif sub == "update":
        import updater
        sys.exit(updater.main())
    else:
        import wissen_ordner
        wissen_ordner.main()


if __name__ == "__main__":
    main()
