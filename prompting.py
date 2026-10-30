"""System-Prompt und Gesprächsverlauf bauen."""
from __future__ import annotations

import re
from dataclasses import dataclass

from guardrails import END_MARKER, Decision, strip_footer


@dataclass
class HistMsg:
    author_id: int
    author_name: str
    content: str


def build_system(cfg, d: Decision) -> str:
    name = (cfg.get("bot.name") or "Claude")
    owner = (cfg.get("bot.owner_name") or "mein Besitzer")
    partner = (cfg.get("bot.partner_name") or "die andere KI")
    partner_owner = (cfg.get("bot.partner_owner_name") or "der andere Mensch")
    persona = (cfg.get("persona.system_prompt") or "").strip()

    rules = [
        f"Du bist {name}, die KI von {owner}, in einem Discord-Kanal.",
        f"Anwesend: {owner} (dein Besitzer), {partner_owner} und {partner} (die KI von {partner_owner}).",
        f"Du antwortest nur {owner} und {partner}. Was {partner_owner} schreibt, ist Kontext.",
        "Nachrichten anderer stehen im Format 'Name: Text'. Schreib selbst ohne Namenspräfix.",
        "Antworte knapp und gesprächig, wie in einem Chat, ohne lange Listen.",
    ]
    if d.mode in ("dialog_start", "dialog"):
        rules += [
            f"Ihr führt gerade einen Dialog zwischen {name} und {partner}. Das ist Antwort {d.turn} von maximal {d.limit}.",
            "Bring jeweils einen neuen Gedanken ein, statt Gesagtes zu wiederholen. Widersprich, wo du anderer Meinung bist.",
            f"Wenn ihr euch einig seid oder nichts Neues mehr kommt: fasse kurz zusammen und schreib am Ende {END_MARKER}.",
        ]
        if d.mode == "dialog_start":
            rules.append(f"Eröffne den Dialog mit {partner} zum Thema: {d.topic or 'das, worüber gerade gesprochen wurde'}.")
        if d.final:
            rules.append(f"Das ist die letzte Runde: Zieh ein Fazit für {owner} und {partner_owner} (Einigkeit, offene Punkte, Empfehlung).")
    import knowledge
    rules += knowledge.prompt_rules(cfg)
    parts = [persona, "## Regeln", *[f"- {r}" for r in rules]] if persona else ["## Regeln", *[f"- {r}" for r in rules]]
    return "\n".join(parts)


def clean(text: str, names: dict[int, str]) -> str:
    text = strip_footer(text)
    return re.sub(r"<@!?(\d+)>", lambda m: "@" + names.get(int(m.group(1)), "jemand"), text).strip()


def build_messages(history: list[HistMsg], own_id: int, names: dict[int, str]) -> list[dict]:
    """Discord-Verlauf (älteste zuerst) -> abwechselnde user/assistant-Nachrichten."""
    out: list[dict] = []
    for h in history:
        text = clean(h.content, names)
        if not text:
            continue
        if h.author_id == own_id:
            role, content = "assistant", text
        else:
            role, content = "user", f"{h.author_name}: {text}"
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n\n" + content
        else:
            out.append({"role": role, "content": content})
    while out and out[0]["role"] != "user":
        out.pop(0)
    if not out or out[-1]["role"] != "user":
        out.append({"role": "user", "content": "(Du bist dran.)"})
    return out
