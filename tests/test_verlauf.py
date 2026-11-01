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
        self.guild, self.can_manage = NS(me=NS(id=ME)), True

    def history(self, limit=30, oldest_first=False, after=None, before=None):
        items = [m for m in self.msgs if (not after or m.id > after.id) and (not before or m.id < before.id)]
        items = sorted(items, key=lambda m: m.id, reverse=not oldest_first)[:limit]

        async def gen():
            for m in items:
                yield m
        return gen()

    async def send(self, text, **kw):
        self.sent.append(text)
        msg = NS(id=1000 + len(self.sent), content=text, pinned=False, author=NS(id=ME, bot=True, display_name="Bot", name="Bot"))
        self.msgs.append(msg)
        return msg

    def permissions_for(self, member):
        return NS(manage_messages=self.can_manage)

    async def purge(self, limit=None, before=None, check=None, bulk=True, reason=None):
        gone = [m for m in self.msgs if m.id < before.id and check(m)]
        self.msgs = [m for m in self.msgs if m not in gone]
        self.purged = gone
        return gone

    def typing(self):
        class T:
            async def __aenter__(self): pass
            async def __aexit__(self, *a): pass
        return T()


def m(i, author, text, bot=False, name=None, pinned=False):
    return NS(id=i, content=text, pinned=pinned, author=NS(id=author, bot=bot, display_name=name or f"U{author}", name=name or f"U{author}"))


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


def test_reset_loescht_chat_erst_nach_partner_bestaetigung(tmp_path):
    bot = make_bot(tmp_path, reset_delete=True)
    ch = FakeChannel([m(5, OWNER, "hallo", name="Basti"), m(6, PARTNER, "hi", True, "Punky"), m(7, OWNER, "wichtig", pinned=True)])

    async def flow():
        bot._purge_after_timeout = lambda *a: asyncio.sleep(0)      # Zeitlimit hier nicht abwarten
        await bot.reset_context(ch, 8, initiator=True)
        assert ch.id in bot.pending_purge and len(ch.msgs) == 4      # noch nichts gelöscht
        ack = m(2000, PARTNER, "✅ Punky: gespeichert\n" + verlauf.RESET_ACK, True, "Punky")
        ch.msgs.append(ack)
        bot.pending_purge.pop(ch.id)
        await bot.purge_chat(ch, ack.id)
    asyncio.run(flow())
    assert [x.id for x in ch.msgs][0] == 7 and "Chat geleert (4 Nachrichten)" in ch.sent[-1]


def test_ohne_recht_nur_eigene_nachrichten(tmp_path):
    bot = make_bot(tmp_path)
    ch = FakeChannel([m(5, OWNER, "hallo"), m(6, ME, "ich", True)])
    ch.can_manage = False
    asyncio.run(bot.purge_chat(ch, 6))
    assert [x.id for x in ch.msgs][0] == 5 and "Nachrichten verwalten" in ch.sent[-1]


def test_reset_wartet_auf_beide_menschen(tmp_path):
    """A (Basti) fragt an → nichts passiert; B (Benni) bestätigt → B setzt zurück, A folgt und löscht."""
    a_dir, b_dir = tmp_path / "a", tmp_path / "b"
    a_dir.mkdir()
    b_dir.mkdir()
    a = make_bot(a_dir, reset_save=True, reset_delete=True)
    b = make_bot(b_dir)
    ch = FakeChannel([m(5, OWNER, "Wie heißt der Drache?", name="Basti")])

    async def flow():
        await a.request_reset(ch, 6)
        req = ch.sent[-1]
        assert verlauf.is_reset_request(req) and "reagieren" in req
        assert a.guard.state(CH).context_after_id == 0               # noch nicht zurückgesetzt
        req_id = a.reset_requested[CH]
        b.note_partner_request(ch, req_id)
        await b.request_reset(ch, req_id + 1)                          # Benni schreibt !reset = Bestätigung
        start = ch.sent[-1]
        assert verlauf.is_reset_start(start) and "bestätigt" in start and CH not in b.reset_to_confirm
        await a.reset_context(ch, req_id + 2, initiator=False)          # A sieht das Startsignal
        assert verlauf.RESET_ACK in ch.sent[-2] and "Chat geleert" in ch.sent[-1]
        assert CH not in a.reset_requested and list((a_dir / "verlauf").glob("*.md"))
    asyncio.run(flow())


def test_bestaetigung_per_reaktion_nur_vom_eigenen_besitzer(tmp_path):
    b = make_bot(tmp_path)
    ch = FakeChannel([])
    b.get_channel = lambda cid: ch

    async def flow():
        b.note_partner_request(ch, 50)
        await b.on_raw_reaction_add(NS(channel_id=CH, message_id=50, emoji="✅", user_id=999))     # fremde Person
        assert CH in b.reset_to_confirm and not ch.sent
        await b.on_raw_reaction_add(NS(channel_id=CH, message_id=50, emoji="✅", user_id=OWNER))
        assert CH not in b.reset_to_confirm and verlauf.is_reset_start(ch.sent[-1])
    asyncio.run(flow())


def test_ohne_partner_sofort(tmp_path):
    from bot import RundenBot
    from config import Config
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump({"bot": {"owner_id": OWNER, "name": "Solo"}}), encoding="utf-8")
    bot = RundenBot(Config(p))
    ch = FakeChannel([])
    asyncio.run(bot.request_reset(ch, 9))
    assert "Mir egal" in ch.sent[-1] and bot.guard.state(CH).context_after_id == 9


def test_datenschutz_nur_besitzer_und_bots_an_die_ki(tmp_path):
    bot = make_bot(tmp_path, include_other_humans=False)
    ch = FakeChannel([m(1, OWNER, "meins", name="Basti"), m(2, 777, "fremd", name="Gast"),
                      m(3, PARTNER, "bot", True, "Punky"), m(4, PARTNER, "🎙️ **Benni:** gesagt", True, "Punky")])
    hist, _ = asyncio.run(bot.fetch_history(ch, 0))
    assert [h.content for h in hist] == ["meins", "bot"]
    (tmp_path / "x").mkdir()
    bot2 = make_bot(tmp_path / "x")
    hist2, _ = asyncio.run(bot2.fetch_history(ch, 0))
    assert len(hist2) == 4
