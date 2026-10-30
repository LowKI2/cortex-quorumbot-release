"""Updates aus dem öffentlichen Release-Repo – für Python-Variante und Windows-exe.

    python updater.py              Stand anzeigen
    python updater.py --install    neueste Version installieren
    python updater.py --rollback   vorige Version wiederherstellen

Ablauf beim Installieren:
  1. Neueste Version über die GitHub-API abfragen (nur das öffentliche Release-Repo).
  2. Passendes Paket laden (CortexQuorumBot.zip bzw. CortexQuorumBot-Windows.zip) und die
     SHA-256-Prüfsumme gegen die Angabe von GitHub prüfen.
  3. Alle Dateien, die ersetzt werden, nach .update-sicherung/v<alt>/ sichern.
  4. Nur Programmdateien austauschen. config.yaml, .env, config.*.json, .venv usw. werden nie angefasst.
In einem Entwicklungsordner (mit .git) wird nie installiert – dort gilt git.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from version import ASSET_EXE, EXE_NAME, RELEASE_REPO, VERSION, app_dir, asset_name, frozen, variant

API_LATEST = f"https://api.github.com/repos/{RELEASE_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{RELEASE_REPO}/releases/latest"
BACKUP_DIR = ".update-sicherung"
MODES = ["manuell", "hinweis", "automatisch"]
RESTART_CODE = 75            # Startskripte schließen ihr Fenster bei diesem Code, statt auf eine Taste zu warten

PROTECTED_DIRS = {".git", ".venv", BACKUP_DIR, "claude-sandbox", "__pycache__", "dist", "build"}
PROTECTED_FILE = re.compile(r"^(\.env.*|config\.yaml.*|.*\.overrides\.json|.*\.status\.json|.*\.budget\.json|.*\.log)$", re.I)


class UpdateError(Exception):
    pass


# --- Hilfen ---------------------------------------------------------------
def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", (v or "").split("-")[0])
    return tuple(int(n) for n in nums[:3]) or (0,)


def is_dev(target: Path | None = None) -> bool:
    return ((target or app_dir()) / ".git").exists()


def protected(rel: str) -> bool:
    parts = PurePosixPath(rel).parts
    return any(p in PROTECTED_DIRS for p in parts[:-1]) or bool(PROTECTED_FILE.match(parts[-1]))


def _ssl_context():
    import ssl
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def http_get(url: str, timeout: int = 20, accept: str = "application/json") -> bytes:
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": f"CortexQuorumBot/{VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:   # noqa: S310 (feste https-Adresse)
        return r.read()


# --- Abfrage --------------------------------------------------------------
def check(fetch=http_get) -> dict:
    """Neueste Version abfragen. Gibt immer ein dict zurück (ok=False bei Fehlern)."""
    base = {"current": VERSION, "variant": variant(), "dev": is_dev(), "page": RELEASES_PAGE}
    try:
        data = json.loads(fetch(API_LATEST))
    except Exception as e:  # noqa: BLE001
        return {**base, "ok": False, "errors": [f"Release-Repo nicht erreichbar ({type(e).__name__}). Internet prüfen."]}
    tag = str(data.get("tag_name") or "")
    asset = next((a for a in data.get("assets") or [] if a.get("name") == asset_name()), None)
    latest = tag.lstrip("v")
    info = {**base, "ok": True, "latest": latest, "tag": tag, "title": data.get("name") or tag,
            "notes": (data.get("body") or "")[:4000], "available": parse_version(latest) > parse_version(VERSION)}
    if asset:
        info.update(asset_url=asset.get("browser_download_url"), size=asset.get("size"), digest=asset.get("digest") or "")
    elif info["available"]:
        info["available"] = False
        info["errors"] = [f"Im Release {tag} fehlt das Paket {asset_name()}."]
    return info


# --- Installieren ---------------------------------------------------------
def _members(zf: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    """Dateien im Paket ohne den Oberordner, mit Schutz gegen Pfad-Tricks."""
    out = {}
    for zi in zf.infolist():
        if zi.is_dir():
            continue
        parts = PurePosixPath(zi.filename.replace("\\", "/")).parts
        if len(parts) < 2 or zi.filename.startswith("/") or ".." in parts or ":" in parts[0]:
            raise UpdateError(f"Ungültiger Pfad im Paket: {zi.filename}")
        rel = "/".join(parts[1:])
        if protected(rel):
            continue                                  # Konfiguration im Paket wird nie übernommen
        out[rel] = zi
    return out


def verify(blob: bytes, digest: str, want_variant: str, latest: str) -> dict[str, bytes]:
    if digest:
        algo, _, want = digest.partition(":")
        if algo.lower() != "sha256" or hashlib.sha256(blob).hexdigest() != want.lower():
            raise UpdateError("Prüfsumme stimmt nicht – Download beschädigt oder verändert. Nichts installiert.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as e:
        raise UpdateError("Paket ist kein gültiges Zip.") from e
    files = {rel: zf.read(zi) for rel, zi in _members(zf).items()}
    if want_variant == "exe":
        if EXE_NAME not in files:
            raise UpdateError(f"{EXE_NAME} fehlt im Paket.")
    else:
        m = re.search(rb'VERSION\s*=\s*"([^"]+)"', files.get("version.py", b""))
        if not m or parse_version(m.group(1).decode()) != parse_version(latest):
            raise UpdateError("Paket passt nicht zur angekündigten Version.")
    return files


def _write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".neu")
    tmp.write_bytes(data)
    try:
        os.replace(tmp, path)
    except PermissionError:
        # Laufende exe kann unter Windows nicht überschrieben, aber umbenannt werden.
        alt = path.with_name(path.name + ".alt")
        if alt.exists():
            alt.unlink()
        os.replace(path, alt)
        os.replace(tmp, path)


def apply(files: dict[str, bytes], target: Path, old_version: str) -> dict:
    backup = target / BACKUP_DIR / f"v{old_version}"
    if backup.exists():
        shutil.rmtree(backup)
    backup.mkdir(parents=True)
    changed, added = [], []
    for rel, data in sorted(files.items()):
        dst = target / rel
        if dst.exists():
            if dst.read_bytes() == data:
                continue
            (backup / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, backup / rel)
            changed.append(rel)
        else:
            added.append(rel)
    (backup / "_update.json").write_text(json.dumps({"version": old_version, "changed": changed, "added": added,
                                                     "ts": time.time()}, indent=1), encoding="utf-8")
    for rel in changed + added:
        _write(target / rel, files[rel])
    return {"changed": changed, "added": added,
            "requirements_changed": "requirements.txt" in changed + added}


def install(info: dict | None = None, fetch=http_get, target: Path | None = None) -> dict:
    target = target or app_dir()
    if is_dev(target):
        return {"ok": False, "errors": ["Entwicklungsordner (mit .git) – hier bitte per git aktualisieren."]}
    info = info or check(fetch)
    if not info.get("ok"):
        return info
    if not info.get("available"):
        return {"ok": False, "errors": info.get("errors") or [f"Schon aktuell (v{VERSION})."]}
    try:
        blob = fetch(info["asset_url"], timeout=120, accept="application/octet-stream")
        files = verify(blob, info.get("digest", ""), info.get("variant", variant()), info["latest"])
        res = apply(files, target, info.get("current", VERSION))
    except UpdateError as e:
        return {"ok": False, "errors": [str(e)]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "errors": [f"Update fehlgeschlagen: {type(e).__name__}: {e}"]}
    return {"ok": True, "installed": info["latest"], "from": info.get("current", VERSION), **res,
            "warnings": [] if info.get("digest") else ["GitHub hat keine Prüfsumme geliefert – nur Paketinhalt geprüft."]}


def backups(target: Path | None = None) -> list[Path]:
    root = (target or app_dir()) / BACKUP_DIR
    if not root.is_dir():
        return []
    return sorted((p for p in root.iterdir() if (p / "_update.json").exists()),
                  key=lambda p: json.loads((p / "_update.json").read_text(encoding="utf-8")).get("ts", 0))


def rollback(target: Path | None = None) -> dict:
    target = target or app_dir()
    if is_dev(target):
        return {"ok": False, "errors": ["Entwicklungsordner (mit .git) – hier bitte per git zurücksetzen."]}
    bks = backups(target)
    if not bks:
        return {"ok": False, "errors": ["Keine Sicherung vorhanden."]}
    bk = bks[-1]
    meta = json.loads((bk / "_update.json").read_text(encoding="utf-8"))
    for rel in meta.get("changed", []):
        _write(target / rel, (bk / rel).read_bytes())
    for rel in meta.get("added", []):
        p = target / rel
        if p.exists() and not protected(rel):
            try:
                p.unlink()
            except PermissionError:
                os.replace(p, p.with_name(p.name + ".alt"))
    shutil.rmtree(bk)
    return {"ok": True, "restored": meta.get("version")}


# --- Neustart -------------------------------------------------------------
def restart(kind: str, cfg_path: str | Path, extra: list[str] | None = None):
    """Programmteil (bot/konfigurator) frisch starten – unter Windows über das Startskript,
    damit neue Pakete installiert werden. Der Aufrufer beendet sich danach mit RESTART_CODE."""
    from version import command
    d = app_dir()
    if sys.platform == "win32":
        bat = d / ("start.bat" if kind == "bot" else "konfigurator.bat")
        subprocess.Popen(["cmd", "/c", "start", "", str(bat), *(extra or [])], cwd=str(d))
    else:
        subprocess.Popen(command(kind, str(cfg_path), *(extra or [])), cwd=str(d), start_new_session=True)


def auto_update(mode: str, kind: str, cfg_path, log=print) -> bool:
    """Beim Start: bei 'automatisch' installieren und neu starten (True = Aufrufer soll sich beenden)."""
    if mode not in ("hinweis", "automatisch") or is_dev():
        return False
    info = check()
    if not info.get("ok") or not info.get("available"):
        return False
    if mode == "hinweis":
        log(f"Update verfügbar: v{info['latest']} (installiert: v{VERSION}) – im Konfigurator unter „Updates“.")
        return False
    log(f"Installiere Update v{info['latest']} …")
    res = install(info)
    if not res.get("ok"):
        log("Update fehlgeschlagen: " + " ".join(res.get("errors", [])))
        return False
    log(f"Update auf v{res['installed']} installiert – starte neu.")
    restart(kind, cfg_path)
    return True


def main() -> int:
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Updates für Cortex QuorumBot")
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    a = ap.parse_args()
    if a.rollback:
        r = rollback()
        print(f"Wiederhergestellt: v{r['restored']}" if r["ok"] else r["errors"][0])
        return 0 if r["ok"] else 1
    info = check()
    if not info["ok"]:
        print(info["errors"][0])
        return 1
    print(f"Installiert: v{VERSION} ({variant()}) · Neueste: v{info['latest']}")
    if not info["available"]:
        print("Aktuell.")
        return 0
    if not a.install:
        print("Update verfügbar – mit --install installieren oder im Konfigurator unter „Updates“.")
        return 0
    r = install(info)
    print(f"Installiert: v{r['installed']} – Bot und Konfigurator neu starten." if r["ok"] else r["errors"][0])
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
