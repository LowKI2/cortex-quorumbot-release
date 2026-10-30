"""Konfigurator für Cortex QuorumBot – lokale Weboberfläche.

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
    header = ("# Cortex QuorumBot – geschrieben vom Konfigurator "
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
                values[k] = str(values[k]) if values[k] else None   # große IDs nie als JS-Zahl; 0 = Platzhalter
            if f["type"] == "idlist" and values[k]:
                values[k] = [str(x) for x in values[k] if x]
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
            "wizard_done": bool(flat_get(data, "meta.wizard_done")),
        }

    def _getter(self, data: dict):
        ov = self.overrides()
        def get(key):
            if key in ov:
                return ov[key]
            v = flat_get(data, key)
            return FIELDS.get(key, {}).get("default") if v is None else v
        return get

    def save(self, incoming: dict, draft: bool = False) -> dict:
        """draft=True (Assistent): Felder prüfen, aber unvollständige Konfiguration erlauben."""
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
        if errors and not draft:
            return {"ok": False, "errors": errors}
        save_config(self.cfg_path, data)
        return {"ok": True, "warnings": warnings, "errors": errors if draft else []}

    def wizard_done(self) -> dict:
        data = load_config(self.cfg_path)
        flat_set(data, "meta.wizard_done", True)
        save_config(self.cfg_path, data)
        return {"ok": True}

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

    def _cfg_env(self):
        from dotenv import load_dotenv

        from checks import load_env
        load_dotenv(self.env_path, override=True)   # für die echte Testanfrage
        return Config(self.cfg_path), load_env(self.env_path)

    def test_llm(self) -> dict:
        """Eine echte Testanfrage mit der gespeicherten Konfiguration."""
        if not self.cfg_path.exists():
            return {"ok": False, "errors": ["Erst speichern."]}
        from checks import model_request
        cfg, _ = self._cfg_env()
        r = model_request(cfg)
        if r.status != "ok":
            return {"ok": False, "errors": [r.detail + (" – " + r.fix if r.fix else "")]}
        return {"ok": True, "text": r.detail.split("„", 1)[-1].rstrip("“"), "detail": r.detail}

    def check(self, with_request: bool) -> dict:
        """Alle Prüfungen (wie pruefen.bat)."""
        if not self.cfg_path.exists():
            return {"ok": False, "errors": ["Erst speichern."]}
        from checks import run_all, summary
        cfg, env = self._cfg_env()
        results = run_all(cfg, env, with_request=with_request)
        return {"ok": True, "results": [r.to_dict() for r in results], "summary": summary(results),
                "ready": not any(r.status == "fail" for r in results)}

    def discord_identity(self) -> dict:
        """Nach dem Setzen des Tokens: Bot-Name, Application-ID, Intent – zum Vorausfüllen im Assistenten."""
        from checks import DISCORD_API, FLAG_MESSAGE_CONTENT, FLAG_MESSAGE_CONTENT_LIMITED, http_get, load_env
        data = load_config(self.cfg_path)
        token = load_env(self.env_path).get(flat_get(data, "discord.token_env") or "DISCORD_TOKEN", "")
        if not token:
            return {"ok": False, "errors": ["Discord-Token ist noch nicht gesetzt."]}
        auth = {"Authorization": f"Bot {token}"}
        st, me = http_get(f"{DISCORD_API}/users/@me", auth)
        if st == 401:
            return {"ok": False, "errors": ["Token ungültig – im Developer Portal neu erzeugen (Reset Token)."]}
        if st != 200 or not isinstance(me, dict):
            return {"ok": False, "errors": [f"Discord nicht erreichbar ({st})."]}
        st, app = http_get(f"{DISCORD_API}/applications/@me", auth)
        flags = int(app.get("flags") or 0) if st == 200 and isinstance(app, dict) else 0
        return {"ok": True, "bot_name": me.get("username"), "bot_id": str(me.get("id")),
                "application_id": str(app.get("id")) if st == 200 and isinstance(app, dict) else None,
                "intent": bool(flags & (FLAG_MESSAGE_CONTENT | FLAG_MESSAGE_CONTENT_LIMITED))}

    def start_bot(self) -> dict:
        """Startet den Bot in einem eigenen Fenster (nur wenn er nicht schon läuft)."""
        try:
            st = json.loads(self.status_path.read_text(encoding="utf-8"))
            if time.time() - float(st.get("ts", 0)) < 60:
                return {"ok": False, "errors": ["Der Bot läuft bereits."]}
        except (OSError, ValueError):
            pass
        if not self.cfg_path.exists():
            return {"ok": False, "errors": ["Erst speichern."]}
        import subprocess
        kwargs = {"cwd": str(HERE)}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([sys.executable, str(HERE / "bot.py"), str(self.cfg_path)], **kwargs)
        return {"ok": True}


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
            if self.path == "/api/discord/identity":
                return self._json(store.discord_identity())
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
                "/api/save": lambda: store.save(body.get("values", {}), draft=bool(body.get("draft"))),
                "/api/wizard/done": store.wizard_done,
                "/api/secret": lambda: store.set_secret(str(body.get("name", "")), str(body.get("value", ""))),
                "/api/override/clear": lambda: store.clear_override(body.get("key")),
                "/api/test": store.test_llm,
                "/api/check": lambda: store.check(bool(body.get("with_request", True))),
                "/api/bot/start": store.start_bot,
            }
            fn = routes.get(self.path)
            if not fn:
                return self._json({"error": "nicht gefunden"}, 404)
            self._json(fn())

    return Handler


def main():
    ap = argparse.ArgumentParser(description="Konfigurator für Cortex QuorumBot")
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
