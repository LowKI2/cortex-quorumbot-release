"""Spracherkennung (STT) und Sprachausgabe (TTS) für Cortex QuorumBot.

Cloud-Anbieter werden per HTTP angesprochen (aiohttp kommt mit discord.py).
Alle Funktionen bekommen eine `post`-Funktion übergeben, damit sie ohne Netz testbar sind.
"""
from __future__ import annotations

import asyncio
import html
import io
import os
import re
import shutil
import tempfile
import wave
from dataclasses import dataclass

STT_DEFAULT_MODEL = {
    "groq": "whisper-large-v3-turbo",
    "openai": "gpt-4o-mini-transcribe",
    "deepgram": "nova-3",
    "lokal": "small",
}
STT_KEY_ENV = {"groq": "GROQ_API_KEY", "openai": "OPENAI_API_KEY", "deepgram": "DEEPGRAM_API_KEY"}

TTS_DEFAULT_VOICE = {
    "azure": "de-DE-KatjaNeural",
    "openai": "alloy",
    "elevenlabs": "",
    "piper": "",
}
TTS_KEY_ENV = {"azure": "AZURE_SPEECH_KEY", "openai": "OPENAI_API_KEY", "elevenlabs": "ELEVENLABS_API_KEY"}


class SpeechError(RuntimeError):
    pass


@dataclass
class Audio:
    data: bytes
    suffix: str      # ".wav" oder ".mp3"


# --- Hilfen -------------------------------------------------------------
def pcm_to_wav(pcm: bytes, rate: int = 48000, channels: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def clean_for_speech(text: str, max_chars: int = 900) -> str:
    """Markdown, Erwähnungen, Links, Code und Fußzeilen entfernen – was übrig bleibt, wird gesprochen."""
    t = re.sub(r"```.*?```", " Codeblock. ", text, flags=re.S)
    t = re.sub(r"^-# .*$", "", t, flags=re.M)             # Discord-Kleindruck (Runde x/y)
    t = re.sub(r"<@!?\d+>", "", t)                          # Erwähnungen
    t = re.sub(r"<#\d+>|<a?:\w+:\d+>", "", t)              # Kanäle, Emojis
    t = re.sub(r"https?://\S+", "Link", t)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"[*_~>|#]+", "", t)
    t = re.sub(r"^\s*[-•]\s+", "", t, flags=re.M)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > max_chars:
        cut = t[:max_chars]
        t = cut[: cut.rfind(". ") + 1] if ". " in cut else cut
    return t


def find_wake_word(text: str, words: list[str]) -> tuple[bool, str]:
    """Erkennt den Rufnamen am Anfang oder irgendwo im Satz. Gibt (gefunden, Text ohne Rufname am Anfang)."""
    low = text.lower()
    for w in sorted({w.strip().lower() for w in words if w and w.strip()}, key=len, reverse=True):
        m = re.match(rf"^\W*(hey|hallo|hi|ok|okay)?\W*{re.escape(w)}\b[\s,.:!?-]*", low)
        if m:
            return True, text[m.end():].strip() or text
        if re.search(rf"\b{re.escape(w)}\b", low):
            return True, text
    return False, text


# --- Spracherkennung ----------------------------------------------------
async def transcribe(cfg, wav: bytes, env: dict, post=None, filename: str = "audio.wav", mime: str = "audio/wav") -> str:
    """wav: Audiodaten (WAV, OGG/Opus oder MP3 – Dateiname/MIME passend angeben)."""
    provider = cfg.get("stt.provider", "groq")
    model = cfg.get("stt.model") or STT_DEFAULT_MODEL.get(provider, "")
    lang = cfg.get("stt.language", "de") or "de"
    post = post or _post

    if provider in ("groq", "openai"):
        key = env.get(STT_KEY_ENV[provider], "")
        if not key:
            raise SpeechError(f"{STT_KEY_ENV[provider]} fehlt")
        url = ("https://api.groq.com/openai/v1/audio/transcriptions" if provider == "groq"
               else "https://api.openai.com/v1/audio/transcriptions")
        fields = {"model": model, "language": lang, "response_format": "json"}
        status, data = await post(url, {"Authorization": f"Bearer {key}"},
                                  form=fields, file=(filename, wav, mime))
        if status != 200:
            raise SpeechError(f"Spracherkennung {provider}: {status} {str(data)[:200]}")
        return (data or {}).get("text", "").strip()

    if provider == "deepgram":
        key = env.get(STT_KEY_ENV["deepgram"], "")
        if not key:
            raise SpeechError("DEEPGRAM_API_KEY fehlt")
        url = f"https://api.deepgram.com/v1/listen?model={model}&language={lang}&smart_format=true"
        status, data = await post(url, {"Authorization": f"Token {key}", "Content-Type": mime}, body=wav)
        if status != 200:
            raise SpeechError(f"Spracherkennung deepgram: {status} {str(data)[:200]}")
        try:
            return data["results"]["channels"][0]["alternatives"][0]["transcript"].strip()
        except (KeyError, IndexError, TypeError):
            return ""

    if provider == "lokal":
        return await asyncio.to_thread(_transcribe_local, wav, model, lang, os.path.splitext(filename)[1] or ".wav")

    raise SpeechError(f"Unbekannter STT-Anbieter: {provider}")


_LOCAL_MODEL = {}


def _transcribe_local(wav: bytes, model: str, lang: str, suffix: str = ".wav") -> str:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise SpeechError("faster-whisper nicht installiert (pip install faster-whisper)") from e
    if model not in _LOCAL_MODEL:
        _LOCAL_MODEL[model] = WhisperModel(model, device="auto", compute_type="int8")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(wav)
        path = f.name
    try:
        segs, _ = _LOCAL_MODEL[model].transcribe(path, language=lang, vad_filter=True)
        return " ".join(s.text.strip() for s in segs).strip()
    finally:
        os.unlink(path)


# --- Sprachausgabe ------------------------------------------------------
async def synthesize(cfg, text: str, env: dict, post=None) -> Audio:
    provider = cfg.get("tts.provider", "azure")
    voice = cfg.get("tts.voice") or TTS_DEFAULT_VOICE.get(provider, "")
    speed = float(cfg.get("tts.speed", 1.0) or 1.0)
    post = post or _post
    if not text.strip():
        raise SpeechError("Kein Text zum Sprechen")

    if provider == "azure":
        key = env.get(TTS_KEY_ENV["azure"], "")
        region = cfg.get("tts.azure_region") or "germanywestcentral"
        if not key:
            raise SpeechError("AZURE_SPEECH_KEY fehlt")
        lang = "-".join(voice.split("-")[:2]) if voice.count("-") >= 2 else "de-DE"
        rate = f"{round((speed - 1) * 100):+d}%"
        ssml = (f"<speak version='1.0' xml:lang='{lang}'><voice name='{html.escape(voice)}'>"
                f"<prosody rate='{rate}'>{html.escape(text)}</prosody></voice></speak>")
        status, data = await post(
            f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
            {"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/ssml+xml",
             "X-Microsoft-OutputFormat": "riff-48khz-16bit-mono-pcm", "User-Agent": "cortex-quorumbot"},
            body=ssml.encode("utf-8"), raw=True)
        if status != 200:
            raise SpeechError(f"Azure-Stimme: {status} {str(data)[:200]}")
        return Audio(data, ".wav")

    if provider == "openai":
        key = env.get(TTS_KEY_ENV["openai"], "")
        if not key:
            raise SpeechError("OPENAI_API_KEY fehlt")
        status, data = await post(
            "https://api.openai.com/v1/audio/speech",
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json_body={"model": cfg.get("tts.model") or "gpt-4o-mini-tts", "voice": voice,
                       "input": text, "response_format": "wav", "speed": speed}, raw=True)
        if status != 200:
            raise SpeechError(f"OpenAI-Stimme: {status} {str(data)[:200]}")
        return Audio(data, ".wav")

    if provider == "elevenlabs":
        key = env.get(TTS_KEY_ENV["elevenlabs"], "")
        if not key:
            raise SpeechError("ELEVENLABS_API_KEY fehlt")
        if not voice:
            raise SpeechError("Für ElevenLabs eine Voice-ID unter „Stimme“ eintragen")
        status, data = await post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
            {"xi-api-key": key, "Content-Type": "application/json"},
            json_body={"text": text, "model_id": cfg.get("tts.model") or "eleven_flash_v2_5",
                       "voice_settings": {"speed": speed}}, raw=True)
        if status != 200:
            raise SpeechError(f"ElevenLabs: {status} {str(data)[:200]}")
        return Audio(data, ".mp3")

    if provider == "piper":
        return await asyncio.to_thread(_synthesize_piper, cfg, text, voice, speed)

    raise SpeechError(f"Unbekannter TTS-Anbieter: {provider}")


def _synthesize_piper(cfg, text: str, model: str, speed: float) -> Audio:
    import subprocess
    exe = shutil.which(cfg.get("tts.piper_path") or "piper") or (cfg.get("tts.piper_path") or "piper")
    if not model:
        raise SpeechError("Für Piper unter „Stimme“ den Pfad zur .onnx-Stimme eintragen")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        out = f.name
    try:
        r = subprocess.run([exe, "--model", model, "--output_file", out, "--length_scale", f"{1 / max(speed, .3):.2f}"],
                           input=text.encode("utf-8"), capture_output=True, timeout=60)
        if r.returncode != 0:
            raise SpeechError(f"Piper: {r.stderr.decode('utf-8', 'replace')[:200]}")
        with open(out, "rb") as fh:
            return Audio(fh.read(), ".wav")
    except FileNotFoundError as e:
        raise SpeechError("Piper nicht gefunden – Pfad unter Erweitert eintragen") from e
    finally:
        try:
            os.unlink(out)
        except OSError:
            pass


# --- HTTP ---------------------------------------------------------------
async def _post(url, headers, *, form=None, file=None, body=None, json_body=None, raw=False, timeout=60):
    import aiohttp
    data = None
    if form is not None or file is not None:
        data = aiohttp.FormData()
        for k, v in (form or {}).items():
            data.add_field(k, str(v))
        if file:
            data.add_field("file", file[1], filename=file[0], content_type=file[2])
    elif body is not None:
        data = body
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
        async with s.post(url, headers=headers, data=data, json=json_body) as r:
            if raw and r.status == 200:
                return r.status, await r.read()
            txt = await r.text(errors="replace")
            try:
                import json
                return r.status, json.loads(txt)
            except ValueError:
                return r.status, txt


def secret_vars(get) -> list[str]:
    """Welche Schlüssel die aktuelle Sprach-Konfiguration braucht."""
    if not get("voice.enabled"):
        return []
    out = []
    stt = get("stt.provider") or "groq"
    tts = get("tts.provider") or "azure"
    if stt in STT_KEY_ENV:
        out.append(STT_KEY_ENV[stt])
    if tts in TTS_KEY_ENV and TTS_KEY_ENV[tts] not in out:
        out.append(TTS_KEY_ENV[tts])
    return out
