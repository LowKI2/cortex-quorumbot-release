import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from config import Config  # noqa: E402
from llm import LLM, render_transcript  # noqa: E402

FAKE = Path(__file__).with_name("fake_claude.py")


def make(tmp_path, **cc):
    if os.name == "nt":   # Windows: .bat statt Shell-Skript
        wrapper = tmp_path / "claude.bat"
        wrapper.write_text(f'@"{sys.executable}" "{FAKE}" %*\r\n')
    else:
        wrapper = tmp_path / "claude"
        wrapper.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE} \"$@\"\n")
        wrapper.chmod(0o755)
    data = {"llm": {"provider": "claude_code", "model": "sonnet"},
            "claude_code": {"path": str(wrapper), "workdir": str(tmp_path / "sb"), **cc}}
    return LLM(Config(tmp_path / "x.yaml", data=data))


def test_abo_aufruf_ohne_werkzeuge(tmp_path):
    llm = make(tmp_path)
    cmd = llm.claude_code_command("sys.md")
    assert "-p" in cmd and cmd[cmd.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in cmd and "--allowedTools" not in cmd and "--mcp-config" not in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    text, tin, tout = asyncio.run(llm.complete("System", [{"role": "user", "content": "Max: hi"}]))
    assert text == "Hallo aus dem Abo" and (tin, tout) == (5, 7)


def test_abo_mit_freigegebenen_werkzeugen(tmp_path):
    llm = make(tmp_path, mcp_config="mcp.json", allowed_tools=["mcp__cortex__read_note"])
    cmd = llm.claude_code_command("sys.md")
    assert cmd[cmd.index("--mcp-config") + 1] == "mcp.json"
    assert cmd[cmd.index("--allowedTools") + 1] == "mcp__cortex__read_note"


def test_abo_fehler_wird_gemeldet(tmp_path):
    llm = make(tmp_path)
    with pytest.raises(RuntimeError, match="Limit erreicht"):
        asyncio.run(llm.complete("S", [{"role": "user", "content": "FEHLER"}]))


def test_transcript_markiert_eigene_beitraege():
    t = render_transcript([{"role": "user", "content": "Max: frage"},
                           {"role": "assistant", "content": "antwort"}])
    assert "Max: frage" in t and "[Du]: antwort" in t


def test_abo_gibt_api_key_nicht_weiter(tmp_path, monkeypatch):
    from llm import abo_env
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert "ANTHROPIC_API_KEY" not in abo_env()
    llm = make(tmp_path)
    text, _, _ = asyncio.run(llm.complete("S", [{"role": "user", "content": "hi"}]))
    assert text == "Hallo aus dem Abo"
