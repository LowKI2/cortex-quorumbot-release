import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

import knowledge  # noqa: E402
from config import Config  # noqa: E402
from wissen_ordner import Folders, handle  # noqa: E402


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "Wissen"
    (root / "Projekte").mkdir(parents=True)
    (root / "Projekte" / "Eisenflut.md").write_text("# Eisenflut\nZeile zwei\nDrache Feuer\n" + "x\n" * 50, encoding="utf-8")
    (root / "notiz.txt").write_text("Drache im Keller", encoding="utf-8")
    (root / ".env").write_text("DISCORD_TOKEN=geheim", encoding="utf-8")
    (root / "passwoerter.txt").write_text("Drache 123", encoding="utf-8")
    (root / "bild.png").write_bytes(b"\x89PNG Drache")
    (root / ".git").mkdir()
    (root / ".git" / "config.md").write_text("Drache", encoding="utf-8")
    (root / "gross.md").write_text("Drache " * 400, encoding="utf-8")
    (tmp_path / "draussen.md").write_text("Drache draußen", encoding="utf-8")
    return root


def test_nur_erlaubte_dateien(tree):
    f = Folders([str(tree)], max_kb=1)
    files = f.list_files()
    assert "Wissen/Projekte/Eisenflut.md" in files and "Wissen/notiz.txt" in files
    for bad in (".env", "passwoerter", "bild.png", ".git", "gross.md"):
        assert bad not in files


def test_suche_findet_nur_freigegebenes(tree):
    out = Folders([str(tree)], max_kb=1).search("drache")
    assert "Eisenflut.md" in out and "notiz.txt" in out
    assert "passwoerter" not in out and "draußen" not in out and ".git" not in out
    with pytest.raises(ValueError):
        Folders([str(tree)]).search("x")


def test_lesen_mit_ausschnitt_und_ohne_ordnernamen(tree):
    f = Folders([str(tree)])
    out = f.read_file("Wissen/Projekte/Eisenflut.md", start_line=2, max_lines=2)
    assert "Zeile zwei" in out and "Drache Feuer" in out and "# Eisenflut" not in out and "weiterlesen" in out
    assert "Eisenflut" in f.read_file("Projekte/Eisenflut.md")         # nur ein Ordner → Name darf fehlen


@pytest.mark.parametrize("path", ["Wissen/../draussen.md", "../draussen.md", "Wissen/.env", "Wissen/.git/config.md",
                                  "Wissen/passwoerter.txt", "Wissen/bild.png"])
def test_lesen_blockiert(tree, path):
    with pytest.raises(ValueError):
        Folders([str(tree)]).read_file(path)


def test_mehrere_ordner_brauchen_namen(tree, tmp_path):
    other = tmp_path / "Notizen"
    other.mkdir()
    (other / "a.md").write_text("Hallo", encoding="utf-8")
    f = Folders([str(tree), str(other), str(tmp_path / "gibtsnicht")])
    assert set(f.roots) == {"Wissen", "Notizen"}
    assert "Hallo" in f.read_file("Notizen/a.md")
    with pytest.raises(ValueError, match="Unbekannter Ordner"):
        f.read_file("a.md")


def test_protokoll(tree):
    f = Folders([str(tree)])
    assert handle(f, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    init = handle(f, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"]["capabilities"] == {"tools": {}}
    names = [t["name"] for t in handle(f, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]]
    assert names == knowledge.FOLDER_TOOLS
    ok = handle(f, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search", "arguments": {"query": "Feuer"}}})
    assert not ok["result"]["isError"] and "Eisenflut" in ok["result"]["content"][0]["text"]
    bad = handle(f, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "read_file", "arguments": {"path": "../draussen.md"}}})
    assert bad["result"]["isError"]
    assert "error" in handle(f, {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "write_file"}})


def kcfg(tree, mv=False):
    return Config("x.yaml", data={"llm": {"provider": "claude_code"},
                                  "knowledge": {"mediavault": {"enabled": mv, "url": "https://mv.example:8445"},
                                                "folders": {"enabled": True, "paths": [str(tree)]}}})


def test_mcp_config_kombiniert(tree, tmp_path):
    import os
    c = kcfg(tree, mv=True)
    names = knowledge.allowed_tool_names(c)
    assert "mcp__ordner__read_file" in names and any(n.startswith("mcp__mediavault__") for n in names)
    path = knowledge.write_mcp_config(c, {knowledge.KEY_ENV: "k"})
    try:
        srv = json.loads(Path(path).read_text(encoding="utf-8"))["mcpServers"]
        assert set(srv) == {"mediavault", "ordner"}
        args = srv["ordner"]["args"]
        assert args[0].endswith("wissen_ordner.py") and args[args.index("--root") + 1] == str(tree)
    finally:
        os.unlink(path)
    only = kcfg(tree)
    assert knowledge.allowed_tool_names(only) == [f"mcp__ordner__{t}" for t in knowledge.FOLDER_TOOLS]
    p2 = knowledge.write_mcp_config(only, {})                       # ohne MediaVault kein Schlüssel nötig
    os.unlink(p2)
    empty = Config("x.yaml", data={"llm": {"provider": "claude_code"}, "knowledge": {"folders": {"enabled": True, "paths": []}}})
    assert not knowledge.enabled(empty)


def test_ordner_pruefung(tree, tmp_path):
    from checks import folder_checks
    r = folder_checks(kcfg(tree))
    assert r[0].status == "ok"
    missing = Config("x.yaml", data={"llm": {"provider": "claude_code"},
                                     "knowledge": {"folders": {"enabled": True, "paths": [str(tmp_path / "fehlt")]}}})
    assert any(x.status == "fail" for x in folder_checks(missing))
