"""!reset mit/ohne Speichern (beide Bots) und Dialoge speichern."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml  # noqa: E402

import verlauf  # noqa: E402

ME, PARTNER, OWNER = 1, 2, 10
CH = 100


class FakeChannel:
    def __init__(self, msgs):
        self.id, self.name, self.msgs, self.sent = CH, "ai-chat", msgs, []

    def history(self, limit=30, oldest_first=False, after=None, before=None):
        items = [m for m in self.msgs if (not after or m.id > after.id) and (not before or m.id < before.id)]
        items = sorted(items, key=lambda m: m.id, reverse=not oldest_first)[:limit]

        async def gen():
            for m in items:
                yield m
        return gen()

    async def send(self, text, **kw):
        self.sent.append(text)

    def typing(self):
        class T:
            async def __aenter__(self): pass
            async def __aexit__(self, *a): pass
        return T()


def m(i, author, text, bot=False, name=None):
    return NS(id=i, content=text, author=NS(id=author, bot=bot, display_name=name or f"U{author}", name=name or f"U{author}"))


def make_bot(tmp_path, **ctx):
    from bot import RundenBot
    from config import Config
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump({"bot": {"owner_id": OWNER, "name": "Cortex", "partner_bot_ids": [PARTNER]},
                                 "context": ctx}), encoding="utf-8")
    bot = RundenBot(Config(p))

    async def fake_llm(system, messages, use_knowledge=True):
        assert use_knowledge is False and "Basti: Wie heißt der Drache?" in messages[0]["content"]
        return "## Themen\n- Drache", 10, 5
    bot.llm.complete = fake_llm
    return bot


def test_reset_ohne_speichern_mir_egal(tmp_path):
    bot = make_bot(tmp_path)
    ch = FakeChannel([m(5, OWNER, "hallo", name="Basti")])
    asyncio.run(bot.reset_context(ch, 6, initiator=True))
    assert "Mir egal" in ch.sent[0] and ch.sent[0].strip().endswith(verlauf.RESET_START)
    assert bot.guard.state(CH).context_after_id == 6 and not (tmp_path / "verlauf").exists()
    # Neustart: Stand bleibt
    bot2 = make_bot(tmp_path)
    assert bot2.guard.state(CH).context_after_id == 6


def test_reset_mit_speichern_und_partner_bestaetigt(tmp_path):
    bot = make_bot(tmp_path, reset_save=True)
    ch = FakeChannel([m(5, OWNER, "Wie heißt der Drache?", name="Basti"), m(6, ME, "Ilzarah.", True, "Cortex")])
    asyncio.run(bot.reset_context(ch, 7, initiator=False))        # als Folge-Bot
    files = list((tmp_path / "verlauf").glob("*.md"))
    assert len(files) == 1 and "## Themen" in files[0].read_text(encoding="utf-8")
    assert "gespeichert (verlauf/" in ch.sent[0] and ch.sent[0].strip().endswith(verlauf.RESET_ACK)
    assert bot.guard.state(CH).summary.startswith("## Themen")
    from guardrails import Decision
    from prompting import build_system
    assert "Zusammenfassung vor dem letzten Reset" in build_system(bot.cfg, Decision(True, "", "owner"), bot.guard.state(CH).summary)


def test_marker_start_und_bestaetigung_unterscheiden():
    assert verlauf.is_reset_start("✅ x\n-# Kontext-Reset")
    assert not verlauf.is_reset_start("✅ x\n-# Kontext-Reset · bestätigt")      # keine Schleife
    assert verlauf.is_dialog_end("Fazit\n-# Runde 4/4 · Ende") and not verlauf.is_dialog_end("x\n-# Runde 2/4")


def test_dialog_speichern(tmp_path):
    from guardrails import Incoming
    bot = make_bot(tmp_path)
    g = bot.guard
    g.observe(Incoming(CH, OWNER, False, "!dialog 4 Godot oder HTML?", False, msg_id=10))
    g.observe(Incoming(CH, ME, True, "<@2> Godot!\n-# Runde 1/4", False, is_own=True, msg_id=11))
    g.observe(Incoming(CH, PARTNER, True, "<@1> HTML!\n-# Runde 2/4 · Ende", True, msg_id=12))
    st = g.state(CH)
    assert st.dialog_start_id == 10 and st.dialog_title == "Godot oder HTML?"
    ch = FakeChannel([m(9, OWNER, "vorher"), m(10, OWNER, "!dialog 4 Godot oder HTML?", name="Basti"),
                      m(11, ME, "<@2> Godot!\n-# Runde 1/4", True, "Cortex"), m(12, PARTNER, "<@1> HTML!\n-# Runde 2/4 · Ende", True, "Punky")])
    asyncio.run(bot.save_dialog(ch, 12, auto=True))
    f = list((tmp_path / "verlauf" / "dialoge").glob("*.md"))
    assert len(f) == 1 and "Godot-oder-HTML" in f[0].name
    text = f[0].read_text(encoding="utf-8")
    assert "# Dialog: Godot oder HTML?" in text and "**Punky:** @Cortex HTML!" in text and "vorher" not in text
    assert "Dialog gespeichert" in ch.sent[0]
