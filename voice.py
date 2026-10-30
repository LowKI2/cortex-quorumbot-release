"""Sprache für Cortex QuorumBot: Sprachraum betreten, sprechen, zuhören, Sprachnachrichten.

Der Bot sitzt wirklich im Sprachraum und spricht dort live. Gesprochenes von dir wird
als Text in den Textkanal geschrieben (damit der andere Bot mitbekommt, worum es geht)
und läuft dann durch dieselben Leitplanken wie eine Textnachricht.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile

import discord

import speech

log = logging.getLogger("runde.voice")

TRANSCRIPT_PREFIX = "🎙️ **"
TRANSCRIPT_RE = re.compile(r"^🎙️ \*\*(.+?):\*\* (.*)$", re.S)


def transcript_line(name: str, text: str) -> str:
    return f"{TRANSCRIPT_PREFIX}{name}:** {text}"


def parse_transcript(content: str):
    """(Name, Text) aus einer Transkript-Nachricht – sonst None."""
    m = TRANSCRIPT_RE.match(content or "")
    return (m.group(1), m.group(2)) if m else None


class VoiceManager:
    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.cfg
        self.vc = None
        self.receiver = None
        self._speak_lock = asyncio.Lock()
        self._playing = asyncio.Event()

    # --- Einstellungen -------------------------------------------------
    def g(self, key, default=None):
        return self.cfg.get(key, default)

    @property
    def enabled(self) -> bool:
        return bool(self.g("voice.enabled", False))

    def env(self) -> dict:
        return dict(os.environ)

    def owner_id(self) -> int:
        return int(self.g("bot.owner_id", 0) or 0)

    def wake_words(self) -> list[str]:
        words = list(self.g("voice.wake_words") or [])
        name = self.g("bot.name")
        if name and name not in words:
            words.append(name)
        return words

    def channel_allowed(self, channel) -> bool:
        allowed = [int(x) for x in (self.g("voice.channel_ids") or [])]
        return not allowed or channel.id in allowed

    def text_channel(self):
        cid = self.g("voice.text_channel_id") or (self.g("discord.allowed_channel_ids") or [None])[0]
        return self.bot.get_channel(int(cid)) if cid else None

    @property
    def connected(self) -> bool:
        return bool(self.vc and self.vc.is_connected())

    # --- Sprachraum ----------------------------------------------------
    async def join(self, channel) -> str:
        if not self.enabled:
            return "Sprache ist ausgeschaltet (Konfigurator → Sprache)."
        if not self.channel_allowed(channel):
            return "Dieser Sprachraum ist nicht freigegeben."
        from voice_receive import QuorumVoiceClient, Receiver
        live = bool(self.g("voice.live_input", True))
        if self.connected:
            if self.vc.channel.id == channel.id:
                return "Bin schon da."
            await self.vc.move_to(channel)
        else:
            self.vc = await channel.connect(cls=QuorumVoiceClient, self_deaf=not live)
        if live and self.receiver is None:
            self.receiver = Receiver(
                self.vc, listen_to=self.owner_id(), loop=self.bot.loop,
                on_utterance=self.on_utterance, on_speech_start=self.on_speech_start,
                silence_s=int(self.g("voice.silence_ms", 900)) / 1000,
                max_s=float(self.g("voice.max_utterance_s", 30)))
            self.receiver.start()
        log.info("Sprachraum betreten: %s", channel.name)
        return f"Bin in 🔊 {channel.name}." + ("" if live else " (Nur Sprechen, Zuhören ist aus.)")

    async def leave(self) -> str:
        if self.receiver:
            self.receiver.stop()
            self.receiver = None
        if self.connected:
            await self.vc.disconnect(force=False)
        self.vc = None
        return "Sprachraum verlassen."

    async def on_voice_state_update(self, member, before, after):
        if not self.enabled or member.id != self.owner_id() or not self.g("voice.follow_owner", True):
            return
        if after.channel and (before.channel is None or before.channel.id != after.channel.id):
            if self.channel_allowed(after.channel):
                try:
                    await self.join(after.channel)
                except Exception:  # noqa: BLE001
                    log.exception("Beitreten fehlgeschlagen")
        elif before.channel and after.channel is None and self.connected:
            await self.leave()

    # --- Sprechen ------------------------------------------------------
    async def speak(self, text: str) -> bool:
        """Text im Sprachraum sprechen. Wartet, bis zu Ende gesprochen (oder unterbrochen) wurde."""
        if not (self.enabled and self.connected and self.g("voice.output", True)):
            return False
        clean = speech.clean_for_speech(text, int(self.g("voice.max_spoken_chars", 900)))
        if not clean:
            return False
        try:
            audio = await speech.synthesize(self.cfg, clean, self.env())
        except Exception as e:  # noqa: BLE001
            log.warning("Sprachausgabe fehlgeschlagen: %s", e)
            return False
        async with self._speak_lock:
            if not self.connected:
                return False
            with tempfile.NamedTemporaryFile(suffix=audio.suffix, delete=False) as f:
                f.write(audio.data)
                path = f.name
            done = asyncio.Event()
            try:
                src = discord.FFmpegPCMAudio(path)
                self._playing.set()
                self.vc.play(src, after=lambda err: self.bot.loop.call_soon_threadsafe(done.set))
                await asyncio.wait_for(done.wait(), timeout=180)
            except Exception as e:  # noqa: BLE001
                log.warning("Abspielen fehlgeschlagen: %s", e)
            finally:
                self._playing.clear()
                try:
                    os.unlink(path)
                except OSError:
                    pass
        return True

    def stop_speaking(self):
        if self.connected and self.vc.is_playing():
            self.vc.stop()

    async def on_speech_start(self, user_id: int):
        if self.g("voice.barge_in", True) and self._playing.is_set():
            self.stop_speaking()

    # --- Zuhören -------------------------------------------------------
    async def on_utterance(self, user_id: int, pcm: bytes):
        if user_id != self.owner_id():
            return
        try:
            text = await speech.transcribe(self.cfg, speech.pcm_to_wav(pcm), self.env())
        except Exception as e:  # noqa: BLE001
            log.warning("Spracherkennung fehlgeschlagen: %s", e)
            return
        if text:
            await self.handle_spoken(text, source="live")

    async def handle_voice_message(self, message: discord.Message) -> bool:
        """Discord-Sprachnachricht (Mikrofon-Knopf im Chat). True = behandelt."""
        if not (self.enabled and self.g("voice.voice_messages", True)):
            return False
        if not message.flags.voice or not message.attachments or message.author.id != self.owner_id():
            return False
        att = message.attachments[0]
        try:
            data = await att.read()
            text = await speech.transcribe(self.cfg, data, self.env(), filename=att.filename or "voice.ogg",
                                           mime=att.content_type or "audio/ogg")
        except Exception as e:  # noqa: BLE001
            await message.channel.send(f"-# Sprachnachricht nicht verstanden ({type(e).__name__})")
            return True
        if text:
            await self.handle_spoken(text, source="nachricht", channel=message.channel)
        return True

    async def handle_spoken(self, text: str, *, source: str, channel=None):
        channel = channel or self.text_channel()
        if channel is None:
            log.warning("Kein Textkanal für Sprache eingestellt (voice.text_channel_id)")
            return
        if source == "nachricht":
            addressed = True                      # Sprachnachrichten sind immer an den Bot gerichtet
        else:
            found, _ = speech.find_wake_word(text, self.wake_words())
            addressed = found or not self.g("voice.require_wake_word", True)
        name = self.g("bot.owner_name") or "Besitzer"
        if self.g("voice.post_transcripts", True):
            await channel.send(transcript_line(name, text)[:1990],
                               allowed_mentions=discord.AllowedMentions.none())
        await self.bot.handle_owner_text(channel, text, addressed=addressed)
