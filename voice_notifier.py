"""Voice-Join-Melder – eigenständiges Modul für discord.py-Bots.

Postet eine kurze Meldung in einen festgelegten Textkanal, wenn jemand einen
überwachten Sprachraum betritt (oder hineinwechselt). Verlassen wird nicht gemeldet.
Keine KI, keine Abhängigkeit vom restlichen Bot-Code – nur discord.py und die Standardbibliothek.

Einbinden:
    from voice_notifier import attach_voice_notifier
    attach_voice_notifier(client, config)        # config: dict oder Funktion, die ein dict liefert

Config (alle Felder optional außer watch):
    enabled: true                 # Melder an/aus
    watch: {VOICE_ID: TEXT_ID}    # beliebig viele Paare, auch aus mehreren Servern
    disabled_guilds: [GUILD_ID]   # Server, in denen nicht gemeldet wird
    cooldown_seconds: 60          # Mindestabstand pro Nutzer + Sprachraum
    template: "🎙️ {name} ist in <#{channel}>."

Wichtig: Pro Server darf der Melder nur in EINEM Bot aktiv sein, sonst kommt jede Meldung doppelt.
Der Bot braucht im Ziel-Textkanal die Rechte „Kanal ansehen“ und „Nachrichten senden“.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Union

import discord

log = logging.getLogger("voice_notifier")

DEFAULT_TEMPLATE = "🎙️ {name} ist in <#{channel}>."
DEFAULT_COOLDOWN = 60.0

ConfigSource = Union[dict, Callable[[], dict]]


class VoiceNotifier:
    def __init__(self, client: discord.Client, config: ConfigSource, clock: Callable[[], float] = time.monotonic):
        self.client = client
        self._config = config
        self.clock = clock
        self._last: dict[tuple[int, int], float] = {}

    # --- Config --------------------------------------------------------
    def config(self) -> dict:
        cfg = self._config() if callable(self._config) else self._config
        return cfg or {}

    @staticmethod
    def _ids(values) -> set[int]:
        out = set()
        for v in values or []:
            try:
                out.add(int(v))
            except (TypeError, ValueError):
                pass
        return out

    def watch(self, cfg: dict) -> dict[int, int]:
        out = {}
        for voice_id, text_id in (cfg.get("watch") or {}).items():
            try:
                out[int(voice_id)] = int(text_id)
            except (TypeError, ValueError):
                log.warning("Ungültiges Paar in watch: %r → %r", voice_id, text_id)
        return out

    # --- Event ---------------------------------------------------------
    def should_notify(self, member, before, after) -> int | None:
        """Gibt die Text-Channel-ID zurück, wenn gemeldet werden soll – sonst None."""
        cfg = self.config()
        if not cfg.get("enabled", False):
            return None
        new = getattr(after, "channel", None)
        old = getattr(before, "channel", None)
        if new is None or (old is not None and old.id == new.id):
            return None                                   # Verlassen oder nur Stummschalten o. Ä.
        if getattr(member, "bot", False):
            return None
        guild = getattr(member, "guild", None)
        if guild is not None and guild.id in self._ids(cfg.get("disabled_guilds")):
            return None
        text_id = self.watch(cfg).get(new.id)
        if not text_id:
            return None
        cooldown = float(cfg.get("cooldown_seconds", DEFAULT_COOLDOWN) or 0)
        key = (member.id, new.id)
        now = self.clock()
        if key in self._last and now - self._last[key] < cooldown:
            return None
        self._last[key] = now
        if len(self._last) > 5000:                        # alte Einträge nicht ewig sammeln
            self._last = {k: t for k, t in self._last.items() if now - t < cooldown}
        return text_id

    def render(self, member, channel) -> str:
        template = self.config().get("template") or DEFAULT_TEMPLATE
        name = getattr(member, "display_name", None) or getattr(member, "name", "Jemand")
        try:
            return template.format(name=name, channel=channel.id, channel_name=channel.name)
        except (KeyError, IndexError, ValueError):
            log.warning("Vorlage fehlerhaft, nutze Standard: %r", template)
            return DEFAULT_TEMPLATE.format(name=name, channel=channel.id)

    async def on_voice_state_update(self, member, before, after) -> None:
        text_id = None
        try:
            text_id = self.should_notify(member, before, after)
            if not text_id:
                return
            channel = self.client.get_channel(text_id)
            if channel is None:
                log.warning("Text-Channel %s nicht gefunden – Melder überspringt.", text_id)
                return
            await channel.send(self.render(member, after.channel)[:2000],
                               allowed_mentions=discord.AllowedMentions.none())
        except discord.Forbidden:
            log.warning("Keine Schreibrechte im Text-Channel %s – Melder überspringt.", text_id)
        except Exception:  # noqa: BLE001 – der Melder darf den Bot nie zum Absturz bringen
            log.exception("Voice-Join-Melder: Fehler beim Melden")


def attach_voice_notifier(client: discord.Client, config: ConfigSource, **kwargs) -> VoiceNotifier:
    """Melder an einen vorhandenen Client hängen. Ein schon vorhandener on_voice_state_update bleibt erhalten."""
    if not client.intents.voice_states:
        log.warning("Intent voice_states ist aus – der Voice-Join-Melder bekommt keine Ereignisse.")
    notifier = VoiceNotifier(client, config, **kwargs)
    previous = getattr(client, "on_voice_state_update", None)

    async def on_voice_state_update(member, before, after):
        await notifier.on_voice_state_update(member, before, after)
        if previous is not None:
            await previous(member, before, after)

    client.on_voice_state_update = on_voice_state_update   # discord.py ruft on_<event> per getattr auf
    client.voice_notifier = notifier
    return notifier
