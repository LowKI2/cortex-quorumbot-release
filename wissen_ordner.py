"""Lese-Server für lokale Wissensordner (MCP über stdio, ohne Zusatzpakete).

Claude Code startet ihn pro Antwort:
    python wissen_ordner.py --root "C:\\Wissen" --root "D:\\Projekte\\Notizen" [--ext .md,.txt] [--max-kb 200]

Werkzeuge (nur lesend):
    list_files  – Dateien auflisten (optional nach Unterordner/Teilstring gefiltert)
    search      – Volltextsuche (Groß-/Kleinschreibung egal), liefert Fundstellen mit Zeilennummer
    read_file   – Datei lesen (Ausschnitt per Zeilen)

Sicherheit: nur innerhalb der freigegebenen Ordner (auch über Verknüpfungen nicht hinaus),
nur Textdateien mit erlaubter Endung, keine versteckten Ordner, keine Schlüssel- oder .env-Dateien,
Größenlimit pro Datei. Schreiben, Löschen oder Ausführen gibt es nicht.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

PROTOCOL = "2025-06-18"
DEFAULT_EXT = [".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".html", ".htm", ".xml", ".ini", ".log", ".rst"]
DENY_NAME = re.compile(r"(^\.env|\.key$|\.pem$|\.pfx$|\.p12$|^id_(rsa|ed25519|ecdsa)|\.kdbx$|credential|secret|passw|token)", re.I)
MAX_FILES = 20000


class Folders:
    def __init__(self, roots: list[str], exts: list[str] | None = None, max_kb: int = 200):
        self.roots: dict[str, Path] = {}
        for r in roots:
            p = Path(r).expanduser().resolve()
            if not p.is_dir():
                continue
            name, i = p.name or str(p).replace(":", "").strip("\\/"), 2
            while name in self.roots:
                name, i = f"{p.name}-{i}", i + 1
            self.roots[name] = p
        self.exts = {e.lower() if e.startswith(".") else "." + e.lower() for e in (exts or DEFAULT_EXT)}
        self.max_bytes = max(1, int(max_kb)) * 1024

    # --- Pfade ---------------------------------------------------------
    def _allowed_file(self, p: Path) -> bool:
        return p.suffix.lower() in self.exts and not DENY_NAME.search(p.name)

    def resolve(self, display: str) -> Path:
        """'Ordnername/unter/datei.md' → echter Pfad, nur wenn er sicher innerhalb liegt."""
        display = (display or "").replace("\\", "/").strip("/")
        root_name, _, rest = display.partition("/")
        if root_name not in self.roots:
            if len(self.roots) == 1:                      # Ordnername darf fehlen, wenn es nur einen gibt
                root_name, rest = next(iter(self.roots)), display
            else:
                raise ValueError(f"Unbekannter Ordner „{root_name}“. Vorhanden: {', '.join(self.roots)}")
        root = self.roots[root_name]
        target = (root / rest).resolve()
        if target != root and root not in target.parents:
            raise ValueError("Pfad liegt außerhalb der freigegebenen Ordner")
        if any(part.startswith(".") for part in target.relative_to(root).parts):
            raise ValueError("Versteckte Ordner und Dateien sind nicht freigegeben")
        return target

    def display(self, p: Path) -> str:
        for name, root in self.roots.items():
            if p == root or root in p.parents:
                return f"{name}/{p.relative_to(root).as_posix()}"
        raise ValueError("außerhalb")

    def iter_files(self):
        n = 0
        for root in self.roots.values():
            for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in ("node_modules", "__pycache__"))
                for f in sorted(filenames):
                    if f.startswith("."):
                        continue
                    p = Path(dirpath) / f
                    if not self._allowed_file(p):
                        continue
                    try:
                        real = p.resolve()
                        if root not in real.parents or real.stat().st_size > self.max_bytes:
                            continue
                    except OSError:
                        continue
                    yield p
                    n += 1
                    if n >= MAX_FILES:
                        return

    # --- Werkzeuge -----------------------------------------------------
    def list_files(self, filter: str = "", limit: int = 200) -> str:
        f = (filter or "").lower()
        out = [self.display(p) for p in self.iter_files() if f in self.display(p).lower()]
        limit = max(1, min(int(limit or 200), 1000))
        more = f"\n… und {len(out) - limit} weitere (Filter verwenden)" if len(out) > limit else ""
        return ("\n".join(out[:limit]) + more) if out else "Keine passenden Dateien."

    def search(self, query: str, limit: int = 20) -> str:
        q = (query or "").strip().lower()
        if len(q) < 2:
            raise ValueError("Suchbegriff mit mindestens 2 Zeichen angeben")
        terms = q.split()
        hits, limit = [], max(1, min(int(limit or 20), 100))
        for p in self.iter_files():
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            low = text.lower()
            if not all(t in low for t in terms):
                continue
            lines = [(i + 1, line.strip()) for i, line in enumerate(text.splitlines()) if any(t in line.lower() for t in terms)]
            snippet = "\n".join(f"  {n}: {line[:200]}" for n, line in lines[:3])
            hits.append(f"{self.display(p)}\n{snippet}")
            if len(hits) >= limit:
                break
        return "\n\n".join(hits) if hits else f"Nichts gefunden zu „{query}“."

    def read_file(self, path: str, start_line: int = 1, max_lines: int = 400) -> str:
        p = self.resolve(path)
        if not p.is_file():
            raise ValueError("Datei nicht gefunden")
        if not self._allowed_file(p):
            raise ValueError("Dateityp ist nicht freigegeben")
        if p.stat().st_size > self.max_bytes:
            raise ValueError(f"Datei größer als {self.max_bytes // 1024} KB")
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(start_line or 1))
        count = max(1, min(int(max_lines or 400), 2000))
        part = lines[start - 1:start - 1 + count]
        tail = f"\n[… Zeilen {start + len(part)}–{len(lines)} mit start_line weiterlesen]" if start - 1 + count < len(lines) else ""
        return f"{self.display(p)} (Zeilen {start}–{start + len(part) - 1} von {len(lines)})\n" + "\n".join(part) + tail


TOOLS = [
    {"name": "list_files", "description": "Listet Dateien in den freigegebenen Wissensordnern. Optional mit Filter (Teil von Ordner- oder Dateiname).",
     "inputSchema": {"type": "object", "properties": {"filter": {"type": "string"}, "limit": {"type": "integer"}}}},
    {"name": "search", "description": "Volltextsuche in den freigegebenen Wissensordnern. Alle Wörter müssen vorkommen. Liefert Dateien mit Fundstellen.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]}},
    {"name": "read_file", "description": "Liest eine Datei aus den Wissensordnern (Pfad wie von list_files/search). Lange Dateien abschnittsweise mit start_line.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"},
                                                      "max_lines": {"type": "integer"}}, "required": ["path"]}},
]


def handle(folders: Folders, msg: dict) -> dict | None:
    """Eine JSON-RPC-Nachricht beantworten (None bei Benachrichtigungen)."""
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:
        return None
    if method == "initialize":
        result = {"protocolVersion": params.get("protocolVersion") or PROTOCOL, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "wissen-ordner", "version": "1.0"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        fn = {"list_files": folders.list_files, "search": folders.search, "read_file": folders.read_file}.get(name)
        if fn is None:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Unbekanntes Werkzeug {name}"}}
        try:
            text, err = fn(**{k: v for k, v in args.items() if k in fn.__code__.co_varnames}), False
        except (ValueError, OSError, TypeError) as e:
            text, err = f"Fehler: {e}", True
        result = {"content": [{"type": "text", "text": text}], "isError": err}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Unbekannte Methode {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main():
    ap = argparse.ArgumentParser(description="Lese-Server für Wissensordner (MCP, stdio)")
    ap.add_argument("--root", action="append", default=[])
    ap.add_argument("--ext", default=",".join(DEFAULT_EXT))
    ap.add_argument("--max-kb", type=int, default=200)
    a = ap.parse_args()
    folders = Folders(a.root, [e.strip() for e in a.ext.split(",") if e.strip()], a.max_kb)
    stdin = open(sys.stdin.fileno(), encoding="utf-8", errors="replace", closefd=False)
    stdout = open(sys.stdout.fileno(), "w", encoding="utf-8", closefd=False, newline="\n")
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        reply = handle(folders, msg)
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()


if __name__ == "__main__":
    main()
