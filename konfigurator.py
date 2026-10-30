"""Konfigurator für die Claude-Runde – lokale Weboberfläche.

Start:  python konfigurator.py [config.yaml] [--port 8765]
Öffnet http://127.0.0.1:8765 – nur auf diesem Rechner erreichbar.

Funktioniert vor dem ersten Start (legt config.yaml an) und bei laufendem Bot:
der Bot liest config.yaml bei der nächsten Nachricht neu ein.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

from config import Config
from settings_schema import FIELDS, SECTIONS, check_consistency, to_value

HERE = Path(__file__).resolve().parent
INVITE_PERMISSIONS = 1024 + 2048 + 65536  # Kanäle sehen, Nachrichten senden, Verlauf lesen
SECRET_KEYS_DEFAULT = ("discord.token_env", "DISCORD_TOKEN"), ("llm.api_key_env", "ANTHROPIC_API_KEY")


# --- Dateien ------------------------------------------------------------
def flat_get(data: dict, key: str):
    cur = data
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def flat_set(data: dict, key: str, value):
    parts = key.split(".")
    cur = data
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def defaults() -> dict:
    data: dict = {}
    for key, f in FIELDS.items():
        if "default" in f:
            flat_set(data, key, f["default"])
    return data


def load_config(path: Path) -> dict:
    if path.exists():
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    example = path.with_name("config.example.yaml")
    if example.exists():
        return yaml.safe_load(example.read_text(encoding="utf-8")) or {}
    return defaults()


def save_config(path: Path, data: dict):
    if path.exists():
        shutil.copy2(path, path.with_suffix(".yaml.bak"))
    header = ("# Claude-Runde – geschrieben vom Konfigurator "
              f"({time.strftime('%Y-%m-%d %H:%M')}).\n"
              "# Erklärungen zu allen Feldern: config.example.yaml oder Konfigurator.\n\n")
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100)
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(header + body, encoding="utf-8")
    tmp.replace(path)  # atomar: der Bot liest nie eine halbe Datei


def read_env(path: Path) -> dict[str, str]:
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def write_env_var(path: Path, name: str, value: str):
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    done = False
    for i, line in enumerate(lines):
        if line.partition("=")[0].strip() == name and not line.lstrip().startswith("#"):
            lines[i] = f"{name}={value}"
            done = True
    if not done:
        lines.append(f"{name}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- Logik --------------------------------------------------------------
class Store:
    def __init__(self, cfg_path: Path):
        self.cfg_path = cfg_path
        self.env_path = cfg_path.parent / ".env"
        self.overrides_path = cfg_path.with_name(cfg_path.stem + ".overrides.json")
        self.status_path = cfg_path.with_name(cfg_path.stem + ".status.json")
        self.budget_path = cfg_path.with_name(cfg_path.stem + ".budget.json")

    def overrides(self) -> dict:
        try:
            return json.loads(self.overrides_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def secret_names(self, data: dict) -> list[str]:
        return [flat_get(data, k) or d for k, d in SECRET_KEYS_DEFAULT]

    def state(self) -> dict:
        data = load_config(self.cfg_path)
        values = {k: flat_get(data, k) for k in FIELDS}
        for k, f in FIELDS.items():
            if values[k] is None and "default" in f:
                values[k] = f["default"]
            if f["type"] in ("id",) and values[k] is not None:
                values[k] = str(values[k])           # große IDs nie als JS-Zahl
            if f["type"] == "idlist" and values[k]:
                values[k] = [str(x) for x in values[k]]
        env = read_env(self.env_path)
        secrets = {n: bool(env.get(n)) for n in self.secret_names(data)}
        status = None
        try:
            st = json.loads(self.status_path.read_text(encoding="utf-8"))
            st["age"] = round(time.time() - float(st.get("ts", 0)))
            status = st
        except (OSError, ValueError):
            pass
        try:
            budget = json.loads(self.budget_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            budget = None
        ov = {k: (str(v) if FIELDS.get(k, {}).get("type") == "id" else v) for k, v in self.overrides().items()}
        errors, warnings = check_consistency(self._getter(data))
        return {
            "sections": [{"title": t, "fields": fs} for t, fs in SECTIONS],
            "values": values, "overrides": ov, "secrets": secrets,
            "status": status, "budget": budget, "exists": self.cfg_path.exists(),
            "path": str(self.cfg_path), "errors": errors, "warnings": warnings,
        }

    def _getter(self, data: dict):
        ov = self.overrides()
        def get(key):
            if key in ov:
                return ov[key]
            v = flat_get(data, key)
            return FIELDS.get(key, {}).get("default") if v is None else v
        return get

    def save(self, incoming: dict) -> dict:
        data = load_config(self.cfg_path)
        field_errors = {}
        for key, raw in incoming.items():
            if key not in FIELDS:
                continue
            try:
                flat_set(data, key, to_value(FIELDS[key], raw))
            except ValueError as e:
                field_errors[key] = str(e)
        if field_errors:
            return {"ok": False, "field_errors": field_errors}
        errors, warnings = check_consistency(self._getter(data))
        if errors:
            return {"ok": False, "errors": errors}
        save_config(self.cfg_path, data)
        return {"ok": True, "warnings": warnings}

    def set_secret(self, name: str, value: str) -> dict:
        data = load_config(self.cfg_path)
        if name not in self.secret_names(data):
            return {"ok": False, "errors": ["Unbekannte Variable"]}
        if any(c in value for c in "\r\n"):
            return {"ok": False, "errors": ["Ungültiger Wert"]}
        write_env_var(self.env_path, name, value.strip())
        return {"ok": True}

    def clear_override(self, key: str | None) -> dict:
        ov = self.overrides()
        if key:
            ov.pop(key, None)
        else:
            ov = {}
        self.overrides_path.write_text(json.dumps(ov, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"ok": True}

    def invite(self) -> dict:
        app_id = flat_get(load_config(self.cfg_path), "discord.application_id")
        if not app_id:
            return {"ok": False, "errors": ["Application-ID fehlt (Abschnitt Discord)."]}
        url = (f"https://discord.com/oauth2/authorize?client_id={app_id}"
               f"&scope=bot%20applications.commands&permissions={INVITE_PERMISSIONS}")
        return {"ok": True, "url": url}

    def test_llm(self) -> dict:
        """Eine echte Testanfrage mit der gespeicherten Konfiguration."""
        if not self.cfg_path.exists():
            return {"ok": False, "errors": ["Erst speichern."]}
        import os

        from dotenv import load_dotenv

        from guardrails import Decision
        from llm import LLM
        from prompting import build_system
        load_dotenv(self.env_path, override=True)
        cfg = Config(self.cfg_path)
        if cfg.get("llm.provider") == "claude_code":
            key_var = cfg.get("llm.api_key_env", "ANTHROPIC_API_KEY")
            if os.environ.get(key_var):
                os.environ.pop(key_var, None)   # damit wirklich das Abo genutzt wird
        system = build_system(cfg, Decision(True, "test", "owner", 1, 1, True))
        msgs = [{"role": "user", "content": f"{cfg.get('bot.owner_name') or 'Besitzer'}: Kurzer Funktionstest – stell dich in einem Satz vor."}]
        t0 = time.time()
        try:
            text, tin, tout = asyncio.run(LLM(cfg).complete(system, msgs))
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "errors": [f"{type(e).__name__}: {e}"[:400]]}
        return {"ok": True, "text": text, "tokens": tin + tout, "seconds": round(time.time() - t0, 1)}


# --- HTTP ---------------------------------------------------------------
def make_handler(store: Store):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _local_only(self) -> bool:
            # Schutz vor fremden Webseiten, die per Browser auf localhost zugreifen wollen.
            host = (self.headers.get("Host") or "").split(":")[0]
            origin = self.headers.get("Origin")
            if host not in ("127.0.0.1", "localhost"):
                return False
            return origin is None or origin.split("//")[-1].split(":")[0] in ("127.0.0.1", "localhost")

        def do_GET(self):
            if not self._local_only():
                return self._json({"error": "nur lokal"}, 403)
            if self.path == "/":
                html = (HERE / "konfigurator.html").read_bytes()
                return self._send(200, html, "text/html; charset=utf-8")
            if self.path == "/api/state":
                return self._json(store.state())
            if self.path == "/api/invite":
                return self._json(store.invite())
            self._json({"error": "nicht gefunden"}, 404)

        def do_POST(self):
            if not self._local_only():
                return self._json({"error": "nur lokal"}, 403)
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self._json({"error": "JSON erwartet"}, 415)
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._json({"error": "ungültiges JSON"}, 400)
            routes = {
                "/api/save": lambda: store.save(body.get("values", {})),
                "/api/secret": lambda: store.set_secret(str(body.get("name", "")), str(body.get("value", ""))),
                "/api/override/clear": lambda: store.clear_override(body.get("key")),
                "/api/test": store.test_llm,
            }
            fn = routes.get(self.path)
            if not fn:
                return self._json({"error": "nicht gefunden"}, 404)
            self._json(fn())

    return Handler


def main():
    ap = argparse.ArgumentParser(description="Konfigurator für die Claude-Runde")
    ap.add_argument("config", nargs="?", default="config.yaml")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    cfg_path = Path(args.config).resolve()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(Store(cfg_path)))
    url = f"http://127.0.0.1:{args.port}"
    print(f"Konfigurator läuft: {url}  (Datei: {cfg_path})  – Beenden mit Strg+C")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")
        sys.exit(0)


if __name__ == "__main__":
    main()
