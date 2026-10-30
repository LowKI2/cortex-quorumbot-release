import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

import updater  # noqa: E402
from version import ASSET_PYTHON, VERSION  # noqa: E402

NEW = "9.9.9"


def make_zip(files: dict[str, bytes], prefix=f"CortexQuorumBot-v{NEW}") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, b in files.items():
            z.writestr(f"{prefix}/{n}" if prefix else n, b)
    return buf.getvalue()


def pkg(extra=None):
    files = {"version.py": f'VERSION = "{NEW}"\n'.encode(), "bot.py": b"neu", "neu.py": b"x",
             "start.bat": b"@echo off\r\n", "config.yaml": b"FREMD", ".env": b"FREMD=1"}
    files.update(extra or {})
    return make_zip(files)


def fake_fetch(blob, tag=f"v{NEW}", digest=True, asset=ASSET_PYTHON):
    def fetch(url, timeout=20, accept=""):
        if url == updater.API_LATEST:
            a = {"name": asset, "browser_download_url": "https://x/dl", "size": len(blob)}
            if digest:
                a["digest"] = "sha256:" + hashlib.sha256(blob).hexdigest()
            return json.dumps({"tag_name": tag, "name": tag, "body": "Neu!", "assets": [a]}).encode()
        assert url == "https://x/dl"
        return blob
    return fetch


@pytest.fixture
def app(tmp_path):
    (tmp_path / "version.py").write_text(f'VERSION = "{VERSION}"\n')
    (tmp_path / "bot.py").write_text("alt")
    (tmp_path / "start.bat").write_bytes(b"@echo off\r\n")
    (tmp_path / "config.yaml").write_text("MEINE")
    (tmp_path / ".env").write_text("DISCORD_TOKEN=geheim")
    return tmp_path


def test_versionen_vergleichen():
    assert updater.parse_version("v0.10.0") > updater.parse_version("0.9.9")
    assert updater.parse_version("0.5.0") == updater.parse_version("v0.5.0")


def test_check_meldet_update():
    info = updater.check(fake_fetch(pkg()))
    assert info["ok"] and info["available"] and info["latest"] == NEW and info["digest"].startswith("sha256:")
    same = updater.check(fake_fetch(pkg(), tag=f"v{VERSION}"))
    assert same["ok"] and not same["available"]
    gone = updater.check(fake_fetch(pkg(), asset="anderes.zip"))
    assert not gone["available"] and "fehlt" in gone["errors"][0]
    def down(*a, **k):
        raise OSError("weg")
    assert not updater.check(down)["ok"]


def test_install_tauscht_programm_behaelt_konfig_und_sichert(app):
    fetch = fake_fetch(pkg())
    r = updater.install(updater.check(fetch), fetch, target=app)
    assert r["ok"], r
    assert (app / "bot.py").read_text() == "neu" and (app / "neu.py").exists()
    assert (app / "config.yaml").read_text() == "MEINE" and (app / ".env").read_text() == "DISCORD_TOKEN=geheim"
    assert "start.bat" not in r["changed"]                       # unverändert = nicht angefasst
    assert (app / updater.BACKUP_DIR / f"v{VERSION}" / "bot.py").read_text() == "alt"
    back = updater.rollback(app)
    assert back["ok"] and (app / "bot.py").read_text() == "alt" and not (app / "neu.py").exists()
    assert (app / "config.yaml").read_text() == "MEINE"


def test_falsche_pruefsumme_installiert_nichts(app):
    fetch = fake_fetch(pkg())
    info = updater.check(fetch)
    info["digest"] = "sha256:" + "0" * 64
    r = updater.install(info, fetch, target=app)
    assert not r["ok"] and "Prüfsumme" in r["errors"][0] and (app / "bot.py").read_text() == "alt"


def test_pfad_tricks_und_falsche_version(app):
    bad = make_zip({"../boese.py": b"x"}, prefix="")
    with pytest.raises(updater.UpdateError):
        updater.verify(bad, "", "python", NEW)
    with pytest.raises(updater.UpdateError):
        updater.verify(make_zip({"x/../../boese.py": b"x"}, prefix=""), "", "python", NEW)
    wrong = pkg({"version.py": b'VERSION = "1.0.0"'})
    with pytest.raises(updater.UpdateError, match="passt nicht"):
        updater.verify(wrong, "", "python", NEW)
    with pytest.raises(updater.UpdateError, match="exe"):
        updater.verify(pkg(), "", "exe", NEW)


def test_entwicklungsordner_wird_nie_ueberschrieben(app):
    (app / ".git").mkdir()
    fetch = fake_fetch(pkg())
    assert not updater.install(updater.check(fetch), fetch, target=app)["ok"]
    assert (app / "bot.py").read_text() == "alt"


def test_geschuetzte_pfade():
    for p in ("config.yaml", ".env", "config.overrides.json", "config.budget.json", ".venv/x.py", ".git/HEAD", "bot.log"):
        assert updater.protected(p), p
    for p in ("bot.py", "tests/x.py", "konfigurator.html", "CortexQuorumBot.exe"):
        assert not updater.protected(p), p


def test_exe_variante_tauscht_exe(app, monkeypatch):
    blob = make_zip({"CortexQuorumBot.exe": b"MZneu", "start.bat": b"@echo neu\r\n"})
    (app / "CortexQuorumBot.exe").write_bytes(b"MZalt")
    info = {"ok": True, "available": True, "latest": NEW, "current": VERSION, "variant": "exe",
            "asset_url": "https://x/dl", "digest": "sha256:" + hashlib.sha256(blob).hexdigest()}
    r = updater.install(info, lambda *a, **k: blob, target=app)
    assert r["ok"] and (app / "CortexQuorumBot.exe").read_bytes() == b"MZneu"


def test_auto_update_modi(monkeypatch):
    calls = []
    monkeypatch.setattr(updater, "is_dev", lambda *a: False)
    monkeypatch.setattr(updater, "check", lambda *a, **k: {"ok": True, "available": True, "latest": NEW})
    monkeypatch.setattr(updater, "install", lambda info: calls.append("install") or {"ok": True, "installed": NEW})
    monkeypatch.setattr(updater, "restart", lambda *a, **k: calls.append("restart"))
    log = []
    assert updater.auto_update("manuell", "bot", "c.yaml", log.append) is False and not calls
    assert updater.auto_update("hinweis", "bot", "c.yaml", log.append) is False and "verfügbar" in log[-1] and not calls
    assert updater.auto_update("automatisch", "bot", "c.yaml", log.append) is True and calls == ["install", "restart"]


# --- Profilbild ----------------------------------------------------------
def test_profilbild(tmp_path):
    from konfigurator import Store
    s = Store(tmp_path / "config.yaml")
    assert not s.set_avatar("data:image/png;base64,AAAA")["ok"]            # ohne Token
    (tmp_path / ".env").write_text("DISCORD_TOKEN=t\n")
    sent = []
    def patch(url, payload, headers):
        sent.append(payload)
        return 200, {}
    assert s.set_avatar("data:image/png;base64,iVBORw0KGgo=", patch=patch)["ok"]
    assert sent[-1]["avatar"].startswith("data:image/png") and s.set_avatar("", patch=patch)["ok"] and sent[-1] == {"avatar": None}
    assert not s.set_avatar("data:text/html;base64,PGI+", patch=patch)["ok"]
    assert "Minuten" in s.set_avatar("data:image/png;base64,AAAA", patch=lambda *a: (429, {}))["errors"][0]
    prof = s.bot_profile(get=lambda url, h: (200, {"id": "123456789012345678", "username": "Nova", "avatar": "abc"}))
    assert prof["avatar_url"].endswith("/123456789012345678/abc.png?size=128")


def test_knowledge_startet_ordnerserver_ueber_version_command(tmp_path, monkeypatch):
    import knowledge
    import version
    from config import Config
    c = Config("x.yaml", data={"llm": {"provider": "claude_code"}, "knowledge": {"folders": {"enabled": True, "paths": [str(tmp_path)]}}})
    e = knowledge.folder_server_entry(c)
    assert e["args"][0].endswith("wissen_ordner.py")
    monkeypatch.setattr(version, "frozen", lambda: True)
    e = knowledge.folder_server_entry(c)
    assert e["command"] == sys.executable and e["args"][0] == "wissen-ordner"


def test_standard_avatar_und_aufraeumen(tmp_path):
    from konfigurator import Store
    (tmp_path / ".env").write_text("DISCORD_TOKEN=t\n")
    sent = []
    assert Store(tmp_path / "config.yaml").set_avatar("standard", patch=lambda u, p, h: sent.append(p) or (200, {}))["ok"]
    assert sent[0]["avatar"].startswith("data:image/png;base64,iVBOR")
    (tmp_path / "CortexQuorumBot.exe.alt").write_bytes(b"x")
    (tmp_path / "bot.py.neu").write_bytes(b"x")
    assert updater.cleanup_old(tmp_path) == 2 and not list(tmp_path.glob("*.alt"))


def test_bot_beenden_ohne_lauf(tmp_path):
    from konfigurator import Store
    assert not Store(tmp_path / "config.yaml").stop_bot()["ok"]
