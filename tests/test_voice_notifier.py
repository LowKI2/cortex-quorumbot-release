"""Abnahme laut Vault-Notiz „Discord Voice-Join-Melder“ plus Randfälle."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import discord  # noqa: E402

from voice_notifier import VoiceNotifier, attach_voice_notifier  # noqa: E402

VOICE, VOICE2, OTHER_VOICE, TEXT = 111111111111111111, 111111111111111112, 999999999999999999, 222222222222222222
GUILD, GUILD2 = 700000000000000001, 700000000000000002


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


class FakeText:
    def __init__(self, fail=None):
        self.sent = []
        self.fail = fail

    async def send(self, content, **kw):
        if self.fail:
            raise self.fail
        self.sent.append((content, kw))


class FakeClient:
    def __init__(self, channels):
        self.channels = channels
        self.intents = discord.Intents.default()

    def get_channel(self, cid):
        return self.channels.get(cid)


def ch(cid, name="Lounge"):
    return SimpleNamespace(id=cid, name=name)


def member(uid=1, bot=False, guild=GUILD, name="Max"):
    return SimpleNamespace(id=uid, bot=bot, display_name=name, guild=SimpleNamespace(id=guild))


def state(channel=None):
    return SimpleNamespace(channel=channel)


def setup(**cfg):
    text = FakeText()
    client = FakeClient({TEXT: text})
    conf = {"enabled": True, "watch": {VOICE: TEXT, VOICE2: TEXT}, "cooldown_seconds": 60, **cfg}
    clock = Clock()
    n = VoiceNotifier(client, conf, clock=clock)
    return n, text, clock, conf


def run(n, m, before, after):
    asyncio.run(n.on_voice_state_update(m, before, after))


# --- Abnahme ------------------------------------------------------------
def test_beitritt_genau_eine_meldung():
    n, text, _, _ = setup()
    run(n, member(), state(None), state(ch(VOICE)))
    assert len(text.sent) == 1
    content, kw = text.sent[0]
    assert content == f"🎙️ Max ist in <#{VOICE}>."
    am = kw["allowed_mentions"]
    assert am.everyone is False and am.users is False and am.roles is False


def test_raus_und_rein_im_cooldown_keine_zweite_meldung():
    n, text, clock, _ = setup(delete_on_leave=False)
    run(n, member(), state(None), state(ch(VOICE)))
    run(n, member(), state(ch(VOICE)), state(None))          # raus – wird nicht gemeldet
    clock.t += 20
    run(n, member(), state(None), state(ch(VOICE)))          # sofort wieder rein
    assert len(text.sent) == 1
    clock.t += 61
    run(n, member(), state(None), state(ch(VOICE)))          # nach dem Cooldown wieder
    assert len(text.sent) == 2


def test_bot_account_keine_meldung():
    n, text, _, _ = setup()
    run(n, member(bot=True), state(None), state(ch(VOICE)))
    assert text.sent == []


def test_nicht_ueberwachter_voice_keine_meldung():
    n, text, _, _ = setup()
    run(n, member(), state(None), state(ch(OTHER_VOICE)))
    assert text.sent == []


# --- Randfälle -----------------------------------------------------------
def test_wechsel_in_ueberwachten_raum_wird_gemeldet_mute_nicht():
    n, text, _, _ = setup()
    run(n, member(), state(ch(OTHER_VOICE)), state(ch(VOICE)))   # Wechsel
    run(n, member(uid=2), state(ch(VOICE)), state(ch(VOICE)))    # nur stumm geschaltet o. Ä.
    assert len(text.sent) == 1


def test_cooldown_gilt_pro_person_und_raum():
    n, text, _, _ = setup(delete_on_leave=False)
    run(n, member(uid=1), state(None), state(ch(VOICE)))
    run(n, member(uid=2), state(None), state(ch(VOICE)))         # andere Person
    run(n, member(uid=1), state(ch(VOICE)), state(ch(VOICE2)))   # gleicher Mensch, anderer Raum
    assert len(text.sent) == 3


def test_ausgeschaltet_und_server_deaktiviert():
    n, text, _, conf = setup(enabled=False)
    run(n, member(), state(None), state(ch(VOICE)))
    assert text.sent == []
    n2, text2, _, _ = setup(disabled_guilds=[str(GUILD)])
    run(n2, member(guild=GUILD), state(None), state(ch(VOICE)))
    run(n2, member(uid=5, guild=GUILD2), state(None), state(ch(VOICE)))
    assert len(text2.sent) == 1


def test_vorlage_und_fehlerhafte_vorlage():
    n, text, _, _ = setup(template="{name} → {channel_name}")
    run(n, member(name="Kai"), state(None), state(ch(VOICE, "Werkstatt")))
    assert text.sent[0][0] == "Kai → Werkstatt"
    n2, text2, _, _ = setup(template="{unbekannt} kaputt")
    run(n2, member(), state(None), state(ch(VOICE)))
    assert text2.sent[0][0] == f"🎙️ Max ist in <#{VOICE}>."


def test_kanal_fehlt_oder_kein_schreibrecht_stuerzt_nicht_ab(caplog):
    n = VoiceNotifier(FakeClient({}), {"enabled": True, "watch": {VOICE: TEXT}}, clock=Clock())
    run(n, member(), state(None), state(ch(VOICE)))                # Kanal fehlt
    forbidden = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions")
    n2 = VoiceNotifier(FakeClient({TEXT: FakeText(fail=forbidden)}), {"enabled": True, "watch": {VOICE: TEXT}}, clock=Clock())
    run(n2, member(), state(None), state(ch(VOICE)))
    n3 = VoiceNotifier(FakeClient({TEXT: FakeText(fail=RuntimeError("Netz weg"))}), {"enabled": True, "watch": {VOICE: TEXT}}, clock=Clock())
    run(n3, member(), state(None), state(ch(VOICE)))
    text = caplog.text
    assert "nicht gefunden" in text and "Keine Schreibrechte" in text and "Fehler beim Melden" in text


def test_watch_aus_yaml_mit_text_ids_und_config_als_funktion():
    calls = []

    def conf():
        calls.append(1)
        return {"enabled": True, "watch": {str(VOICE): str(TEXT)}}
    text = FakeText()
    n = VoiceNotifier(FakeClient({TEXT: text}), conf, clock=Clock())
    run(n, member(), state(None), state(ch(VOICE)))
    assert len(text.sent) == 1 and calls


def test_einhaengen_behaelt_vorhandenen_handler():
    seen = []
    text = FakeText()
    client = FakeClient({TEXT: text})

    async def existing(m, b, a):
        seen.append(m.id)
    client.on_voice_state_update = existing
    n = attach_voice_notifier(client, {"enabled": True, "watch": {VOICE: TEXT}})
    asyncio.run(client.on_voice_state_update(member(uid=7), state(None), state(ch(VOICE))))
    assert seen == [7] and len(text.sent) == 1 and client.voice_notifier is n


def test_bot_haengt_melder_ein_und_liest_config(tmp_path):
    import yaml

    from bot import RundenBot
    from config import Config
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump({"bot": {"owner_id": 1}, "voice_notifier": {"enabled": True, "watch": {VOICE: TEXT}}}), encoding="utf-8")
    bot = RundenBot(Config(p))
    assert bot.intents.voice_states and isinstance(bot.voice_notifier, VoiceNotifier)
    assert bot.voice_notifier.config()["watch"] == {VOICE: TEXT}
    bot.cfg.set("voice_notifier.enabled", "nein")                  # per Chat ausschaltbar
    assert bot.voice_notifier.config()["enabled"] is False



# --- Meldung als Status: beim Verlassen löschen ----------------------------
class Msg:
    def __init__(self):
        self.deleted = False

    async def delete(self):
        self.deleted = True


class StatusText(FakeText):
    async def send(self, content, **kw):
        await super().send(content, **kw)
        m = Msg()
        self.msgs = getattr(self, "msgs", []) + [m]
        return m


def status_setup(**cfg):
    text = StatusText()
    conf = {"enabled": True, "watch": {VOICE: TEXT, VOICE2: TEXT}, "leave_grace_seconds": 0, **cfg}
    return VoiceNotifier(FakeClient({TEXT: text}), conf, clock=Clock()), text


def test_meldung_wird_beim_verlassen_geloescht():
    async def flow():
        n, text = status_setup()
        await n.on_voice_state_update(member(), state(None), state(ch(VOICE)))
        assert len(text.sent) == 1 and not text.msgs[0].deleted
        await n.on_voice_state_update(member(), state(ch(VOICE)), state(None))
        await asyncio.sleep(0.01)
        assert text.msgs[0].deleted
        await n.on_voice_state_update(member(), state(None), state(ch(VOICE)))   # wieder rein → neue Meldung
        assert len(text.sent) == 2
    asyncio.run(flow())


def test_schnell_wieder_rein_behaelt_meldung():
    async def flow():
        n, text = status_setup(leave_grace_seconds=5)
        await n.on_voice_state_update(member(), state(None), state(ch(VOICE)))
        await n.on_voice_state_update(member(), state(ch(VOICE)), state(None))
        await n.on_voice_state_update(member(), state(None), state(ch(VOICE)))
        await asyncio.sleep(0.01)
        assert len(text.sent) == 1 and not text.msgs[0].deleted and not n._pending_delete
    asyncio.run(flow())


def test_wechsel_loescht_alte_und_meldet_neuen_raum():
    async def flow():
        n, text = status_setup()
        await n.on_voice_state_update(member(), state(None), state(ch(VOICE)))
        await n.on_voice_state_update(member(), state(ch(VOICE)), state(ch(VOICE2)))
        await asyncio.sleep(0.01)
        assert len(text.sent) == 2 and text.msgs[0].deleted and not text.msgs[1].deleted
    asyncio.run(flow())


def test_ohne_loeschen_bleibt_meldung():
    async def flow():
        n, text = status_setup(delete_on_leave=False)
        await n.on_voice_state_update(member(), state(None), state(ch(VOICE)))
        await n.on_voice_state_update(member(), state(ch(VOICE)), state(None))
        await asyncio.sleep(0.01)
        assert not text.msgs[0].deleted
    asyncio.run(flow())
