import asyncio
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import discord  # noqa: E402
import nacl.secret  # noqa: E402
import pytest  # noqa: E402

import speech  # noqa: E402
from config import Config  # noqa: E402
from voice import parse_transcript, transcript_line  # noqa: E402
from voice_receive import BYTES_PER_SECOND, Receiver, decrypt_transport, parse_rtp  # noqa: E402

OWNER, OTHER = 123456789012345678, 223456789012345678
KEY = bytes(range(32))


def cfg(**over):
    data = {"bot": {"name": "Nova", "owner_id": OWNER, "owner_name": "Max"},
            "voice": {"enabled": True}, "stt": {"provider": "groq"}, "tts": {"provider": "azure"}}
    for k, v in over.items():
        sec, key = k.split("__")
        data.setdefault(sec, {})[key] = v
    return Config("x.yaml", data=data)


# --- Text ---------------------------------------------------------------
def test_text_fuer_sprache_bereinigen():
    t = speech.clean_for_speech("**Klar!** Siehe https://x.de und `code`\n- Punkt eins\n-# Runde 2/6\n<@123> ok")
    assert t == "Klar! Siehe Link und code Punkt eins ok"
    assert len(speech.clean_for_speech("Satz. " * 400, 100)) <= 100


@pytest.mark.parametrize("text,found,rest", [
    ("Nova, was meinst du?", True, "was meinst du?"),
    ("Hey Nova wie spät ist es", True, "wie spät ist es"),
    ("Was meint Nova dazu?", True, "Was meint Nova dazu?"),
    ("Was meinst du dazu?", False, "Was meinst du dazu?"),
    ("Novalis war ein Dichter", False, "Novalis war ein Dichter"),
])
def test_rufname(text, found, rest):
    assert speech.find_wake_word(text, ["Nova"]) == (found, rest)


def test_transkript_format():
    line = transcript_line("Max", "Nova, hallo\nzweite Zeile")
    assert parse_transcript(line) == ("Max", "Nova, hallo\nzweite Zeile")
    assert parse_transcript("normale Nachricht") is None


# --- Anbieter -----------------------------------------------------------
def fake_post(status=200, data=None):
    calls = []

    async def post(url, headers, **kw):
        calls.append((url, headers, kw))
        return status, data
    return post, calls


def test_groq_erkennung():
    post, calls = fake_post(data={"text": " Hallo Nova "})
    text = asyncio.run(speech.transcribe(cfg(), b"RIFF", {"GROQ_API_KEY": "k"}, post=post))
    assert text == "Hallo Nova"
    url, headers, kw = calls[0]
    assert "api.groq.com" in url and headers["Authorization"] == "Bearer k"
    assert kw["form"]["model"] == "whisper-large-v3-turbo" and kw["form"]["language"] == "de"


def test_deepgram_erkennung_und_fehlender_key():
    post, calls = fake_post(data={"results": {"channels": [{"alternatives": [{"transcript": "hallo"}]}]}})
    c = cfg(stt__provider="deepgram")
    assert asyncio.run(speech.transcribe(c, b"x", {"DEEPGRAM_API_KEY": "k"}, post=post, mime="audio/ogg")) == "hallo"
    assert calls[0][1]["Content-Type"] == "audio/ogg" and "model=nova-3" in calls[0][0]
    with pytest.raises(speech.SpeechError, match="DEEPGRAM_API_KEY"):
        asyncio.run(speech.transcribe(c, b"x", {}, post=post))


def test_azure_stimme():
    post, calls = fake_post(data=b"RIFFwav")
    a = asyncio.run(speech.synthesize(cfg(tts__speed=1.2), "Hallo <Welt> & Co", {"AZURE_SPEECH_KEY": "k"}, post=post))
    assert a.suffix == ".wav" and a.data == b"RIFFwav"
    url, headers, kw = calls[0]
    assert url.startswith("https://germanywestcentral.tts.speech.microsoft.com")
    ssml = kw["body"].decode()
    assert "de-DE-KatjaNeural" in ssml and "+20%" in ssml and "&lt;Welt&gt; &amp; Co" in ssml


def test_elevenlabs_braucht_voice_id():
    post, _ = fake_post(data=b"mp3")
    with pytest.raises(speech.SpeechError, match="Voice-ID"):
        asyncio.run(speech.synthesize(cfg(tts__provider="elevenlabs"), "hi", {"ELEVENLABS_API_KEY": "k"}, post=post))
    a = asyncio.run(speech.synthesize(cfg(tts__provider="elevenlabs", tts__voice="abc"), "hi", {"ELEVENLABS_API_KEY": "k"}, post=post))
    assert a.suffix == ".mp3"


def test_fehler_vom_anbieter():
    post, _ = fake_post(status=401, data={"error": "invalid key"})
    with pytest.raises(speech.SpeechError, match="401"):
        asyncio.run(speech.transcribe(cfg(), b"x", {"GROQ_API_KEY": "k"}, post=post))


def test_geheimnisse_je_nach_anbieter():
    c = cfg()
    assert speech.secret_vars(c.get) == ["GROQ_API_KEY", "AZURE_SPEECH_KEY"]
    assert speech.secret_vars(cfg(voice__enabled=False).get) == []
    assert speech.secret_vars(cfg(stt__provider="openai", tts__provider="openai").get) == ["OPENAI_API_KEY"]
    assert speech.secret_vars(cfg(stt__provider="lokal", tts__provider="piper").get) == []


# --- Empfang ------------------------------------------------------------
def make_packet(opus: bytes, ssrc: int, seq: int, nonce: int, ext: bytes = b"", pad: int = 0) -> bytes:
    """Paket so bauen, wie Discord es schickt (aead_xchacha20_poly1305_rtpsize)."""
    b0 = 0x80 | (0x10 if ext else 0) | (0x20 if pad else 0)
    header = bytes([b0, 0x78]) + struct.pack(">HII", seq, seq * 960, ssrc)
    body = opus
    if ext:
        header += b"\xbe\xde" + struct.pack(">H", len(ext) // 4)
        body = ext + body
    if pad:
        body += bytes(pad - 1) + bytes([pad])
    n = struct.pack(">I", nonce)
    ct = nacl.secret.Aead(KEY).encrypt(body, header, n + bytes(20)).ciphertext
    return header + ct + n


def test_rtp_entschluesseln_mit_erweiterung_und_padding():
    pkt = parse_rtp(make_packet(b"OPUSDATA", 42, 7, 3, ext=b"\x10\xff\x00\x00", pad=3))
    assert pkt.ssrc == 42 and pkt.sequence == 7
    assert decrypt_transport(pkt, list(KEY)) == b"OPUSDATA"
    assert parse_rtp(b"\x00" * 40) is None


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


def fake_vc(dave=None):
    listeners = []
    conn = SimpleNamespace(secret_key=list(KEY), ssrc=1, dave_session=dave, dave_protocol_version=1 if dave else 0,
                           add_socket_listener=listeners.append, remove_socket_listener=listeners.remove)
    return SimpleNamespace(_connection=conn, ssrc_users={10: OWNER, 20: OTHER}), listeners


def opus_frames(n):
    discord.opus._load_default()
    enc = discord.opus.Encoder()
    pcm = (struct.pack("<h", 3000) * 2) * 960   # 20 ms Ton, Stereo
    return [enc.encode(pcm, 960) for _ in range(n)]


def make_receiver(dave=None):
    vc, listeners = fake_vc(dave)
    clock = Clock()
    loop = asyncio.new_event_loop()
    started = []

    async def on_start(uid):
        started.append(uid)
    r = Receiver(vc, listen_to=OWNER, loop=loop, on_utterance=None, on_speech_start=on_start, clock=clock)
    r.vc._connection.add_socket_listener(r._on_packet)
    return r, listeners, clock, loop, started


def test_empfang_nur_besitzer_und_pause():
    r, listeners, clock, loop, started = make_receiver()
    frames = opus_frames(40)                          # 0,8 s
    for i, f in enumerate(frames):
        listeners[0](make_packet(f, 10, i, i))       # Besitzer
        listeners[0](make_packet(f, 20, i, i))       # andere Person → verworfen
    assert r.stats["verworfen_fremd"] == 40 and r.stats["pakete"] == 40
    assert r.collect() == []                          # noch keine Pause
    clock.t += 1.0
    out = r.collect()
    assert len(out) == 1 and out[0][0] == OWNER
    assert abs(len(out[0][1]) / BYTES_PER_SECOND - 0.8) < 0.05
    loop.run_until_complete(asyncio.sleep(0))
    assert started == [OWNER]
    loop.close()


def test_zu_kurz_wird_verworfen():
    r, listeners, clock, loop, _ = make_receiver()
    for i, f in enumerate(opus_frames(10)):           # 0,2 s – Räuspern
        listeners[0](make_packet(f, 10, i, i))
    clock.t += 1.0
    assert r.collect() == []
    loop.close()


def test_dave_entschluesselung_und_durchreichen():
    frames = opus_frames(30)

    class Dave:
        def decrypt(self, uid, media, data):
            assert uid == OWNER
            return data[1:]                           # „entschlüsselt“ = erstes Byte weg

    r, listeners, clock, loop, _ = make_receiver(Dave())
    for i, f in enumerate(frames):
        listeners[0](make_packet(b"\x00" + f, 10, i, i))
    assert r.stats["pakete"] == 30 and r.stats["fehler"] == 0

    class Unencrypted:
        def decrypt(self, *a):
            raise ValueError("Failed to decrypt: UnencryptedWhenPassthroughDisabled")
    r2, l2, _, loop2, _ = make_receiver(Unencrypted())
    l2[0](make_packet(frames[0], 10, 1, 1))
    assert r2.stats["pakete"] == 1

    class Broken:
        def decrypt(self, *a):
            raise ValueError("Failed to decrypt: DecryptionFailed")
    r3, l3, _, loop3, _ = make_receiver(Broken())
    l3[0](make_packet(frames[0], 10, 1, 1))
    assert r3.stats["pakete"] == 0
    for lp in (loop, loop2, loop3):
        lp.close()


# --- Bot ----------------------------------------------------------------
class FakeChannel:
    def __init__(self, cid=555):
        self.id = cid
        self.sent = []
        self.history_msgs = []

    async def send(self, content, **kw):
        self.sent.append(content)

    def typing(self):
        class T:
            async def __aenter__(s):
                return s

            async def __aexit__(s, *a):
                return False
        return T()

    async def history(self, **kw):
        for m in reversed(self.history_msgs):
            yield m


def make_bot(tmp_path, **voice):
    import yaml

    from bot import RundenBot
    data = {"bot": {"name": "Nova", "owner_id": OWNER, "owner_name": "Max", "partner_bot_ids": [OTHER]},
            "discord": {"allowed_channel_ids": [555]}, "voice": {"enabled": True, **voice},
            "llm": {"provider": "anthropic"}}
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    bot = RundenBot(Config(p))
    bot._connection.user = SimpleNamespace(id=999, mentioned_in=lambda m: False)
    seen = {}

    async def complete(system, msgs):
        seen["msgs"] = msgs
        return "Antwort von Nova", 1, 1
    bot.llm.complete = complete
    return bot, seen


def test_gesprochenes_mit_rufname_wird_beantwortet(tmp_path):
    bot, seen = make_bot(tmp_path)
    ch = FakeChannel()
    ch.history_msgs = [SimpleNamespace(author=SimpleNamespace(id=999, display_name="Nova"),
                                       content=transcript_line("Max", "Nova, wie geht's?"))]
    asyncio.run(bot.handle_owner_text(ch, "Nova, wie geht's?", addressed=True))
    assert ch.sent == ["Antwort von Nova"]
    # Transkript zählt im Verlauf als Mensch, nicht als eigene Bot-Nachricht
    assert seen["msgs"][0] == {"role": "user", "content": "Max: Nova, wie geht's?"}


def test_gesprochenes_ohne_rufname_nur_mithoeren(tmp_path):
    bot, _ = make_bot(tmp_path)
    ch = FakeChannel()
    asyncio.run(bot.handle_owner_text(ch, "wir sollten das nochmal anschauen", addressed=False))
    assert ch.sent == []


def test_stopp_per_sprache(tmp_path):
    bot, _ = make_bot(tmp_path)
    ch = FakeChannel()
    asyncio.run(bot.handle_owner_text(ch, "stopp", addressed=False))
    assert bot.guard.state(555).halted and ch.sent == []


def test_wann_gesprochen_wird(tmp_path):
    from guardrails import Decision
    bot, _ = make_bot(tmp_path, dialog_output="nur_fazit")
    bot.voice.vc = SimpleNamespace(is_connected=lambda: True)
    owner = Decision(True, "x", "owner", 1, 1, True)
    turn = Decision(True, "x", "dialog", 2, 6, False)
    assert bot._should_speak(owner, False)
    assert not bot._should_speak(turn, True)          # Zwischenrunde: still
    assert bot._should_speak(turn, False)             # Fazit: sprechen
    bot.cfg.base["voice"]["dialog_output"] = "alles"
    assert bot._should_speak(turn, True)
    bot.cfg.base["voice"]["output"] = False
    assert not bot._should_speak(owner, False)
    bot.voice.vc = None
    bot.cfg.base["voice"]["output"] = True
    assert not bot._should_speak(owner, False)        # nicht im Sprachraum


def test_nur_sprechen_ohne_text_und_im_verlauf_gemerkt(tmp_path):
    from guardrails import Decision
    bot, seen = make_bot(tmp_path)
    bot.voice.vc = SimpleNamespace(is_connected=lambda: True)
    spoken = []

    async def speak(t):
        spoken.append(t)
    bot.voice.speak = speak
    ch = FakeChannel()
    asyncio.run(bot.respond(ch, Decision(True, "x", "owner", 1, 1, True)))
    assert ch.sent == [] and spoken == ["Antwort von Nova"]
    assert bot.spoken_log[ch.id] and bot.spoken_log[ch.id][-1][1] == "Antwort von Nova"
    hist, _ = asyncio.run(bot.fetch_history(ch, 0))
    assert hist[-1].content == "Antwort von Nova" and hist[-1].author_id == bot.user.id
    # Dialoge laufen weiter als Text (Partner-Bot braucht ihn)
    asyncio.run(bot.respond(ch, Decision(True, "x", "dialog", 2, 6, False)))
    assert ch.sent and "Runde 2/6" in ch.sent[-1]
