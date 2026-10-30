"""Prüfungen für Installation und Einrichtung.

Genutzt vom Selbsttest (pruefen.py) und vom Assistenten im Konfigurator.
Jede Prüfung liefert ein Ergebnis mit Status ok | warn | fail | skip und einem
Hinweis, was zu tun ist. Keine Prüfung gibt Geheimnisse aus.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

DISCORD_API = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://github.com/LowKI2/cortex-quorumbot-release, 0.2)"
FLAG_MESSAGE_CONTENT = 1 << 18
FLAG_MESSAGE_CONTENT_LIMITED = 1 << 19
PACKAGES = [("discord", "discord.py"), ("yaml", "PyYAML"), ("dotenv", "python-dotenv"),
            ("anthropic", "anthropic"), ("openai", "openai")]


@dataclass
class Result:
    name: str
    status: str          # ok | warn | fail | skip
    detail: str = ""
    fix: str = ""

    def to_dict(self):
        return asdict(self)


# --- HTTP (austauschbar für Tests) --------------------------------------
def http_get(url: str, headers: dict | None = None, timeout: float = 10.0):
    """Gibt (status, json|None) zurück; Netzwerkfehler → (0, Fehlertext)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace") or "null")
        except ValueError:
            return e.code, None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, str(e)


# --- Umgebung -----------------------------------------------------------
def check_python() -> Result:
    v = sys.version_info
    if v < (3, 10):
        return Result("Python", "fail", f"{v.major}.{v.minor} gefunden",
                      "Python 3.11 oder neuer von python.org installieren, beim Setup „Add to PATH“ anhaken.")
    return Result("Python", "ok", f"{v.major}.{v.minor}.{v.micro}")


def check_packages() -> Result:
    missing = []
    for mod, pkg in PACKAGES:
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        return Result("Pakete", "fail", "fehlt: " + ", ".join(missing),
                      "start.bat einmal ausführen oder: pip install -r requirements.txt")
    return Result("Pakete", "ok", "alle installiert")


# --- Discord ------------------------------------------------------------
def discord_checks(cfg, token: str, get=http_get) -> list[Result]:
    out: list[Result] = []
    if not token:
        return [Result("Discord-Token", "fail", "nicht gesetzt",
                       "Developer Portal → deine App → Bot → Reset Token, Wert im Konfigurator unter Zugangsdaten setzen.")]
    auth = {"Authorization": f"Bot {token}"}

    st, me = get(f"{DISCORD_API}/users/@me", auth)
    if st == 0:
        return [Result("Discord-Token", "warn", "Discord nicht erreichbar", "Internetverbindung prüfen.")]
    if st == 401:
        return [Result("Discord-Token", "fail", "Token ungültig",
                       "Im Developer Portal unter Bot einen neuen Token erzeugen (Reset Token) und neu setzen.")]
    if st != 200 or not isinstance(me, dict):
        return [Result("Discord-Token", "fail", f"Antwort {st}", "Token prüfen.")]
    bot_name = me.get("username", "?")
    out.append(Result("Discord-Token", "ok", f"gültig – Bot „{bot_name}“ (ID {me.get('id')})"))

    st, app = get(f"{DISCORD_API}/applications/@me", auth)
    if st == 200 and isinstance(app, dict):
        flags = int(app.get("flags") or 0)
        if flags & (FLAG_MESSAGE_CONTENT | FLAG_MESSAGE_CONTENT_LIMITED):
            out.append(Result("Message Content Intent", "ok", "eingeschaltet"))
        else:
            out.append(Result("Message Content Intent", "fail", "ausgeschaltet – der Bot sieht keine Nachrichtentexte",
                              "Developer Portal → Bot → Privileged Gateway Intents → Message Content Intent einschalten, speichern."))
        cfg_app = cfg.get("discord.application_id")
        if cfg_app and str(cfg_app) != str(app.get("id")):
            out.append(Result("Application-ID", "warn", "passt nicht zum Token",
                              f"Im Konfigurator {app.get('id')} eintragen."))
        elif not cfg_app:
            out.append(Result("Application-ID", "warn", "nicht eingetragen",
                              f"Für den Einladungslink {app.get('id')} unter Discord eintragen."))
        else:
            out.append(Result("Application-ID", "ok", str(cfg_app)))

    st, guilds = get(f"{DISCORD_API}/users/@me/guilds", auth)
    if st == 200 and isinstance(guilds, list):
        if guilds:
            out.append(Result("Server", "ok", ", ".join(g.get("name", "?") for g in guilds[:3])))
        else:
            out.append(Result("Server", "fail", "Bot ist auf keinem Server",
                              "Im Konfigurator „Einladungslink“ klicken, Link öffnen, Server wählen."))

    for cid in cfg.get("discord.allowed_channel_ids") or []:
        st, ch = get(f"{DISCORD_API}/channels/{cid}", auth)
        if st == 200:
            out.append(Result(f"Kanal {cid}", "ok", f"#{ch.get('name', '?')}"))
        elif st in (403, 404):
            out.append(Result(f"Kanal {cid}", "fail", "Bot sieht den Kanal nicht",
                              "ID prüfen (Rechtsklick auf Kanal → ID kopieren) und dem Bot im Kanal Lesen/Schreiben erlauben."))

    owner = cfg.get("bot.owner_id")
    if owner:
        st, u = get(f"{DISCORD_API}/users/{owner}", auth)
        if st == 200 and isinstance(u, dict):
            if u.get("bot"):
                out.append(Result("Deine User-ID", "fail", f"{u.get('username')} ist ein Bot",
                                  "Hier gehört DEINE Discord-ID hin: Rechtsklick auf deinen Namen → ID kopieren."))
            else:
                out.append(Result("Deine User-ID", "ok", u.get("global_name") or u.get("username", "?")))
        elif st == 404:
            out.append(Result("Deine User-ID", "fail", "unbekannte ID", "ID neu kopieren (Entwicklermodus an)."))
    for pid in cfg.get("bot.partner_bot_ids") or []:
        st, u = get(f"{DISCORD_API}/users/{pid}", auth)
        if st == 200 and isinstance(u, dict):
            if str(pid) == str(me.get("id")):
                out.append(Result("Partner-Bot", "fail", "das ist dein eigener Bot", "Die ID des ANDEREN Bots eintragen."))
            elif u.get("bot"):
                out.append(Result("Partner-Bot", "ok", u.get("username", "?")))
            else:
                out.append(Result("Partner-Bot", "fail", f"{u.get('username')} ist kein Bot",
                                  "Rechtsklick auf den anderen BOT (nicht auf dessen Besitzer) → ID kopieren."))
        elif st == 404:
            out.append(Result("Partner-Bot", "fail", "unbekannte ID", "ID neu kopieren."))
    return out


# --- Modell -------------------------------------------------------------
def claude_cli_check(cfg, run=subprocess.run) -> Result:
    exe = cfg.get("claude_code.path", "claude")
    found = shutil.which(exe) or (exe if Path(exe).exists() else None)
    if not found:
        return Result("Claude Code", "fail", "Programm „claude“ nicht gefunden",
                      "Claude Code installieren (claude.com/claude-code), danach einmal im Terminal „claude“ starten und mit dem Abo einloggen.")
    try:
        r = run([found, "--version"], capture_output=True, text=True, timeout=30)
        ver = (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr) else "?"
    except (OSError, subprocess.SubprocessError) as e:
        return Result("Claude Code", "fail", f"startet nicht ({type(e).__name__})", "Neu installieren.")
    return Result("Claude Code", "ok", ver)


def api_key_conflict(cfg, env: dict) -> Result | None:
    if cfg.get("llm.provider") != "claude_code":
        return None
    var = cfg.get("llm.api_key_env", "ANTHROPIC_API_KEY")
    if env.get(var):
        return Result("API-Key bei Abo", "warn", f"{var} ist gesetzt",
                      "Der Bot gibt ihn nicht an Claude Code weiter, trotzdem besser leeren, damit keine Verwechslung entsteht.")
    return None


def ollama_check(cfg, get=http_get) -> Result:
    base = (cfg.get("llm.base_url") or "").rstrip("/")
    if not base:
        return Result("Modell-Server", "fail", "Base-URL fehlt", "z. B. http://localhost:11434/v1 eintragen.")
    st, data = get(f"{base}/models", {}, 5)
    if st != 200 or not isinstance(data, dict):
        return Result("Modell-Server", "fail", f"nicht erreichbar ({base})", "Ollama starten bzw. URL prüfen.")
    models = [m.get("id") for m in data.get("data", [])]
    want = cfg.get("llm.model")
    if want and models and want not in models:
        return Result("Modell-Server", "warn", f"Modell „{want}“ nicht gefunden",
                      "Vorhanden: " + ", ".join(models[:6]))
    return Result("Modell-Server", "ok", f"{len(models)} Modell(e)")


def model_request(cfg) -> Result:
    """Echte Testanfrage – kostet bei API einen Bruchteil eines Cents bzw. etwas Abo-Kontingent."""
    import time

    from guardrails import Decision
    from llm import LLM
    from prompting import build_system
    system = build_system(cfg, Decision(True, "test", "owner", 1, 1, True))
    who = cfg.get("bot.owner_name") or "Besitzer"
    msgs = [{"role": "user", "content": f"{who}: Kurzer Funktionstest – stell dich in einem Satz vor."}]
    t0 = time.time()
    try:
        text, tin, tout = asyncio.run(LLM(cfg).complete(system, msgs))
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {e}"[:300]
        fix = "Zugangsdaten und Modellname prüfen."
        if "authentication" in msg.lower() or "401" in msg:
            fix = "API-Key ungültig – in der Anthropic-Konsole neu erzeugen und setzen."
        elif cfg.get("llm.provider") == "claude_code":
            fix = "Im Terminal „claude“ starten und einloggen; prüfen, ob „claude -p hallo“ antwortet."
        return Result("Testanfrage", "fail", msg, fix)
    return Result("Testanfrage", "ok", f"{time.time() - t0:.1f} s, {tin + tout} Tokens – „{text.strip()[:140]}“")


# --- Gesamtablauf -------------------------------------------------------
def run_all(cfg, env: dict, with_request: bool = True, get=http_get) -> list[Result]:
    from settings_schema import check_consistency
    res = [check_python(), check_packages()]
    errors, warnings = check_consistency(cfg.get)
    if errors:
        res += [Result("Konfiguration", "fail", e, "Im Konfigurator korrigieren.") for e in errors]
    else:
        res.append(Result("Konfiguration", "ok", "gültig"))
    res += [Result("Hinweis", "warn", w) for w in warnings]

    res += discord_checks(cfg, env.get(cfg.get("discord.token_env", "DISCORD_TOKEN"), ""), get=get)

    provider = cfg.get("llm.provider", "anthropic")
    if provider == "claude_code":
        res.append(claude_cli_check(cfg))
        c = api_key_conflict(cfg, env)
        if c:
            res.append(c)
    elif provider == "anthropic":
        if not env.get(cfg.get("llm.api_key_env", "ANTHROPIC_API_KEY")):
            res.append(Result("API-Key", "fail", "nicht gesetzt",
                              "console.anthropic.com → API Keys → Create Key, im Konfigurator unter Zugangsdaten setzen."))
    else:
        res.append(ollama_check(cfg, get=get))

    blocked = any(r.status == "fail" and r.name in ("Pakete", "API-Key", "Claude Code", "Modell-Server") for r in res)
    if with_request and not blocked:
        res.append(model_request(cfg))
    elif with_request:
        res.append(Result("Testanfrage", "skip", "übersprungen – erst die Fehler oben beheben"))
    return res


def summary(results: list[Result]) -> str:
    fails = sum(r.status == "fail" for r in results)
    warns = sum(r.status == "warn" for r in results)
    if fails:
        return f"{fails} Fehler, {warns} Hinweis(e) – Bot noch nicht startklar"
    return "Startklar" + (f" ({warns} Hinweis(e))" if warns else "")


def load_env(env_path: Path) -> dict:
    """Werte aus .env plus Prozessumgebung (Prozess gewinnt nicht – .env ist maßgeblich)."""
    from dotenv import dotenv_values
    env = dict(os.environ)
    if env_path.exists():
        env.update({k: v for k, v in dotenv_values(env_path).items() if v is not None})
    return env
