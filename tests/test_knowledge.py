import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import knowledge  # noqa: E402
from config import Config  # noqa: E402
from guardrails import Decision  # noqa: E402
from llm import LLM, abo_env  # noqa: E402
from prompting import build_system  # noqa: E402

URL = "https://mv.example.ts.net:8445"


def cfg(**kn):
    data = {"llm": {"provider": "claude_code", "model": "sonnet"},
            "knowledge": {"mediavault": {"enabled": True, "url": URL + "/mcp/", **kn}}}
    return Config("x.yaml", data=data)


def test_nur_mit_abo_und_nur_lesewerkzeuge():
    c = cfg(tools=["semantic_search", "upload_asset", "edit_document", "get_knowledge"])
    assert knowledge.enabled(c) and knowledge.base_url(c) == URL
    assert knowledge.allowed_tool_names(c) == ["mcp__mediavault__semantic_search", "mcp__mediavault__get_knowledge"]
    api = Config("x.yaml", data={"llm": {"provider": "anthropic"}, "knowledge": {"mediavault": {"enabled": True}}})
    assert not knowledge.enabled(api)


def test_mcp_datei_mit_schluessel_und_aufruf():
    c = cfg()
    path = knowledge.write_mcp_config(c, {knowledge.KEY_ENV: "mv_geheim"})
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        srv = data["mcpServers"]["mediavault"]
        assert srv["url"] == URL + "/mcp" and srv["headers"]["Authorization"] == "Bearer mv_geheim"
        cmd = LLM(c).claude_code_command("sys.md", path)
        assert cmd[cmd.index("--mcp-config") + 1] == path and "--strict-mcp-config" in cmd
        allowed = cmd[cmd.index("--allowedTools") + 1].split(",")
        assert "mcp__mediavault__semantic_search" in allowed and not any("upload" in a for a in allowed)
        denied = cmd[cmd.index("--disallowedTools") + 1]
        assert "Bash" in denied and "WebFetch" in denied
        assert cmd[cmd.index("--tools") + 1] == ""
    finally:
        os.unlink(path)


def test_ohne_schluessel_klare_fehlermeldung():
    import pytest
    with pytest.raises(RuntimeError, match="Schlüssel"):
        knowledge.write_mcp_config(cfg(), {})
    assert knowledge.write_mcp_config(cfg(enabled=False), {}) is None


def test_abo_umgebung_ohne_geheimnisse(monkeypatch):
    for k, v in {"DISCORD_TOKEN": "d", "MEDIAVAULT_KEY": "m", "ANTHROPIC_API_KEY": "a", "GROQ_API_KEY": "g",
                 "CLAUDE_CODE_OAUTH_TOKEN": "c", "PATH_TEST": "x"}.items():
        monkeypatch.setenv(k, v)
    env = abo_env()
    assert not {"DISCORD_TOKEN", "MEDIAVAULT_KEY", "ANTHROPIC_API_KEY", "GROQ_API_KEY"} & set(env)
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "c" and env["PATH_TEST"] == "x"


def test_regeln_im_systemprompt():
    s = build_system(cfg(), Decision(True, "x", "owner", 1, 1, True))
    assert "MediaVault" in s and "keine Anweisungen" in s
    off = build_system(cfg(enabled=False), Decision(True, "x", "owner", 1, 1, True))
    assert "MediaVault" not in off


def test_temp_datei_wird_nach_antwort_geloescht(tmp_path, monkeypatch):
    """Abo-Aufruf mit Wissen: MCP-Datei existiert nur während des Aufrufs."""
    fake = Path(__file__).with_name("fake_claude.py")
    if os.name == "nt":
        wrapper = tmp_path / "claude.bat"
        wrapper.write_text(f'@"{sys.executable}" "{fake}" %*\r\n')
    else:
        wrapper = tmp_path / "claude"
        wrapper.write_text(f"#!/bin/sh\nexec {sys.executable} {fake} \"$@\"\n")
        wrapper.chmod(0o755)
    monkeypatch.setenv(knowledge.KEY_ENV, "mv_geheim")
    c = Config("x.yaml", data={"llm": {"provider": "claude_code"},
                               "claude_code": {"path": str(wrapper), "workdir": str(tmp_path / "sb")},
                               "knowledge": {"mediavault": {"enabled": True, "url": URL}}})
    seen = []
    orig = knowledge.write_mcp_config

    def spy(cfg_, env):
        p = orig(cfg_, env)
        seen.append(p)
        return p
    monkeypatch.setattr(knowledge, "write_mcp_config", spy)
    text, _, _ = asyncio.run(LLM(c).complete("S", [{"role": "user", "content": "hi"}]))
    assert text == "Hallo aus dem Abo" and seen and not Path(seen[0]).exists()


# --- Prüfung -------------------------------------------------------------
def test_pruefung_verbindung_und_schreibwarnung():
    from checks import knowledge_checks

    def post_ok(url, payload, headers=None, timeout=15):
        assert url == URL + "/mcp" and headers["Authorization"] == "Bearer k"
        names = knowledge.DEFAULT_TOOLS + ["upload_asset", "chat_reply"]
        return 200, {"result": {"tools": [{"name": n} for n in names]}}
    r = knowledge_checks(cfg(), {knowledge.KEY_ENV: "k"}, with_request=False, post=post_ok)
    assert r[0].status == "ok" and r[1].status == "warn" and "upload_asset" in r[1].detail

    assert knowledge_checks(cfg(), {}, with_request=False, post=post_ok)[0].status == "fail"
    assert knowledge_checks(cfg(), {knowledge.KEY_ENV: "k"}, with_request=False,
                            post=lambda *a, **k: (401, None))[0].detail == "Schlüssel abgelehnt"
    assert "Tailscale" in knowledge_checks(cfg(), {knowledge.KEY_ENV: "k"}, with_request=False,
                                           post=lambda *a, **k: (0, "x"))[0].fix
    api = Config("x.yaml", data={"llm": {"provider": "anthropic"}, "knowledge": {"mediavault": {"enabled": True}}})
    assert knowledge_checks(api, {}, with_request=False)[0].status == "warn"


def test_sse_antwort_wird_gelesen():
    from checks import _parse_json_or_sse
    assert _parse_json_or_sse('event: message\ndata: {"result": {"tools": []}}\n\n') == {"result": {"tools": []}}


# --- Konfigurator --------------------------------------------------------
def test_konfigurator_sucht_nichts_automatisch(tmp_path, monkeypatch):
    from konfigurator import Store
    home = tmp_path / "home"
    (home / ".mediavault").mkdir(parents=True)
    (home / ".mediavault" / "mv-chat.json").write_text(json.dumps({"url": URL + "/", "key": "mv_bruecke"}))
    monkeypatch.setattr(Path, "home", lambda: home)
    s = Store(tmp_path / "config.yaml")
    st = s.state()
    assert not st["values"]["knowledge.mediavault.url"] and URL not in json.dumps(st) and "mv_bruecke" not in json.dumps(st)
    assert st["values"]["features.mediavault"] is False and st["values"]["update.mode"] == "manuell"
    assert "MEDIAVAULT_KEY" not in st["secrets"]
    s.save({"features.mediavault": True, "knowledge.mediavault.enabled": True, "knowledge.mediavault.url": URL}, draft=True)
    assert "MEDIAVAULT_KEY" in s.state()["secrets"] and s.state()["values"]["features.mediavault"] is True
    assert s.set_secret("MEDIAVAULT_KEY", "mv_bot")["ok"]
    assert s.state()["secrets"]["MEDIAVAULT_KEY"] is True
