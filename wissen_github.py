"""GitHub-Repos als Wissensquelle – nur lesend.

Der Bot lädt die eingetragenen Repos als Zip über die GitHub-API (kein git nötig) in einen
lokalen Zwischenspeicher neben der config.yaml (wissen-cache/github/<owner>-<repo>) und gibt sie
über denselben Lese-Server wie lokale Ordner frei. Übernommen werden nur Textdateien mit
erlaubter Endung; versteckte Ordner, .env- und Schlüsseldateien werden gar nicht erst entpackt.

Private Repos brauchen einen GitHub-Token nur mit Leserecht (Fine-grained: Contents = Read-only).
Der Token bleibt im Bot – Claude Code bekommt ihn nie zu sehen.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

API = "https://api.github.com"
TOKEN_ENV_DEFAULT = "GITHUB_TOKEN"
SPEC = re.compile(r"^(?:https?://github\.com/)?([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9._-]{1,100}?)(?:\.git)?/?(?:[@#](\S+))?$")
MARKER = ".quelle.json"


class RepoError(Exception):
    pass


def parse(spec: str) -> tuple[str, str, str | None]:
    """'owner/repo', 'https://github.com/owner/repo' oder mit '@branch' → (owner, repo, ref|None)."""
    m = SPEC.match((spec or "").strip())
    if not m:
        raise RepoError(f"„{spec}“ ist keine Repo-Angabe (Beispiel: BBZGames/Bratratz_lore oder …@main)")
    return m.group(1), m.group(2), m.group(3)


def repos(cfg) -> list[str]:
    return [str(r).strip() for r in (cfg.get("knowledge.github.repos") or []) if str(r).strip()]


def cache_root(cfg) -> Path:
    return Path(cfg.path).resolve().parent / "wissen-cache" / "github"


def repo_dir(cfg, spec: str) -> Path:
    owner, name, ref = parse(spec)
    return cache_root(cfg) / (f"{owner}-{name}" + (f"-{re.sub(r'[^A-Za-z0-9._-]', '_', ref)}" if ref else ""))


def token(cfg, env: dict) -> str:
    return env.get(cfg.get("knowledge.github.token_env") or TOKEN_ENV_DEFAULT, "")


def _headers(tok: str, accept: str = "application/vnd.github+json") -> dict:
    h = {"Accept": accept, "User-Agent": "CortexQuorumBot", "X-GitHub-Api-Version": "2022-11-28"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def http(url: str, headers: dict, timeout: int = 30, limit: int | None = None) -> tuple[int, bytes]:
    from updater import _ssl_context
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:  # noqa: S310 (feste https-Adresse)
            if limit is None:
                return r.status, r.read()
            buf = io.BytesIO()
            while chunk := r.read(1 << 16):
                buf.write(chunk)
                if buf.tell() > limit:
                    raise RepoError(f"Repo größer als {limit // (1024 * 1024)} MB – Grenze unter Erweitert anheben oder kleineres Repo wählen.")
            return r.status, buf.getvalue()
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b""
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, str(e).encode()


def _explain(status: int, spec: str, tok: str) -> str:
    if status == 0:
        return "GitHub nicht erreichbar – Internet prüfen."
    if status == 401:
        return "Token ungültig oder abgelaufen."
    if status in (403, 429):
        return "Zu viele Abfragen oder keine Berechtigung – später erneut bzw. Token prüfen."
    if status == 404:
        return ("nicht gefunden – Schreibweise prüfen; bei privaten Repos muss der Token Zugriff darauf haben."
                if tok else "nicht gefunden – Schreibweise prüfen. Privates Repo? Dann GITHUB_TOKEN setzen.")
    return f"Antwort {status}"


def info(spec: str, tok: str, get=http) -> dict:
    owner, name, ref = parse(spec)
    st, body = get(f"{API}/repos/{owner}/{name}", _headers(tok))
    if st != 200:
        raise RepoError(f"{owner}/{name}: {_explain(st, spec, tok)}")
    data = json.loads(body)
    return {"full_name": data.get("full_name"), "private": bool(data.get("private")),
            "ref": ref or data.get("default_branch") or "main", "size_kb": data.get("size", 0),
}


def token_can_write(tok: str, head=None) -> bool | None:
    """Darf der Token schreiben? Nur bei klassischen Tokens (ghp_…) abfragbar – über X-OAuth-Scopes.
    Fine-grained-Tokens (github_pat_…) verraten ihre Rechte nicht → None (unbekannt).
    Achtung: „permissions“ in der Repo-Antwort zeigt die Rechte des KONTOS, nicht des Tokens."""
    if not tok.startswith(("ghp_", "gho_")):
        return None
    if head is None:
        from updater import _ssl_context
        req = urllib.request.Request(API, headers=_headers(tok))
        try:
            with urllib.request.urlopen(req, timeout=15, context=_ssl_context()) as r:  # noqa: S310
                scopes = r.headers.get("X-OAuth-Scopes", "")
        except (urllib.error.URLError, TimeoutError, OSError):
            return None
    else:
        scopes = head(tok)
    found = {x.strip() for x in scopes.split(",") if x.strip()}
    return bool(found & {"repo", "public_repo", "write:org", "admin:org", "workflow"})


def head_sha(owner: str, name: str, ref: str, tok: str, get=http) -> str:
    st, body = get(f"{API}/repos/{owner}/{name}/commits/{ref}", _headers(tok, "application/vnd.github.sha"))
    if st != 200:
        raise RepoError(f"{owner}/{name}@{ref}: {_explain(st, f'{owner}/{name}', tok)}")
    return body.decode().strip()


def _wanted(rel: str, exts: set[str], deny) -> bool:
    parts = PurePosixPath(rel).parts
    if not parts or any(p.startswith(".") or p in ("node_modules", "__pycache__") for p in parts):
        return False
    name = parts[-1]
    return PurePosixPath(name).suffix.lower() in exts and not deny.search(name)


def extract(blob: bytes, dest: Path, exts: list[str], max_kb: int) -> int:
    """Nur erlaubte Textdateien aus dem GitHub-Zip entpacken (Oberordner wird entfernt)."""
    from wissen_ordner import DENY_NAME
    ext = {e.lower() if e.startswith(".") else "." + e.lower() for e in exts}
    tmp = dest.with_name(dest.name + ".neu")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    n = 0
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for zi in z.infolist():
            parts = PurePosixPath(zi.filename).parts
            if zi.is_dir() or len(parts) < 2 or ".." in parts or zi.filename.startswith("/"):
                continue
            rel = "/".join(parts[1:])
            if not _wanted(rel, ext, DENY_NAME) or zi.file_size > max_kb * 1024:
                continue
            target = tmp / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(zi))
            n += 1
    if dest.exists():
        shutil.rmtree(dest)
    tmp.rename(dest)
    return n


def marker(path: Path) -> dict:
    try:
        return json.loads((path / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def sync_one(cfg, spec: str, tok: str, force: bool = False, get=http) -> dict:
    """Ein Repo aktualisieren, falls sich der Stand geändert hat. Gibt einen Statusbericht zurück."""
    from knowledge import DEFAULT_EXT
    owner, name, _ = parse(spec)
    meta = info(spec, tok, get)
    sha = head_sha(owner, name, meta["ref"], tok, get)
    dest = repo_dir(cfg, spec)
    old = marker(dest)
    if not force and old.get("sha") == sha and dest.is_dir():
        old["ts"] = time.time()
        (dest / MARKER).write_text(json.dumps(old), encoding="utf-8")
        return {**old, "repo": meta["full_name"], "updated": False}
    limit = int(cfg.get("knowledge.github.max_mb", 100) or 100) * 1024 * 1024
    st, blob = get(f"{API}/repos/{owner}/{name}/zipball/{sha}", _headers(tok), timeout=120, limit=limit)
    if st != 200:
        raise RepoError(f"{owner}/{name}: Download fehlgeschlagen ({_explain(st, spec, tok)})")
    exts = cfg.get("knowledge.github.extensions") or cfg.get("knowledge.folders.extensions") or DEFAULT_EXT
    n = extract(blob, dest, exts, int(cfg.get("knowledge.folders.max_kb", 200) or 200))
    m = {"repo": meta["full_name"], "ref": meta["ref"], "sha": sha, "files": n, "ts": time.time(), "private": meta["private"]}
    (dest / MARKER).write_text(json.dumps(m), encoding="utf-8")
    return {**m, "updated": True}


def sync(cfg, env: dict, force: bool = False, get=http) -> list[dict]:
    """Alle eingetragenen Repos aktualisieren. Fehler pro Repo, der Rest läuft weiter."""
    tok = token(cfg, env)
    out = []
    for spec in repos(cfg):
        try:
            out.append({"spec": spec, "ok": True, **sync_one(cfg, spec, tok, force, get)})
        except (RepoError, ValueError, zipfile.BadZipFile, OSError) as e:
            out.append({"spec": spec, "ok": False, "error": str(e)})
    return out


def due(cfg) -> bool:
    """Ist eine Aktualisierung fällig (fehlender Zwischenspeicher oder älter als das Intervall)?"""
    every = max(5, int(cfg.get("knowledge.github.refresh_minutes", 60) or 60)) * 60
    for spec in repos(cfg):
        try:
            m = marker(repo_dir(cfg, spec))
        except RepoError:
            continue
        if time.time() - float(m.get("ts", 0)) > every:
            return True
    return False


def cached_dirs(cfg) -> list[str]:
    out = []
    for spec in repos(cfg):
        try:
            d = repo_dir(cfg, spec)
        except RepoError:
            continue
        if d.is_dir() and marker(d):
            out.append(str(d))
    return out
