"""Beschreibung aller Einstellungen – genutzt vom Web-Konfigurator und den Slash-Befehlen."""
from __future__ import annotations

import re

from config import DEFAULT_SETTABLE
from knowledge import DEFAULT_TOOLS as KNOWLEDGE_DEFAULT
from knowledge import DEFAULT_EXT as KNOWLEDGE_EXT
from knowledge import READ_TOOLS as KNOWLEDGE_TOOLS
from guardrails import HARD_MAX_MINUTES, HARD_MAX_ROUNDS, HARD_MIN_COOLDOWN

PROVIDERS = ["anthropic", "claude_code", "openai"]
NOT_CC = {"llm.provider": ["anthropic", "openai"]}
ONLY_CC = {"llm.provider": ["claude_code"]}
VOICE_ON = {"voice.enabled": [True]}
STT_PROVIDERS = ["groq", "openai", "deepgram", "lokal"]
TTS_PROVIDERS = ["azure", "piper", "elevenlabs", "openai"]

# type: text | textarea | int | float | bool | select | id | idlist | list | checklist
SECTIONS = [
    ("Bot & Personen", [
        {"key": "bot.name", "label": "Name deines Bots", "type": "text", "default": "Nova"},
        {"key": "bot.owner_name", "label": "Dein Name", "type": "text", "default": ""},
        {"key": "bot.owner_id", "label": "Deine Discord-User-ID", "type": "id", "required": True,
         "help": "Nur diese Person kann den Bot ansprechen. Rechtsklick auf dich → ID kopieren."},
        {"key": "bot.partner_name", "label": "Name des Partner-Bots", "type": "text", "default": "Kai"},
        {"key": "bot.partner_owner_name", "label": "Besitzer des Partner-Bots", "type": "text", "default": ""},
        {"key": "bot.partner_bot_ids", "label": "User-ID(s) des Partner-Bots", "type": "idlist",
         "help": "Ohne Partner sind keine Bot-Dialoge möglich."},
    ]),
    ("Discord", [
        {"key": "discord.application_id", "label": "Application-ID (für den Einladungslink)", "type": "id",
         "help": "Developer Portal → General Information → Application ID."},
        {"key": "discord.allowed_channel_ids", "label": "Erlaubte Kanal-IDs", "type": "idlist",
         "help": "Leer = alle Kanäle. Empfohlen: nur euer Runden-Kanal."},
        {"key": "discord.required_role", "label": "Pflicht-Rolle des Bots", "type": "text", "default": "",
         "help": "Name oder ID einer Rolle (z. B. AI-Bot). Gesetzt: Der Bot arbeitet auf einem Server nur, wenn ein Admin ihm diese Rolle gegeben hat – sonst bleibt er komplett still. Leer = keine Pflicht-Rolle."},
        {"key": "discord.invite_without_permissions", "label": "Einladen ohne eigene Rechte", "type": "bool", "default": False,
         "help": "Der Einladungslink fordert keine Rechte an – die automatische Bot-Rolle bekommt dann nichts. Alle Rechte vergibt ein Admin über die Pflicht-Rolle (Kanal ansehen, Nachrichten senden, Verlauf lesen, Reaktionen; für Sprache: Verbinden, Sprechen)."},
        {"key": "discord.command_prefix", "label": "Befehlszeichen", "type": "text", "default": "!"},
        {"key": "discord.token_env", "label": "Name der Token-Variable in .env", "type": "text",
         "default": "DISCORD_TOKEN", "advanced": True},
    ]),
    ("Modell", [
        {"key": "llm.provider", "label": "Anbieter", "type": "select", "options": PROVIDERS, "default": "anthropic",
         "labels": ["Anthropic-API", "Claude-Abo (Claude Code)", "Lokal / OpenAI-kompatibel"],
         "help": "claude_code = dein Abo über Claude Code (kein API-Key)."},
        {"key": "llm.model", "label": "Modell", "type": "text", "default": "claude-sonnet-5-5",
         "suggest": ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5", "sonnet", "haiku", "opus"]},
        {"key": "llm.max_tokens", "label": "Max. Antwort-Tokens", "type": "int", "min": 50, "max": 8000,
         "default": 800, "show_if": NOT_CC},
        {"key": "llm.temperature", "label": "Temperatur", "type": "float", "min": 0, "max": 1,
         "default": 0.7, "show_if": NOT_CC, "help": "Nur für OpenAI-kompatible/ältere Modelle – bei aktuellen Claude-Modellen wird sie nicht mehr verwendet."},
        {"key": "llm.api_key_env", "label": "Name der API-Key-Variable in .env", "type": "text",
         "default": "ANTHROPIC_API_KEY", "show_if": NOT_CC, "advanced": True},
        {"key": "llm.base_url", "label": "Base-URL", "type": "text", "default": "",
         "help": "Ollama z. B. http://localhost:11434/v1", "show_if": {"llm.provider": ["openai"]}},
        {"key": "claude_code.path", "label": "Pfad zu claude", "type": "text", "default": "claude", "show_if": ONLY_CC},
        {"key": "claude_code.workdir", "label": "Sandbox-Ordner", "type": "text", "default": "./claude-sandbox",
         "show_if": ONLY_CC},
        {"key": "claude_code.timeout_seconds", "label": "Timeout (s)", "type": "int", "min": 10, "max": 900,
         "default": 180, "show_if": ONLY_CC},
        {"key": "claude_code.mcp_config", "label": "MCP-Freigabedatei", "type": "text", "default": "",
         "help": "Leer = keine Werkzeuge.", "show_if": ONLY_CC},
        {"key": "claude_code.allowed_tools", "label": "Erlaubte Werkzeuge", "type": "list",
         "help": "Eins pro Zeile, z. B. mcp__cortex__read_note", "show_if": ONLY_CC},
    ]),
    ("Persönlichkeit & Kontext", [
        {"key": "persona.system_prompt", "label": "Persona / System-Prompt", "type": "textarea", "default": ""},
        {"key": "persona.max_reply_chars", "label": "Max. Zeichen pro Antwort", "type": "int", "min": 100,
         "max": 1900, "default": 1500},
        {"key": "context.max_messages", "label": "Mitgelesene Nachrichten", "type": "int", "min": 2, "max": 100,
         "default": 30},
        {"key": "context.include_other_humans", "label": "Nachrichten anderer Menschen an die KI senden", "type": "bool", "default": True,
         "help": "An: Der Bot liest alles im Kanal als Kontext (auch was andere schreiben) und schickt es an den KI-Anbieter. Aus (datensparsam, für öffentliche Server): nur deine Nachrichten und die der Bots."},
        {"key": "context.reset_save", "label": "Vor !reset zusammenfassen und speichern", "type": "bool", "default": False,
         "help": "!reset setzt den Verlauf bei beiden Bots zurück. An: vorher fasst die KI den Verlauf zusammen und speichert ihn als Markdown-Datei auf diesem Rechner (kostet eine Anfrage). Aus: nur zurücksetzen."},
        {"key": "context.reset_carry_summary", "label": "Zusammenfassung als Startkontext behalten", "type": "bool", "default": True,
         "show_if": {"context.reset_save": [True]}, "help": "Der Bot kennt nach dem Reset die Kurzfassung – der Kontext bleibt trotzdem klein."},
        {"key": "context.reset_delete", "label": "Nach !reset den Chat im Kanal löschen", "type": "bool", "default": False,
         "help": "Erst speichern beide Bots (je nach Einstellung), dann löscht dieser Bot alle Nachrichten im Kanal bis zum Reset – angeheftete bleiben. Braucht das Discord-Recht „Nachrichten verwalten“ (Servereinstellungen → Rollen → Rolle des Bots). Nur in einem der beiden Bots einschalten genügt."},
        {"key": "context.reset_confirm_both", "label": "!reset erst nach Bestätigung beider Menschen", "type": "bool", "default": True,
         "help": "Der Bot fragt im Kanal nach; der Besitzer des Partner-Bots bestätigt mit ✅ (Reaktion) oder eigenem !reset. Erst dann sichern und zurücksetzen beide."},
        {"key": "context.reset_confirm_minutes", "label": "Bestätigung gilt (min)", "type": "int", "min": 1, "max": 60, "default": 5,
         "show_if": {"context.reset_confirm_both": [True]}, "advanced": True},
        {"key": "context.reset_no_save_text", "label": "Antwort bei !reset ohne Speichern", "type": "text",
         "default": "🤷 Mir egal – Verlauf vergessen, nichts gespeichert.", "show_if": {"context.reset_save": [False]}},
        {"key": "context.dialog_save", "label": "Jeden Dialog automatisch speichern", "type": "bool", "default": False,
         "help": "Am Ende eines Dialogs (Runde x/x · Ende) wird er als Markdown-Datei gespeichert – ohne KI, kostet nichts. Einzeln jederzeit mit !speichern."},
        {"key": "context.reset_folder", "label": "Ordner für gespeicherte Verläufe und Dialoge", "type": "text", "default": "verlauf",
         "help": "Relativ zum Programmordner oder ein voller Pfad. Dialoge landen im Unterordner „dialoge“."},
        {"key": "context.reset_raw", "label": "Beim Reset auch den Rohverlauf speichern", "type": "bool", "default": False,
         "show_if": {"context.reset_save": [True]}, "advanced": True},
        {"key": "context.reset_follow_partner", "label": "Reset des Partner-Bots mitmachen", "type": "bool", "default": True,
         "advanced": True, "help": "Setzt der Partner-Bot per !reset zurück, macht dieser Bot mit (und speichert nach eigener Einstellung)."},
    ]),
    ("Leitplanken", [
        {"key": "guardrails.respond_to_owner", "label": "Antwortet dem Besitzer", "type": "bool", "default": True},
        {"key": "guardrails.require_mention_from_owner", "label": "Nur bei @-Erwähnung", "type": "bool", "default": True},
        {"key": "guardrails.allow_bot_dialog", "label": "Bot-Dialoge erlaubt", "type": "bool", "default": True},
        {"key": "guardrails.dialog_on_double_mention", "label": "Dialog, wenn du beide Bots erwähnst", "type": "bool", "default": True,
         "help": "„@MeinBot @PartnerBot was meint ihr zu …?“ startet einen Dialog mit der Standard-Rundenzahl – wie !dialog."},
        {"key": "guardrails.foreign_reply", "label": "Standardantwort an andere Menschen", "type": "bool", "default": True,
         "help": "Erwähnt jemand anderes den Bot, antwortet er kurz ohne KI, dass er nur auf dich hört (kostet nichts)."},
        {"key": "guardrails.foreign_reply_text", "label": "Text der Standardantwort", "type": "text",
         "default": "Hey {name}, ich höre nur auf {owner}. Sprich am besten deinen eigenen Bot an 🙂",
         "show_if": {"guardrails.foreign_reply": [True]}, "help": "{name} = wer fragt, {owner} = „Dein Name“ unter Bot & Personen, {bot} = Name des Bots."},
        {"key": "guardrails.foreign_reply_cooldown", "label": "Standardantwort höchstens alle (s) pro Person", "type": "int",
         "min": 0, "max": 86400, "default": 600, "show_if": {"guardrails.foreign_reply": [True]}, "advanced": True},
        {"key": "guardrails.dialog_default_rounds", "label": "Runden pro Dialog (Standard)", "type": "int",
         "min": 1, "max": HARD_MAX_ROUNDS, "default": 6},
        {"key": "guardrails.dialog_max_rounds", "label": "Runden pro Dialog (Obergrenze)", "type": "int",
         "min": 1, "max": HARD_MAX_ROUNDS, "default": 12},
        {"key": "guardrails.dialog_max_minutes", "label": "Zeitlimit pro Dialog (min)", "type": "float",
         "min": 0.5, "max": HARD_MAX_MINUTES, "default": 5},
        {"key": "guardrails.stop_words", "label": "Stoppwörter", "type": "list", "default": ["stopp", "stop", "halt"]},
        {"key": "guardrails.repetition_threshold", "label": "Ausstieg bei Wiederholung ab Ähnlichkeit", "type": "float",
         "min": 0.5, "max": 1, "default": 0.85},
        {"key": "guardrails.cooldown_seconds", "label": "Mindestabstand (s)", "type": "float",
         "min": HARD_MIN_COOLDOWN, "max": 600, "default": 2},
        {"key": "guardrails.max_requests_per_hour", "label": "Anfragen pro Stunde", "type": "int", "min": 1,
         "max": 1000, "default": 60},
        {"key": "guardrails.max_tokens_per_day", "label": "Tokens pro Tag", "type": "int", "min": 1000,
         "max": 50_000_000, "default": 300_000},
    ]),
    ("Wissen", [
        {"key": "knowledge.mediavault.enabled", "label": "MediaVault-Wissen nutzen", "type": "bool", "default": False,
         "show_if": {"features.mediavault": [True]},
         "help": "Nur mit Anbieter „Claude-Abo“. Der Bot darf MediaVault lesen – nichts ändern. Alles, was er lesen kann, kann er im Kanal auch erzählen: Schlüssel nur für freigegebene Projekte anlegen."},
        {"key": "knowledge.mediavault.url", "label": "MediaVault-Adresse", "type": "text", "default": "",
         "show_if": {"features.mediavault": [True], "knowledge.mediavault.enabled": [True]}, "help": "z. B. https://…ts.net:8445 – ohne /mcp."},
        {"key": "knowledge.mediavault.tools", "label": "Erlaubte Lese-Werkzeuge", "type": "checklist",
         "options": KNOWLEDGE_TOOLS, "default": KNOWLEDGE_DEFAULT,
         "show_if": {"features.mediavault": [True], "knowledge.mediavault.enabled": [True]},
         "help": "Schreibende Werkzeuge gibt es hier nicht – sie sind für den Bot immer gesperrt."},
        {"key": "knowledge.folders.enabled", "label": "Lokale Ordner nutzen", "type": "bool", "default": False,
         "help": "Mit jedem Anbieter. Der Bot darf in den gewählten Ordnern Textdateien auflisten, durchsuchen und lesen – nichts ändern. Versteckte Ordner, .env- und Schlüsseldateien sind immer gesperrt."},
        {"key": "knowledge.folders.paths", "label": "Wissensordner", "type": "list", "show_if": {"knowledge.folders.enabled": [True]},
         "help": "Ein Ordner pro Zeile, z. B. C:\\Users\\Name\\Documents\\Wissen – oder unten „Ordner wählen …“. Nur Ordner, deren Inhalt in die Runde darf."},
        {"key": "knowledge.folders.extensions", "label": "Dateitypen", "type": "list", "default": KNOWLEDGE_EXT,
         "show_if": {"knowledge.folders.enabled": [True]}, "advanced": True, "help": "Nur Textformate, eins pro Zeile."},
        {"key": "knowledge.github.enabled", "label": "GitHub-Repos nutzen", "type": "bool", "default": False,
         "help": "Mit jedem Anbieter. Der Bot lädt die Repos als Kopie auf diesen Rechner und darf darin Textdateien lesen – nichts ändern."},
        {"key": "knowledge.github.repos", "label": "Repos", "type": "list", "show_if": {"knowledge.github.enabled": [True]},
         "help": "Eins pro Zeile: Besitzer/Repo oder die GitHub-Adresse, optional mit @Branch (z. B. BBZGames/Bratratz_lore@main). Private Repos brauchen GITHUB_TOKEN unter Zugangsdaten."},
        {"key": "knowledge.github.refresh_minutes", "label": "Aktualisieren alle (Minuten)", "type": "int", "min": 5, "max": 1440,
         "default": 60, "show_if": {"knowledge.github.enabled": [True]}, "help": "Der laufende Bot holt neue Stände in diesem Abstand – nur wenn sich etwas geändert hat."},
        {"key": "knowledge.github.max_mb", "label": "Max. Repo-Größe (MB)", "type": "int", "min": 1, "max": 1000, "default": 100,
         "show_if": {"knowledge.github.enabled": [True]}, "advanced": True},
        {"key": "knowledge.github.token_env", "label": "Name der Token-Variable in .env", "type": "text", "default": "GITHUB_TOKEN",
         "show_if": {"knowledge.github.enabled": [True]}, "advanced": True},
        {"key": "knowledge.max_tool_rounds", "label": "Max. Nachschlage-Schritte pro Antwort (API)", "type": "int", "min": 1, "max": 15,
         "default": 6, "advanced": True,
         "help": "Nur Anthropic-API/OpenAI-kompatibel: so oft darf das Modell pro Antwort suchen/lesen. Jeder Schritt kostet Tokens."},
        {"key": "features.mediavault", "label": "MediaVault-Anbindung anzeigen", "type": "bool", "default": False, "advanced": True,
         "help": "Nur für einen eigenen MediaVault-Server. Blendet oben die MediaVault-Einstellungen ein."},
        {"key": "knowledge.folders.max_kb", "label": "Max. Dateigröße (KB)", "type": "int", "min": 10, "max": 5000, "default": 200,
         "show_if": {"knowledge.folders.enabled": [True]}, "advanced": True},
    ]),
    ("Voice-Melder", [
        {"key": "voice_notifier.enabled", "label": "Voice-Melder aktiv", "type": "bool", "default": False,
         "help": "Meldet im Textkanal, wenn jemand einen überwachten Sprachraum betritt. Ohne KI. Pro Server nur in EINEM Bot einschalten, sonst doppelte Meldungen."},
        {"key": "voice_notifier.watch", "label": "Sprachraum → Textkanal", "type": "pairs", "show_if": {"voice_notifier.enabled": [True]},
         "help": "Eine Zeile pro Paar: Sprachraum-ID = Textkanal-ID. Mehrere Paare und Server möglich. Bot braucht im Textkanal „Kanal ansehen“ und „Nachrichten senden“."},
        {"key": "voice_notifier.ping_ids", "label": "Diese Personen benachrichtigen", "type": "idlist",
         "show_if": {"voice_notifier.enabled": [True]},
         "help": "User-IDs, eine pro Zeile. Sie werden in der Meldung erwähnt und bekommen eine Benachrichtigung – außer die Person, die selbst beitritt, und wer schon im Sprachraum ist. Leer = niemand wird erwähnt."},
        {"key": "voice_notifier.delete_on_leave", "label": "Meldung löschen, wenn die Person geht", "type": "bool", "default": True,
         "show_if": {"voice_notifier.enabled": [True]}, "help": "Die Meldung ist dann ein Status: Sie steht nur, solange die Person im Sprachraum ist."},
        {"key": "voice_notifier.leave_grace_seconds", "label": "Schonfrist beim Verlassen (s)", "type": "int", "min": 0, "max": 600, "default": 15,
         "show_if": {"voice_notifier.enabled": [True], "voice_notifier.delete_on_leave": [True]}, "advanced": True,
         "help": "Wer in dieser Zeit wieder reinkommt (z. B. Verbindungsabbruch), behält seine Meldung."},
        {"key": "voice_notifier.cooldown_seconds", "label": "Pause pro Person und Raum (s)", "type": "int", "min": 0, "max": 3600,
         "default": 60, "show_if": {"voice_notifier.enabled": [True], "voice_notifier.delete_on_leave": [False]},
         "help": "Nur ohne „Meldung löschen“: Raus und gleich wieder rein wird innerhalb dieser Zeit nicht erneut gemeldet."},
        {"key": "voice_notifier.template", "label": "Nachricht", "type": "text", "default": "🎙️ {name} ist in <#{channel}>.",
         "show_if": {"voice_notifier.enabled": [True]}, "help": "{name} = Anzeigename, {channel} = Sprachraum (als Link), {channel_name} = Name als Text, {ping} = Erwähnungen (sonst vorne). Andere Pings (@everyone, Rollen) werden nie ausgelöst."},
        {"key": "voice_notifier.disabled_guilds", "label": "Server ohne Melder", "type": "idlist", "show_if": {"voice_notifier.enabled": [True]},
         "advanced": True, "help": "Server-IDs, in denen dieser Bot nicht meldet (z. B. weil dort schon ein anderer Bot meldet)."},
    ]),
    ("Sprache (Beta)", [
        {"key": "voice.enabled", "label": "Sprache aktiv", "type": "bool", "default": False,
         "help": "BETA. Bot betritt Sprachräume, spricht seine Antworten und hört dir zu. Braucht FFmpeg sowie Keys für Spracherkennung und Stimme (Abschnitt unten)."},
        {"key": "voice.output", "label": "Antworten im Sprachraum sprechen", "type": "bool", "default": True, "show_if": VOICE_ON},
        {"key": "voice.text_with_speech", "label": "Gesprochene Antworten zusätzlich als Text", "type": "bool", "default": False,
         "show_if": VOICE_ON, "help": "Aus: Antworten an dich gibt es nur im Sprachraum (der Bot merkt sie sich trotzdem). Bot-Dialoge laufen immer auch als Text – der Partner-Bot kann nur Text lesen."},
        {"key": "voice.live_input", "label": "Live zuhören (experimentell)", "type": "bool", "default": True, "show_if": VOICE_ON,
         "help": "Nur deine Stimme wird verarbeitet. Kopfhörer empfohlen."},
        {"key": "voice.voice_messages", "label": "Sprachnachrichten verstehen", "type": "bool", "default": True, "show_if": VOICE_ON,
         "help": "Mikrofon-Knopf im Textkanal – funktioniert auch am Handy."},
        {"key": "voice.follow_owner", "label": "Folgt dir in den Sprachraum", "type": "bool", "default": True, "show_if": VOICE_ON,
         "help": "Sonst mit !beitreten bzw. /name beitreten holen."},
        {"key": "voice.require_wake_word", "label": "Nur mit Rufnamen reagieren", "type": "bool", "default": True, "show_if": VOICE_ON,
         "help": "„Nova, was meinst du?“ – ohne Rufnamen hört er nur mit."},
        {"key": "voice.dialog_output", "label": "Bot-Dialoge sprechen", "type": "select", "options": ["nur_fazit", "alles", "aus"],
         "labels": ["Nur das Fazit", "Jede Runde", "Gar nicht"],
         "default": "nur_fazit", "show_if": VOICE_ON},
        {"key": "voice.barge_in", "label": "Unterbrechen, wenn du sprichst", "type": "bool", "default": True, "show_if": VOICE_ON},
        {"key": "voice.post_transcripts", "label": "Gesprochenes als Text in den Kanal", "type": "bool", "default": True, "show_if": VOICE_ON,
         "help": "Nötig, damit der andere Bot mitbekommt, was du sagst."},
        {"key": "voice.text_channel_id", "label": "Textkanal für Gesprochenes", "type": "id", "show_if": VOICE_ON,
         "help": "Leer = erster erlaubter Kanal."},
        {"key": "voice.channel_ids", "label": "Erlaubte Sprachräume", "type": "idlist", "show_if": VOICE_ON,
         "help": "Leer = alle."},
        {"key": "voice.wake_words", "label": "Weitere Rufnamen", "type": "list", "show_if": VOICE_ON,
         "help": "Der Bot-Name zählt immer. Hilfreich, wenn die Erkennung den Namen anders schreibt."},
        {"key": "voice.silence_ms", "label": "Sprechpause bis Ende (ms)", "type": "int", "min": 300, "max": 3000,
         "default": 900, "show_if": VOICE_ON, "advanced": True},
        {"key": "voice.max_utterance_s", "label": "Max. Länge einer Äußerung (s)", "type": "int", "min": 5, "max": 120,
         "default": 30, "show_if": VOICE_ON, "advanced": True},
        {"key": "voice.max_spoken_chars", "label": "Max. gesprochene Zeichen pro Antwort", "type": "int", "min": 100,
         "max": 3000, "default": 900, "show_if": VOICE_ON, "advanced": True},
    ]),
    ("Spracherkennung & Stimme", [
        {"key": "stt.provider", "label": "Spracherkennung", "type": "select", "options": STT_PROVIDERS, "default": "groq",
         "labels": ["Groq (empfohlen)", "OpenAI", "Deepgram", "Lokal (faster-whisper)"],
         "show_if": VOICE_ON, "help": "groq: sehr schnell, Cent-Beträge. lokal: faster-whisper auf diesem Rechner."},
        {"key": "stt.model", "label": "Erkennungs-Modell", "type": "text", "default": "", "show_if": VOICE_ON,
         "help": "Leer = Standard des Anbieters.", "advanced": True},
        {"key": "stt.language", "label": "Sprache", "type": "text", "default": "de", "show_if": VOICE_ON, "advanced": True},
        {"key": "tts.provider", "label": "Stimme von", "type": "select", "options": TTS_PROVIDERS, "default": "azure",
         "labels": ["Azure (empfohlen)", "Piper (lokal, gratis)", "ElevenLabs", "OpenAI"],
         "show_if": VOICE_ON, "help": "azure: natürliche Stimmen, 500.000 Zeichen/Monat frei. piper: lokal, kostenlos."},
        {"key": "tts.voice", "label": "Stimme", "type": "text", "default": "", "show_if": VOICE_ON,
         "suggest": ["de-DE-KatjaNeural", "de-DE-ConradNeural", "de-DE-SeraphinaMultilingualNeural", "de-DE-FlorianMultilingualNeural", "alloy", "nova", "onyx"],
         "help": "Leer = Standard. Azure: z. B. de-DE-KatjaNeural · ElevenLabs: Voice-ID · Piper: Pfad zur .onnx-Datei."},
        {"key": "tts.speed", "label": "Sprechtempo", "type": "float", "min": 0.5, "max": 2.0, "default": 1.0, "show_if": VOICE_ON},
        {"key": "tts.azure_region", "label": "Azure-Region", "type": "text", "default": "westeurope",
         "suggest": ["westeurope", "northeurope", "swedencentral", "germanywestcentral", "eastus"],
         "help": "Wie beim Anlegen des Speech-Dienstes gewählt, z. B. westeurope.",
         "show_if": {"voice.enabled": [True], "tts.provider": ["azure"]}},
        {"key": "tts.piper_path", "label": "Pfad zu piper", "type": "text", "default": "piper",
         "show_if": {"voice.enabled": [True], "tts.provider": ["piper"]}, "advanced": True},
    ]),
    ("Updates", [
        {"key": "update.mode", "label": "Nach Updates suchen", "type": "select", "options": ["manuell", "hinweis", "automatisch"],
         "default": "manuell",
         "help": "manuell = nur per Knopf (kein Online-Check beim Start) · hinweis = beim Start prüfen und anzeigen · automatisch = beim Start von Bot oder Konfigurator installieren und neu starten. Konfiguration und Schlüssel bleiben immer erhalten."},
    ]),
    ("Chat-Rechte", [
        {"key": "guardrails.settable_keys", "label": "Per Chat änderbar (!set und Slash-Befehle)", "type": "checklist",
         "options": DEFAULT_SETTABLE, "default": DEFAULT_SETTABLE},
    ]),
]

FIELDS = {f["key"]: f for _, fields in SECTIONS for f in fields}


def to_value(field: dict, raw):
    """Wert aus Formular/Chat in den richtigen Typ bringen. Wirft ValueError mit deutscher Meldung."""
    t = field["type"]
    label = field["label"]
    if t in ("text", "textarea", "select"):
        val = "" if raw is None else str(raw)
        if t == "select" and val not in field["options"]:
            raise ValueError(f"{label}: erlaubt sind {', '.join(field['options'])}")
        return val
    if t == "bool":
        if isinstance(raw, bool):
            return raw
        low = str(raw).strip().lower()
        if low in ("true", "ja", "an", "on", "1"):
            return True
        if low in ("false", "nein", "aus", "off", "0", ""):
            return False
        raise ValueError(f"{label}: ja oder nein")
    if t in ("int", "float"):
        if raw in (None, ""):
            raise ValueError(f"{label}: Wert fehlt")
        try:
            val = int(str(raw).strip()) if t == "int" else float(str(raw).replace(",", ".").strip())
        except ValueError:
            raise ValueError(f"{label}: keine Zahl") from None
        if "min" in field and val < field["min"]:
            raise ValueError(f"{label}: mindestens {field['min']}")
        if "max" in field and val > field["max"]:
            raise ValueError(f"{label}: höchstens {field['max']}")
        return val
    if t == "id":
        s = "" if raw is None else str(raw).strip()
        if not s:
            if field.get("required"):
                raise ValueError(f"{label}: fehlt")
            return None
        if not s.isdigit() or not 15 <= len(s) <= 21:
            raise ValueError(f"{label}: keine gültige Discord-ID ({s})")
        return int(s)
    if t == "pairs":
        if isinstance(raw, dict):
            items = [f"{k} = {v}" for k, v in raw.items()]
        else:
            items = raw if isinstance(raw, list) else str(raw or "").splitlines()
        out = {}
        for line in items:
            line = str(line).strip()
            if not line or line.startswith("#"):
                continue
            parts = [p for p in re.split(r"\s*(?:=|->|→|:|\s)\s*", line) if p]
            if len(parts) != 2 or not all(p.isdigit() and 15 <= len(p) <= 21 for p in parts):
                raise ValueError(f"{label}: Zeile „{line}“ – Format: Sprachraum-ID = Textkanal-ID")
            out[int(parts[0])] = int(parts[1])
        return out
    if t in ("idlist", "list", "checklist"):
        items = raw if isinstance(raw, list) else str(raw or "").replace(",", "\n").splitlines()
        items = [str(i).strip() for i in items if str(i).strip()]
        if t == "idlist":
            out = []
            for s in items:
                if not s.isdigit() or not 15 <= len(s) <= 21:
                    raise ValueError(f"{label}: keine gültige Discord-ID ({s})")
                out.append(int(s))
            return out
        if t == "checklist":
            bad = [i for i in items if i not in field["options"]]
            if bad:
                raise ValueError(f"{label}: unbekannt {', '.join(bad)}")
        return items
    raise ValueError(f"{label}: unbekannter Typ {t}")


def check_consistency(get) -> tuple[list[str], list[str]]:
    """Fehler und Warnungen über mehrere Felder hinweg. `get(key)` liefert den wirksamen Wert."""
    errors, warnings = [], []
    if not get("bot.owner_id"):
        errors.append("Deine Discord-User-ID fehlt – der Bot würde auf niemanden reagieren.")
    if (get("guardrails.dialog_default_rounds") or 6) > (get("guardrails.dialog_max_rounds") or 12):
        warnings.append("Standard-Runden liegen über der Obergrenze – es gilt die Obergrenze.")
    if not get("bot.partner_bot_ids") and get("guardrails.allow_bot_dialog"):
        warnings.append("Kein Partner-Bot eingetragen – Bot-Dialoge funktionieren nicht.")
    if not get("discord.allowed_channel_ids"):
        warnings.append("Keine Kanäle eingeschränkt – der Bot liest in allen Kanälen des Servers mit.")
    if get("llm.provider") == "claude_code" and get("claude_code.allowed_tools") and not get("claude_code.mcp_config"):
        warnings.append("Werkzeuge erlaubt, aber keine MCP-Freigabedatei – die Werkzeuge gibt es dann nicht.")
    owner = get("bot.owner_id")
    if owner and owner in (get("bot.partner_bot_ids") or []):
        errors.append("Deine User-ID steht auch als Partner-Bot drin.")
    if get("knowledge.mediavault.enabled"):
        if get("llm.provider") != "claude_code":
            warnings.append("MediaVault-Wissen funktioniert nur mit Anbieter „Claude-Abo“ – bei anderen Anbietern bleibt es aus.")
        if not (get("knowledge.mediavault.url") or "").strip():
            warnings.append("MediaVault-Wissen ist an, aber die Adresse fehlt.")
        if not get("knowledge.mediavault.tools"):
            warnings.append("MediaVault-Wissen ist an, aber kein Werkzeug erlaubt.")
    if get("knowledge.folders.enabled"):
        if not get("knowledge.folders.paths"):
            warnings.append("Wissensordner sind an, aber es ist kein Ordner eingetragen.")
    if get("knowledge.github.enabled"):
        specs = get("knowledge.github.repos") or []
        if not specs:
            warnings.append("GitHub-Repos sind an, aber es ist kein Repo eingetragen.")
        import wissen_github
        for sp in specs:
            try:
                wissen_github.parse(sp)
            except wissen_github.RepoError as e:
                errors.append(f"GitHub: {e}")
    if get("voice_notifier.enabled"):
        if not get("voice_notifier.watch"):
            warnings.append("Voice-Melder ist an, aber es ist kein Sprachraum → Textkanal eingetragen.")
        tpl = get("voice_notifier.template") or ""
        try:
            tpl.format(name="x", channel=1, channel_name="x", ping="")
        except (KeyError, IndexError, ValueError):
            errors.append("Voice-Melder: Vorlage fehlerhaft – erlaubt sind {name}, {channel}, {channel_name}, {ping}.")
    if get("voice.enabled"):
        if get("voice.live_input") and not (get("voice.text_channel_id") or get("discord.allowed_channel_ids")):
            warnings.append("Sprache: Kein Textkanal für Gesprochenes – unter Sprache oder Discord einen Kanal eintragen.")
        if get("tts.provider") == "elevenlabs" and not get("tts.voice"):
            errors.append("ElevenLabs braucht eine Voice-ID unter „Stimme“.")
        if get("tts.provider") == "piper" and not get("tts.voice"):
            errors.append("Piper braucht den Pfad zur .onnx-Stimme unter „Stimme“.")
    return errors, warnings
