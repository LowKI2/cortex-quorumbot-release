"""Live-Empfang im Sprachraum (experimentell).

discord.py sendet Sprache, empfängt sie aber nicht. Dieses Modul hängt sich an die
Sprachverbindung und baut den Empfang selbst:

  UDP-Paket → RTP-Kopf lesen → Transport entschlüsseln (AEAD XChaCha20-Poly1305, „rtpsize“)
  → Ende-zu-Ende entschlüsseln (DAVE, über die davey-Sitzung von discord.py)
  → Opus dekodieren → je Sprecher puffern → nach einer Sprechpause als Äußerung ausgeben.

Datenschutz: Es wird ausschließlich der Ton der eingestellten Person (Besitzer) verarbeitet.
Pakete anderer Teilnehmer werden verworfen, bevor sie entschlüsselt werden.
"""
from __future__ import annotations

import asyncio
import logging
import struct
import threading
import time
from dataclasses import dataclass, field

import discord
from discord.voice_state import VoiceConnectionState

log = logging.getLogger("runde.voice")

OP_SPEAKING = 5
OP_CLIENT_DISCONNECT = 13
RTP_PAYLOAD_OPUS = 0x78
OPUS_SILENCE = b"\xf8\xff\xfe"
BYTES_PER_SECOND = 48000 * 2 * 2          # 48 kHz, 16 bit, Stereo


class QuorumVoiceClient(discord.VoiceClient):
    """VoiceClient, der mitliest, welche SSRC (Tonspur) zu welchem Discord-Nutzer gehört."""

    def __init__(self, client, channel):
        self.ssrc_users: dict[int, int] = {}
        super().__init__(client, channel)

    def create_connection_state(self) -> VoiceConnectionState:
        return VoiceConnectionState(self, hook=self._ws_hook)

    async def _ws_hook(self, ws, msg: dict) -> None:
        op, d = msg.get("op"), msg.get("d") or {}
        if op == OP_SPEAKING and "ssrc" in d and "user_id" in d:
            self.ssrc_users[int(d["ssrc"])] = int(d["user_id"])
        elif op == OP_CLIENT_DISCONNECT and "user_id" in d:
            uid = int(d["user_id"])
            for ssrc in [s for s, u in self.ssrc_users.items() if u == uid]:
                self.ssrc_users.pop(ssrc, None)


@dataclass
class RtpPacket:
    ssrc: int
    sequence: int
    timestamp: int
    aad: bytes            # unverschlüsselter Teil (Kopf), dient als „associated data“
    ciphertext: bytes
    nonce_suffix: bytes
    has_extension: bool
    has_padding: bool


def parse_rtp(data: bytes) -> RtpPacket | None:
    """RTP-Kopf im Discord-Format („rtpsize“) zerlegen. None = kein Audio-Paket."""
    if len(data) < 12 + 4 + 16:
        return None
    b0, b1 = data[0], data[1]
    if b0 >> 6 != 2 or (b1 & 0x7F) != RTP_PAYLOAD_OPUS:
        return None
    cc = b0 & 0x0F
    has_ext = bool(b0 & 0x10)
    has_pad = bool(b0 & 0x20)
    seq, ts, ssrc = struct.unpack_from(">HII", data, 2)
    head = 12 + 4 * cc
    if has_ext:
        head += 4          # Profil + Länge sind unverschlüsselt, der Inhalt der Erweiterung nicht
    if len(data) < head + 4:
        return None
    return RtpPacket(ssrc, seq, ts, bytes(data[:head]), bytes(data[head:-4]), bytes(data[-4:]), has_ext, has_pad)


def decrypt_transport(pkt: RtpPacket, secret_key) -> bytes:
    """Transportverschlüsselung lösen und RTP-Erweiterung/Padding entfernen → Opus (ggf. noch DAVE-verschlüsselt)."""
    import nacl.secret
    nonce = pkt.nonce_suffix + bytes(20)
    plain = nacl.secret.Aead(bytes(secret_key)).decrypt(pkt.ciphertext, pkt.aad, nonce)
    if pkt.has_extension:
        ext_words = struct.unpack_from(">H", pkt.aad, len(pkt.aad) - 2)[0]
        plain = plain[4 * ext_words:]
    if pkt.has_padding and plain:
        plain = plain[: -plain[-1]] if plain[-1] <= len(plain) else b""
    return plain


@dataclass
class _Buffer:
    user_id: int
    chunks: list = field(default_factory=list)
    size: int = 0
    started: float = 0.0
    last: float = 0.0


class Receiver:
    """Sammelt den Ton einer Person und meldet ganze Äußerungen.

    on_utterance(user_id, pcm) – async, wird im Bot-Eventloop aufgerufen.
    on_speech_start(user_id)   – async, beim ersten Ton einer neuen Äußerung (zum Unterbrechen).
    """

    def __init__(self, vc: QuorumVoiceClient, *, listen_to: int, loop: asyncio.AbstractEventLoop,
                 on_utterance, on_speech_start=None, silence_s: float = 0.9,
                 min_s: float = 0.5, max_s: float = 30.0, clock=time.monotonic):
        self.vc = vc
        self.listen_to = int(listen_to)
        self.loop = loop
        self.on_utterance = on_utterance
        self.on_speech_start = on_speech_start
        self.silence_s, self.min_s, self.max_s = silence_s, min_s, max_s
        self.clock = clock
        self._buffers: dict[int, _Buffer] = {}
        self._decoders: dict[int, discord.opus.Decoder] = {}
        self._lock = threading.Lock()
        self._task: asyncio.Task | None = None
        self._dave_errors = 0
        self.stats = {"pakete": 0, "verworfen_fremd": 0, "fehler": 0}

    # --- Lebenszyklus ---------------------------------------------------
    def start(self):
        if not discord.opus.is_loaded():
            discord.opus._load_default()
        self.vc._connection.add_socket_listener(self._on_packet)
        self._task = self.loop.create_task(self._watch())
        log.info("Live-Empfang gestartet (nur Nutzer %s)", self.listen_to)

    def stop(self):
        try:
            self.vc._connection.remove_socket_listener(self._on_packet)
        except Exception:  # noqa: BLE001
            pass
        if self._task:
            self._task.cancel()
        with self._lock:
            self._buffers.clear()
            self._decoders.clear()

    # --- Socket-Thread --------------------------------------------------
    def _on_packet(self, data: bytes) -> None:
        try:
            self._handle(data)
        except Exception as e:  # noqa: BLE001 – ein kaputtes Paket darf den Empfang nicht beenden
            self.stats["fehler"] += 1
            if self.stats["fehler"] in (1, 50, 500):
                log.warning("Sprachpaket verworfen (%s: %s)", type(e).__name__, e)

    def _handle(self, data: bytes) -> None:
        pkt = parse_rtp(data)
        if pkt is None:
            return
        conn = self.vc._connection
        if pkt.ssrc == getattr(conn, "ssrc", None):
            return
        user_id = self.vc.ssrc_users.get(pkt.ssrc)
        if user_id != self.listen_to:
            self.stats["verworfen_fremd"] += 1
            return
        opus = decrypt_transport(pkt, conn.secret_key)
        opus = self._dave(conn, user_id, opus)
        if opus is None or opus == OPUS_SILENCE:
            return
        dec = self._decoders.get(pkt.ssrc)
        if dec is None:
            dec = self._decoders[pkt.ssrc] = discord.opus.Decoder()
        pcm = dec.decode(opus, fec=False)
        self.stats["pakete"] += 1
        now = self.clock()
        new_utterance = False
        with self._lock:
            buf = self._buffers.get(pkt.ssrc)
            if buf is None:
                buf = self._buffers[pkt.ssrc] = _Buffer(user_id, started=now)
                new_utterance = True
            buf.chunks.append(pcm)
            buf.size += len(pcm)
            buf.last = now
        if new_utterance and self.on_speech_start:
            asyncio.run_coroutine_threadsafe(self.on_speech_start(user_id), self.loop)

    def _dave(self, conn, user_id: int, opus: bytes) -> bytes | None:
        sess = getattr(conn, "dave_session", None)
        if sess is None or not getattr(conn, "dave_protocol_version", 0):
            return opus
        try:
            import davey
            return bytes(sess.decrypt(user_id, davey.MediaType.audio, opus))
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "Unencrypted" in msg or "passthrough" in msg.lower():
                return opus
            self._dave_errors += 1
            if self._dave_errors in (1, 100):
                log.warning("DAVE-Entschlüsselung fehlgeschlagen (%s) – Paket verworfen", msg[:80])
            return None

    # --- Eventloop: Pausen erkennen ------------------------------------
    async def _watch(self):
        while True:
            await asyncio.sleep(0.15)
            for user_id, pcm in self.collect():
                self.loop.create_task(self.on_utterance(user_id, pcm))

    def collect(self) -> list[tuple[int, bytes]]:
        """Fertige Äußerungen herausnehmen (Pause erreicht oder zu lang)."""
        now = self.clock()
        done = []
        with self._lock:
            for ssrc, buf in list(self._buffers.items()):
                quiet = now - buf.last >= self.silence_s
                too_long = buf.size >= self.max_s * BYTES_PER_SECOND
                if quiet or too_long:
                    self._buffers.pop(ssrc)
                    if buf.size >= self.min_s * BYTES_PER_SECOND:
                        done.append((buf.user_id, b"".join(buf.chunks)))
        return done
