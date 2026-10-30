"""Konfigurator für Cortex QuorumBot – lokale Weboberfläche.

Start:  python konfigurator.py [config.yaml] [--port 8765] [--fenster | --browser]
Öffnet http://127.0.0.1:8765 – nur auf diesem Rechner erreichbar. In der Windows-exe
(oder mit --fenster und installiertem pywebview) als eigenes Programmfenster.

Funktioniert vor dem ersten Start (legt config.yaml an) und bei laufendem Bot:
der Bot liest config.yaml bei der nächsten Nachricht neu ein.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
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
        self.window = None                # pywebview-Fenster (nur im Fenstermodus)
        self._update_info = None
        self._update_ts = 0.0

    def overrides(self) -> dict:
        try:
            return json.loads(self.overrides_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def secret_names(self, data: dict) -> list[str]:
        import knowledge
        names = [flat_get(data, k) or d for k, d in SECRET_KEYS_DEFAULT]
        if flat_get(data, "knowledge.mediavault.enabled") and knowledge.KEY_ENV not in names:
            names.append(knowledge.KEY_ENV)
        return names

    def state(self) -> dict:
        data = load_config(self.cfg_path)
        values = {k: flat_get(data, k) for k in FIELDS}
        for k, f in FIELDS.items():
            if values[k] is None and "default" in f:
                values[k] = f["default"]
            if f["type"] in ("id",) and values[k] is not None:
                values[k] = str(values[k]) if values[k] else None   # große IDs nie als JS-Zahl; 0 = Platzhalter
            if f["type"] == "pairs":
                values[k] = [f"{a} = {b}" for a, b in (values[k] or {}).items()]
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
        sections = [{"title": t, "fields": fs} for t, fs in SECTIONS]   # nichts wird automatisch gesucht
        return {
            "sections": sections,
            "values": values, "overrides": ov, "secrets": secrets,
            "status": status, "budget": budget, "exists": self.cfg_path.exists(),
            "path": str(self.cfg_path), "errors": errors, "warnings": warnings,
            "wizard_done": bool(flat_get(data, "meta.wizard_done")),
            "app": self.app_info(),
        }

    # --- Updates ---------------------------------------------------------
    def app_info(self) -> dict:
        import updater
        from version import VERSION, variant
        return {"version": VERSION, "variant": variant(), "dev": updater.is_dev(),
                "backups": [p.name for p in updater.backups()], "window": self.window is not None}

    def _bot_running(self) -> bool:
        try:
            st = json.loads(self.status_path.read_text(encoding="utf-8"))
            return time.time() - float(st.get("ts", 0)) < 60
        except (OSError, ValueError):
            return False

    def update_check(self, force: bool = False) -> dict:
        import updater
        if force or not self._update_info or time.time() - self._update_ts > 600:
            self._update_info = updater.check()
            self._update_ts = time.time()
        return self._update_info

    def update_install(self) -> dict:
        import updater
        if self._bot_running():
            return {"ok": False, "errors": ["Der Bot läuft – bitte erst beenden (Fenster schließen), dann updaten."]}
        res = updater.install(self.update_check(force=True))
        if res.get("ok"):
            self._update_info = None
            self.schedule_restart()
        return res

    def update_rollback(self) -> dict:
        import updater
        if self._bot_running():
            return {"ok": False, "errors": ["Der Bot läuft – bitte erst beenden."]}
        res = updater.rollback()
        if res.get("ok"):
            self.schedule_restart()
        return res

    def schedule_restart(self):
        """Nach Update: neuen Konfigurator starten und diesen beenden (Antwort geht vorher noch raus)."""
        import updater

        def go():
            time.sleep(1.0)
            updater.restart("konfigurator", self.cfg_path, ["--no-browser"] if self.window is None else [])
            os._exit(updater.RESTART_CODE)              # beendet auch ein offenes Programmfenster
        threading.Thread(target=go, daemon=True).start()

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

    # --- Profilbild des Bots ---------------------------------------------
    AVATAR_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")
    AVATAR_MAX = 8 * 1024 * 1024

    def _discord_auth(self):
        from checks import load_env
        data = load_config(self.cfg_path)
        token = load_env(self.env_path).get(flat_get(data, "discord.token_env") or "DISCORD_TOKEN", "")
        return {"Authorization": f"Bot {token}"} if token else None

    def bot_profile(self, get=None) -> dict:
        from checks import DISCORD_API, http_get
        auth = self._discord_auth()
        if not auth:
            return {"ok": False, "errors": ["Erst den Discord-Token setzen."]}
        st, me = (get or http_get)(f"{DISCORD_API}/users/@me", auth)
        if st != 200 or not isinstance(me, dict):
            return {"ok": False, "errors": ["Token ungültig." if st == 401 else f"Discord nicht erreichbar ({st})."]}
        uid, av = str(me.get("id")), me.get("avatar")
        url = (f"https://cdn.discordapp.com/avatars/{uid}/{av}.{'gif' if str(av).startswith('a_') else 'png'}?size=128"
               if av else f"https://cdn.discordapp.com/embed/avatars/{(int(uid) >> 22) % 6}.png")
        return {"ok": True, "name": me.get("username"), "avatar_url": url, "has_avatar": bool(av)}

    def set_avatar(self, data_url: str, patch=None) -> dict:
        """Profilbild des Bots setzen (Datenadresse aus dem Browser). Leer = Standardbild."""
        import base64
        from checks import DISCORD_API, http_patch_json
        auth = self._discord_auth()
        if not auth:
            return {"ok": False, "errors": ["Erst den Discord-Token setzen."]}
        data_url = (data_url or "").strip()
        if data_url:
            head, _, b64 = data_url.partition(",")
            mime = head[5:].split(";")[0] if head.startswith("data:") else ""
            if mime not in self.AVATAR_TYPES or ";base64" not in head:
                return {"ok": False, "errors": ["Bitte ein Bild wählen (PNG, JPG, GIF oder WebP)."]}
            try:
                raw = base64.b64decode(b64, validate=True)
            except ValueError:
                return {"ok": False, "errors": ["Bild konnte nicht gelesen werden."]}
            if len(raw) > self.AVATAR_MAX:
                return {"ok": False, "errors": ["Bild ist größer als 8 MB."]}
        st, res = (patch or http_patch_json)(f"{DISCORD_API}/users/@me", {"avatar": data_url or None}, auth)
        if st == 200:
            return {"ok": True}
        if st == 429:
            return {"ok": False, "errors": ["Discord erlaubt nur wenige Bildwechsel kurz hintereinander – in ein paar Minuten nochmal versuchen."]}
        msg = res.get("message") if isinstance(res, dict) else None
        return {"ok": False, "errors": [f"Discord hat abgelehnt ({st}{': ' + msg if msg else ''})."]}

    def knowledge_check(self) -> dict:
        """Nur die MediaVault-Prüfung (ohne Modell-Anfrage) – für den Knopf „Verbindung prüfen“."""
        if not self.cfg_path.exists():
            return {"ok": False, "errors": ["Erst speichern."]}
        from checks import knowledge_checks
        cfg, env = self._cfg_env()
        res = knowledge_checks(cfg, env, with_request=False)
        if not res:
            return {"ok": False, "errors": ["Wissen ist aus."]}
        return {"ok": True, "results": [r.to_dict() for r in res],
                "summary": "Bereit" if all(r.status != "fail" for r in res) else "Nicht bereit",
                "ready": all(r.status != "fail" for r in res)}

    def pick_folder(self) -> dict:
        """Windows-/System-Dialog „Ordner wählen“ – der Konfigurator läuft lokal, daher geht das."""
        if self.window is not None:                       # eigenes Fenster: Dialog von WebView2
            try:
                import webview
                res = self.window.create_file_dialog(webview.FOLDER_DIALOG)
            except Exception:  # noqa: BLE001
                res = None
            if res:
                return {"ok": True, "path": str(Path(res[0] if isinstance(res, (list, tuple)) else res))}
            if res is not None:
                return {"ok": False, "errors": ["Abgebrochen."]}
        import queue
        q = queue.Queue()

        def run():
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                path = filedialog.askdirectory(title="Wissensordner wählen", mustexist=True)
                root.destroy()
                q.put(path or "")
            except Exception as e:  # noqa: BLE001
                q.put(e)
        threading.Thread(target=run, daemon=True).start()
        try:
            res = q.get(timeout=600)
        except Exception:  # noqa: BLE001
            return {"ok": False, "errors": ["Kein Ordner gewählt."]}
        if isinstance(res, Exception):
            return {"ok": False, "errors": ["Ordner-Dialog nicht verfügbar – Pfad bitte von Hand eintragen."]}
        if not res:
            return {"ok": False, "errors": ["Abgebrochen."]}
        return {"ok": True, "path": str(Path(res))}

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
        from version import app_dir, command
        kwargs = {"cwd": str(app_dir())}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(command("bot", str(self.cfg_path)), **kwargs)
        return {"ok": True}


# --- HTTP ---------------------------------------------------------------
def make_handler(store: "Store"):
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
            if self.path == "/api/discord/profile":
                return self._json(store.bot_profile())
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
                "/api/knowledge/check": store.knowledge_check,
                "/api/pick_folder": store.pick_folder,
                "/api/discord/avatar": lambda: store.set_avatar(str(body.get("image", ""))),
                "/api/update/check": lambda: store.update_check(force=bool(body.get("force"))),
                "/api/update/install": store.update_install,
                "/api/update/rollback": store.update_rollback,
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
    ap.add_argument("--fenster", action="store_true", help="eigenes Programmfenster (braucht pywebview)")
    ap.add_argument("--browser", action="store_true", help="immer im Browser öffnen")
    args = ap.parse_args()
    cfg_path = Path(args.config).resolve()

    from version import frozen
    store = Store(cfg_path)
    import updater
    mode = flat_get(load_config(cfg_path), "update.mode") or FIELDS["update.mode"]["default"]   # Standard: manuell
    if updater.auto_update(mode, "konfigurator", cfg_path):
        sys.exit(updater.RESTART_CODE)

    server = None
    for _ in range(30):                                   # nach einem Neustart kann der Port kurz noch belegt sein
        try:
            server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(store))
            break
        except OSError:
            time.sleep(0.5)
    if server is None:
        sys.exit(f"Port {args.port} ist belegt – läuft der Konfigurator schon? Dann dort weiterarbeiten.")
    url = f"http://127.0.0.1:{args.port}"
    print(f"Konfigurator läuft: {url}  (Datei: {cfg_path})  – Beenden mit Strg+C")

    want_window = (frozen() or args.fenster) and not args.browser
    if want_window:
        try:
            import webview
        except ImportError:
            webview = None
            print("Eigenes Fenster nicht verfügbar – öffne im Browser.")
        if webview is not None:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            store.window = webview.create_window("Cortex QuorumBot · Konfigurator", url, width=1320, height=900,
                                                 min_size=(380, 600), background_color="#070b12")
            try:
                webview.start()
                os._exit(updater.RESTART_CODE)            # Fenster geschlossen: Konsolenfenster schließt mit
            except Exception as e:  # noqa: BLE001  (z. B. WebView2 fehlt)
                store.window = None
                print(f"Fenster ließ sich nicht öffnen ({e}) – öffne im Browser.")
                webbrowser.open(url)
                threading.Event().wait()
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")
        sys.exit(0)


if __name__ == "__main__":
    main()
