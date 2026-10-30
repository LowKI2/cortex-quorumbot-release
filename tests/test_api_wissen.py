"""Wissen über die Anthropic-API bzw. OpenAI-kompatible API: der Bot führt die Lese-Werkzeuge selbst aus."""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import Config  # noqa: E402
from llm import LLM  # noqa: E402


def cfg(tmp_path, provider="anthropic", **kn):
    w = tmp_path / "Wissen"
    w.mkdir(exist_ok=True)
    (w / "lore.md").write_text("Der Drache heißt Ilzarah.", encoding="utf-8")
    (w / ".env").write_text("DISCORD_TOKEN=geheim", encoding="utf-8")
    return Config(str(tmp_path / "config.yaml"), data={"llm": {"provider": provider, "model": "m"},
                  "knowledge": {"folders": {"enabled": True, "paths": [str(w)]}, **kn}})


class FakeAnthropic:
    """Erst Werkzeug search, dann read_file auf .env (muss scheitern), dann Antwort."""
    def __init__(self):
        self.calls = []

    async def create(self, *, max_tokens, messages, model, system=None, tools=None, timeout=None):
        self.calls.append({"messages": json.loads(json.dumps(messages, default=str)), "tools": tools})
        n = len(self.calls)
        usage = NS(input_tokens=10, output_tokens=5)
        if n == 1:
            return NS(content=[NS(type="text", text="Ich suche."), NS(type="tool_use", id="t1", name="search", input={"query": "drache"})], usage=usage)
        if n == 2:
            return NS(content=[NS(type="tool_use", id="t2", name="read_file", input={"path": "Wissen/.env"})], usage=usage)
        return NS(content=[NS(type="text", text="Der Drache heißt Ilzarah (lore.md).")], usage=usage)


def run(llm, client, provider="anthropic"):
    llm._client_for = lambda: (provider, client)
    return asyncio.run(llm.complete("S", [{"role": "user", "content": "Wie heißt der Drache?"}]))


def test_anthropic_werkzeuge_lesen_und_sperren(tmp_path):
    fake = FakeAnthropic()
    text, tin, tout = run(LLM(cfg(tmp_path)), NS(messages=fake))
    assert text.startswith("Der Drache heißt Ilzarah") and tin == 30 and tout == 15
    assert [t["name"] for t in fake.calls[0]["tools"]] == ["list_files", "search", "read_file"]
    r1 = fake.calls[1]["messages"][-1]["content"][0]
    assert r1["type"] == "tool_result" and r1["tool_use_id"] == "t1" and "lore.md" in r1["content"]
    r2 = fake.calls[2]["messages"][-1]["content"][0]
    assert r2.get("is_error") and "geheim" not in r2["content"]          # versteckte Datei bleibt zu


def test_ohne_wissen_keine_werkzeuge(tmp_path):
    fake = FakeAnthropic()
    c = Config(str(tmp_path / "c.yaml"), data={"llm": {"provider": "anthropic", "model": "m"}})
    text, _, _ = run(LLM(c), NS(messages=fake))
    assert fake.calls[0]["tools"] is None and text == "Ich suche."


def test_schrittgrenze(tmp_path):
    class Endlos(FakeAnthropic):
        async def create(self, **kw):
            self.calls.append(kw)
            u = NS(input_tokens=1, output_tokens=1)
            if kw.get("tools"):
                return NS(content=[NS(type="tool_use", id=f"t{len(self.calls)}", name="list_files", input={})], usage=u)
            return NS(content=[NS(type="text", text="fertig")], usage=u)
    fake = Endlos()
    text, _, _ = run(LLM(cfg(tmp_path, max_tool_rounds=2)), NS(messages=fake))
    assert text == "fertig" and len(fake.calls) == 3 and fake.calls[-1].get("tools") is None


def test_openai_kompatibel(tmp_path):
    calls = []

    class Completions:
        async def create(self, *, model, max_tokens, messages, tools=None, **kw):
            calls.append({"messages": json.loads(json.dumps(messages)), "tools": tools})
            u = NS(prompt_tokens=3, completion_tokens=2)
            if len(calls) == 1:
                tc = NS(id="c1", function=NS(name="read_file", arguments='{"path": "lore.md"}'))
                return NS(choices=[NS(message=NS(content=None, tool_calls=[tc]))], usage=u)
            return NS(choices=[NS(message=NS(content="Ilzarah.", tool_calls=None))], usage=u)
    text, tin, _ = run(LLM(cfg(tmp_path, provider="openai")), NS(chat=NS(completions=Completions())), "openai")
    assert text == "Ilzarah." and tin == 6 and calls[0]["tools"][0]["type"] == "function"
    tool_msg = calls[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and "Ilzarah" in tool_msg["content"]


def test_mediavault_bleibt_abo_only(tmp_path):
    import knowledge
    c = Config("x.yaml", data={"llm": {"provider": "anthropic"}, "knowledge": {"mediavault": {"enabled": True, "url": "https://x"}}})
    assert not knowledge.mediavault_on(c) and knowledge.reader(c) is None
