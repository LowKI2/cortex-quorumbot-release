"""Leitplanken der Claude-Runde.

Reine Logik ohne Discord-Abhängigkeit, damit alles testbar ist.
Jede Instanz gehört genau einem Bot (eine Person, ein Bot).
"""
from __future__ import annotations

import difflib
import json
import re
import time
from collections import deque
from dataclasses import dataclass
from datetime import date
from pathlib import Path

FOOTER_RE = re.compile(r"Runde (\d+)/(\d+)")
FOOTER_LINE_RE = re.compile(r"^-# .*Runde \d+/\d+.*$", re.MULTILINE)
END_MARKER = "[ENDE]"

# Notbremsen im Code – gelten auch, wenn die Config Unsinn enthält.
HARD_MAX_ROUNDS = 30
HARD_MAX_MINUTES = 30
HARD_MIN_COOLDOWN = 1.0


@dataclass
class Incoming:
    channel_id: int
    author_id: int
    author_is_bot: bool
    content: str
    mentions_me: bool
    is_own: bool = False


@dataclass
class Decision:
    respond: bool
    reason: str
    mode: str = ""      # "owner" | "dialog_start" | "dialog"
    turn: int = 0       # Nummer dieser Bot-Antwort in der Kette
    limit: int = 0      # max. Bot-Antworten in dieser Kette
    final: bool = False  # letzte erlaubte Runde: Fazit, nicht weiterreichen
    topic: str = ""


@dataclass
class ChannelState:
    bot_turns: int = 0          # Bot-Nachrichten seit der letzten Menschen-Nachricht
    last_human_ts: float = 0.0
    in_dialog: bool = False
    halted: bool = False        # Stopp oder Mensch hat dazwischengeredet
    last_own_text: str = ""
    context_after_id: int = 0   # !reset: Verlauf erst ab dieser Nachricht


def no(reason: str) -> Decision:
    return Decision(False, reason)


def strip_footer(text: str) -> str:
    return FOOTER_LINE_RE.sub("", text).strip()


class Guard:
    def __init__(self, cfg, clock=time.time):
        self.cfg = cfg
        self.clock = clock
        self.states: dict[int, ChannelState] = {}

    # --- Hilfen -------------------------------------------------------
    def g(self, key, default=None):
        return self.cfg.get(key, default)

    def state(self, channel_id: int) -> ChannelState:
        return self.states.setdefault(channel_id, ChannelState())

    def channel_allowed(self, channel_id: int) -> bool:
        allowed = self.g("discord.allowed_channel_ids") or []
        return not allowed or channel_id in allowed

    def is_stop(self, text: str) -> bool:
        t = text.strip().lower().lstrip(self.prefix()).strip(" !.")
        return t in [w.lower() for w in self.g("guardrails.stop_words", ["stopp"])]

    def prefix(self) -> str:
        return self.g("discord.command_prefix", "!")

    def parse_command(self, text: str):
        """'!dialog 8 Thema' -> ('dialog', '8 Thema'); sonst None."""
        p = self.prefix()
        t = text.strip()
        # Erwähnungen am Anfang erlauben: '@Nova !dialog ...'
        t = re.sub(r"^(<@!?\d+>\s*)+", "", t)
        if not t.startswith(p):
            return None
        head, _, rest = t[len(p):].partition(" ")
        return head.lower(), rest.strip()

    def max_rounds(self) -> int:
        return max(1, min(int(self.g("guardrails.dialog_max_rounds", 12)), HARD_MAX_ROUNDS))

    def max_minutes(self) -> float:
        return max(0.5, min(float(self.g("guardrails.dialog_max_minutes", 5)), HARD_MAX_MINUTES))

    # --- Jede Nachricht im Kanal ---------------------------------------
    def observe(self, m: Incoming) -> None:
        if not self.channel_allowed(m.channel_id):
            return
        st = self.state(m.channel_id)
        if m.author_is_bot:
            footer = FOOTER_RE.search(m.content)
            if footer and footer.group(1) == "1":
                # Eröffnung eines Dialogs: kommt immer von einem Menschen-Befehl
                # (Text oder Slash) – Zähler und Uhr starten hier neu.
                st.bot_turns = 0
                st.halted = False
                st.last_human_ts = self.clock()
            st.bot_turns += 1
            if m.is_own:
                st.last_own_text = strip_footer(m.content)
            if FOOTER_RE.search(m.content):
                st.in_dialog = True
            return

        # Ein Mensch schreibt.
        st.bot_turns = 0
        st.last_human_ts = self.clock()
        if self.is_stop(m.content):
            st.halted = True
            st.in_dialog = False
            return
        cmd = self.parse_command(m.content)
        if cmd and cmd[0] == "dialog":
            st.halted = False
            st.in_dialog = False
            return
        if st.in_dialog:
            # Dazwischengeredet: laufender Dialog pausiert.
            st.halted = True
            st.in_dialog = False

    # --- Soll dieser Bot antworten? -------------------------------------
    def decide(self, m: Incoming) -> Decision:
        if m.is_own:
            return no("eigene Nachricht")
        if not self.channel_allowed(m.channel_id):
            return no("Kanal nicht freigegeben")
        st = self.state(m.channel_id)

        if not m.author_is_bot:
            if m.author_id != int(self.g("bot.owner_id", 0)):
                return no("Mensch ist nicht mein Besitzer")
            if self.is_stop(m.content):
                return no("Stopp")
            cmd = self.parse_command(m.content)
            if cmd and cmd[0] == "dialog":
                if not self.g("guardrails.allow_bot_dialog", True):
                    return no("Bot-Dialog abgeschaltet")
                if not self.g("bot.partner_bot_ids"):
                    return no("kein Partner-Bot konfiguriert")
                rounds, topic = self._parse_dialog_args(cmd[1])
                limit = min(rounds, self.max_rounds())
                return Decision(True, "Dialog gestartet", "dialog_start", 1, limit,
                                final=limit <= 1, topic=topic)
            if cmd:
                return no("anderer Befehl")
            if not self.g("guardrails.respond_to_owner", True):
                return no("Antworten an Besitzer abgeschaltet")
            if self.g("guardrails.require_mention_from_owner", True) and not m.mentions_me:
                return no("nicht erwähnt")
            return Decision(True, "Besitzer fragt", "owner", 1, 1, final=True)

        # Absender ist ein Bot
        if m.author_id not in [int(x) for x in self.g("bot.partner_bot_ids", [])]:
            return no("fremder Bot")
        if not self.g("guardrails.allow_bot_dialog", True):
            return no("Bot-Dialog abgeschaltet")
        if not m.mentions_me:
            return no("Partner hat mich nicht angesprochen")
        if st.halted:
            return no("Dialog pausiert/gestoppt")
        footer = FOOTER_RE.search(m.content)
        if not footer:
            return no("kein Dialog (Footer fehlt)")
        if self.clock() - st.last_human_ts > self.max_minutes() * 60:
            return no("Zeitlimit erreicht")
        limit = min(int(footer.group(2)), self.max_rounds())
        turn = st.bot_turns + 1
        if turn > limit:
            return no("Rundenlimit erreicht")
        return Decision(True, "Partner antwortet", "dialog", turn, limit, final=turn >= limit)

    def start_dialog(self, channel_id: int, rounds: int | None, topic: str) -> Decision:
        """Dialog per Slash-Befehl (der Aufruf ist im Kanal nicht als Nachricht sichtbar)."""
        if not self.channel_allowed(channel_id):
            return no("Kanal nicht freigegeben")
        if not self.g("guardrails.allow_bot_dialog", True):
            return no("Bot-Dialog abgeschaltet")
        if not self.g("bot.partner_bot_ids"):
            return no("kein Partner-Bot konfiguriert")
        st = self.state(channel_id)
        st.bot_turns, st.halted, st.in_dialog, st.last_human_ts = 0, False, False, self.clock()
        limit = min(max(1, rounds or int(self.g("guardrails.dialog_default_rounds", 6))), self.max_rounds())
        return Decision(True, "Dialog per Slash", "dialog_start", 1, limit, final=limit <= 1, topic=topic)

    def stop(self, channel_id: int):
        st = self.state(channel_id)
        st.halted, st.in_dialog = True, False

    def _parse_dialog_args(self, args: str):
        default = int(self.g("guardrails.dialog_default_rounds", 6))
        parts = args.split(maxsplit=1)
        if parts and parts[0].isdigit():
            return max(1, int(parts[0])), (parts[1] if len(parts) > 1 else "")
        return max(1, default), args

    # --- Antwort nachbearbeiten ----------------------------------------
    def finalize(self, channel_id: int, d: Decision, text: str):
        """Gibt (Text, weiterreichen?) zurück."""
        st = self.state(channel_id)
        ended = END_MARKER in text
        text = text.replace(END_MARKER, "").strip()
        max_chars = int(self.g("persona.max_reply_chars", 1500))
        if len(text) > max_chars:
            text = text[: max_chars - 1].rstrip() + "…"
        repeat = False
        if st.last_own_text:
            ratio = difflib.SequenceMatcher(None, text, st.last_own_text).ratio()
            repeat = ratio >= float(self.g("guardrails.repetition_threshold", 0.85))
        pass_on = (
            d.mode in ("dialog_start", "dialog")
            and not d.final
            and not ended
            and not repeat
            and not st.halted
        )
        return text, pass_on


class Budget:
    """Anfragen pro Stunde, Tokens pro Tag, Mindestabstand."""

    def __init__(self, cfg, path: Path, clock=time.time):
        self.cfg = cfg
        self.path = Path(path)
        self.clock = clock
        self.calls: deque[float] = deque()
        self.last_call = 0.0
        self.day = date.today().isoformat()
        self.tokens = 0
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data.get("day") == self.day:
                    self.tokens = int(data.get("tokens", 0))
            except (ValueError, OSError):
                pass

    def _roll_day(self):
        today = date.today().isoformat()
        if today != self.day:
            self.day, self.tokens = today, 0

    def check(self):
        now = self.clock()
        self._roll_day()
        cooldown = max(HARD_MIN_COOLDOWN, float(self.cfg.get("guardrails.cooldown_seconds", 2)))
        if now - self.last_call < cooldown:
            return False, "Mindestabstand"
        while self.calls and now - self.calls[0] > 3600:
            self.calls.popleft()
        if len(self.calls) >= int(self.cfg.get("guardrails.max_requests_per_hour", 60)):
            return False, "Stundenlimit für Anfragen erreicht"
        if self.tokens >= int(self.cfg.get("guardrails.max_tokens_per_day", 300_000)):
            return False, "Tagesbudget an Tokens aufgebraucht"
        return True, ""

    def reserve(self):
        now = self.clock()
        self.last_call = now
        self.calls.append(now)

    def record(self, tokens: int):
        self._roll_day()
        self.tokens += int(tokens)
        try:
            self.path.write_text(json.dumps({"day": self.day, "tokens": self.tokens}), encoding="utf-8")
        except OSError:
            pass

    def status(self) -> str:
        self._roll_day()
        limit = int(self.cfg.get("guardrails.max_tokens_per_day", 300_000))
        hour_limit = int(self.cfg.get("guardrails.max_requests_per_hour", 60))
        return f"Tokens heute: {self.tokens}/{limit} · Anfragen letzte Stunde: {len(self.calls)}/{hour_limit}"
