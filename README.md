# Claude-Runde

> **Status: Beta (v0.1.0).** Leitplanken und Abo-Anbindung sind automatisch getestet, der Betrieb mit zwei Bots in echtem Discord noch nicht. Bitte erst in einem eigenen Test-Server ausprobieren.

Discord-Bot für eine Runde aus zwei Menschen und zwei KIs. Jede Person betreibt **einen eigenen Bot** auf dem eigenen Rechner, mit eigenem API-Key **oder eigenem Claude-Abo**. Gleicher Code, eigene `config.yaml`.

## Was der Bot tut

- Antwortet **nur seinem Besitzer** (standardmäßig nur bei @-Erwähnung) und **nur dem Partner-Bot**.
- Liest alles im Kanal mit, damit er weiß, worum es geht.
- Führt auf Befehl einen **Dialog mit dem Partner-Bot**, innerhalb fester Leitplanken.
- LLM: Anthropic-API, Claude-Abo über Claude Code oder jede OpenAI-kompatible API (z. B. Ollama lokal).

## ⚠️ Wichtige Hinweise

- **Zugangsdaten gehören nur in die `.env`.** Discord-Token und API-Key niemals in die `config.yaml`, in Chats oder in ein Repo. Die `.gitignore` schließt `.env` und `config.yaml` aus – prüf trotzdem vor jedem Commit. Ist ein Token einmal öffentlich, sofort im Developer Portal bzw. in der Anthropic-Konsole neu erzeugen.
- **Mitlesen:** Der Bot liest im freigegebenen Kanal alle Nachrichten mit und schickt die letzten Nachrichten als Kontext an das KI-Modell (Anthropic bzw. den gewählten Anbieter). Sag allen im Kanal Bescheid und nutze einen eigenen Kanal (`allowed_channel_ids`). Keine sensiblen oder personenbezogenen Daten Dritter in den Kanal.
- **Kosten:** Mit API-Key kostet jede Antwort Geld. Setz in der Anthropic-Konsole ein Ausgabelimit und halte `max_tokens_per_day` und `max_requests_per_hour` niedrig.
- **Abo-Variante:** Läuft über dein eingeloggtes Claude-Abo und zählt auf dein Nutzungskontingent. Ein dauerhaft laufender Bot über ein Abo ist nicht dasselbe wie normale Nutzung – prüf die aktuellen Nutzungsbedingungen von Anthropic, bevor du ihn dauerhaft betreibst. Nur du solltest deinen Bot auslösen (das erzwingt `owner_id`). Ist `ANTHROPIC_API_KEY` gesetzt, nutzt Claude Code den Key statt des Abos.
- **Werkzeuge:** In der Abo-Variante hat der Bot standardmäßig keine Werkzeuge. Gib über `claude_code.mcp_config`/`allowed_tools` nur frei, was der Bot wirklich braucht – alles, worauf er zugreifen kann, kann er auch im Kanal ausplaudern.
- **Konfigurator:** läuft nur auf `127.0.0.1` und ist nicht für den Betrieb im Netzwerk gedacht. Nicht per Portfreigabe o. Ä. ins Internet stellen.
- Ohne Gewähr: Der Bot gibt KI-Antworten wieder, die falsch sein können.

## Einrichtung (pro Person, ca. 15 Minuten)

1. **Discord-Bot anlegen:** discord.com/developers/applications → New Application → Reiter *Bot* → Token kopieren. Dort **Message Content Intent** einschalten.
2. **Einladen:** Application-ID im Konfigurator eintragen und auf „Einladungslink“ klicken. Oder von Hand: Reiter *OAuth2 → URL Generator* → Scopes `bot` **und** `applications.commands`, Rechte *Send Messages*, *Read Message History*, *View Channels* → Link öffnen, Server wählen.
3. **IDs holen:** In Discord *Einstellungen → Erweitert → Entwicklermodus* an. Dann Rechtsklick → *ID kopieren* für: dich selbst, den Bot des anderen, den Runden-Kanal.
4. **Am einfachsten:** `konfigurator.bat` doppelklicken. Im Browser alles ausfüllen, Token setzen, speichern, „Testanfrage“ drücken. Alternativ von Hand: `config.example.yaml` → `config.yaml` kopieren und ausfüllen. `.env.example` → `.env` kopieren und den Discord-Token eintragen, bei der API-Variante auch den API-Key.
5. Windows: `start.bat` doppelklicken. Sonst: `pip install -r requirements.txt` und `python bot.py config.yaml`.

## Abo-Variante (ohne API-Key)

1. Claude Code installieren und **einmal** im Terminal `claude` starten und mit deinem Abo einloggen.
2. Prüfen: `claude -p "sag hallo"` muss antworten.
3. In der `config.yaml`: `llm.provider: claude_code`, `llm.model: sonnet`. `ANTHROPIC_API_KEY` in der `.env` leer lassen. Ist dort ein Key gesetzt, nimmt Claude Code den statt des Abos.
4. Starten wie gewohnt.

Was dabei passiert: Pro Antwort ruft der Bot `claude -p` auf. Standardmäßig sind **alle Werkzeuge aus**: kein Bash, kein Dateizugriff, keine MCP-Server. Nur wenn du unter `claude_code` eine MCP-Freigabedatei und `allowed_tools` einträgst, darf er genau diese Werkzeuge nutzen (z. B. Cortex lesen).

Hinweise:
- Jede Antwort zählt aufs Abo-Kontingent. `max_requests_per_hour` niedrig halten.
- Eine Antwort dauert ein paar Sekunden länger als über die API.
- Ein Dauer-Bot über das Abo ist eine Grauzone. Nur du solltest deinen Bot auslösen (das erzwingt `owner_id`), und prüft die aktuellen Nutzungsbedingungen.

## Konfigurator

`konfigurator.bat` (oder `python konfigurator.py config.yaml`) öffnet eine Oberfläche unter http://127.0.0.1:8765, nur auf diesem Rechner erreichbar.

- **Vorher:** legt die `config.yaml` aus der Vorlage an, prüft IDs und Grenzwerte, setzt Token und API-Key in der `.env` (Werte werden nie angezeigt).
- **Bei laufendem Bot:** zeigt, ob der Bot läuft und den Verbrauch heute. Gespeicherte Änderungen gelten ab der nächsten Nachricht im Kanal, ohne Neustart. Nur ein neuer Discord-Token braucht einen Neustart.
- **Chat-Werte:** Was per `!set` oder Slash-Befehl gesetzt wurde, überschreibt die Datei. Der Konfigurator zeigt das am Feld und kann es entfernen.
- **Testanfrage:** schickt eine echte Anfrage mit der gespeicherten Konfiguration, auch über das Abo.
- Vor jedem Speichern wird eine Sicherung `config.yaml.bak` angelegt. Kommentare in der `config.yaml` gehen beim Speichern verloren, die Erklärungen stehen im Konfigurator.

## Slash-Befehle in Discord

Die Befehlsgruppe heißt wie dein Bot, also z. B. `/nova …` und `/kai …`. So kommen sich die zwei Bots nicht in die Quere. Antworten sieht nur, wer den Befehl aufruft.

| Befehl | Wirkung |
|---|---|
| `/nova panel` | Schalter für Erwähnung und Bot-Dialoge, Auswahl für Runden und Modell, Persona im Textfenster bearbeiten |
| `/nova set` | Einstellung ändern, mit Vorschlägen für Schlüssel und Werte |
| `/nova zuruecksetzen` | Chat-Wert entfernen (ohne Angabe: alle) |
| `/nova status` | Einstellungen und Verbrauch |
| `/nova dialog` | Dialog mit dem Partner-Bot starten |
| `/nova stopp` | Dialog beenden (darf jeder) |

Alles außer `stopp` nur für den Besitzer. Es gelten dieselben Prüfungen und Grenzen wie im Konfigurator. Was per Chat änderbar ist, legst du im Konfigurator unter „Chat-Rechte“ fest. Wurde der Bot ohne `applications.commands` eingeladen, einfach mit dem neuen Einladungslink nochmal einladen.

## Text-Befehle (nur der Besitzer)

| Befehl | Wirkung |
|---|---|
| `@Nova <Frage>` | Bot antwortet dir |
| `!dialog [runden] <thema>` | Bot eröffnet einen Dialog mit dem Partner-Bot |
| `!stopp` | beendet einen laufenden Dialog (darf **jeder** Mensch im Kanal) |
| `!status` | aktuelle Einstellungen und Budget |
| `!set <schlüssel> <wert>` | Einstellung live ändern, z. B. `!set llm.temperature 0.4` |
| `!unset <schlüssel>` | zurück auf den Wert aus der `config.yaml` |
| `!reset` | Gesprächsverlauf ab hier neu |
| `!hilfe` | Übersicht |

Werte aus `!set` landen in `config.overrides.json` und überleben einen Neustart. Welche Schlüssel per Chat änderbar sind, legt `guardrails.settable_keys` fest. Besitzer-ID, Partner-IDs, Kanäle und API-Keys sind standardmäßig **nicht** per Chat änderbar.

## Leitplanken

| Leitplanke | Einstellung | Standard |
|---|---|---|
| Nur Besitzer + Partner-Bot | `bot.owner_id`, `bot.partner_bot_ids` | – |
| Nur freigegebene Kanäle | `discord.allowed_channel_ids` | alle |
| Besitzer muss erwähnen | `guardrails.require_mention_from_owner` | ja |
| Bot-Dialog an/aus | `guardrails.allow_bot_dialog` | an |
| Runden pro Dialog | `guardrails.dialog_default_rounds` / `dialog_max_rounds` | 6 / 12 |
| Zeitlimit pro Dialog | `guardrails.dialog_max_minutes` | 5 min |
| Stoppwörter | `guardrails.stop_words` | stopp, stop, halt |
| Ausstieg bei Wiederholung | `guardrails.repetition_threshold` | 0,85 |
| Mindestabstand zwischen Antworten | `guardrails.cooldown_seconds` | 2 s |
| Anfragen pro Stunde | `guardrails.max_requests_per_hour` | 60 |
| Tokens pro Tag | `guardrails.max_tokens_per_day` | 300 000 |
| Antwortlänge | `persona.max_reply_chars`, `llm.max_tokens` | 1500 Zeichen / 800 Tokens |

**Notbremsen im Code** (nicht konfigurierbar): höchstens 30 Runden, höchstens 30 Minuten, mindestens 1 s Abstand.

### Wie der Dialog sicher bleibt

- Ein Dialog startet **nur durch einen Menschen** (`!dialog`). Von selbst fangen die Bots nie an.
- Jede Dialog-Nachricht trägt einen Footer `Runde x/y`. Jeder Bot zählt selbst mit und nimmt das **kleinere** Limit aus Footer und eigener Config. Ein falsch eingestellter Partner kann das eigene Limit also nicht aushebeln.
- Weitergereicht wird nur per @-Erwähnung. In der letzten Runde, bei `[ENDE]` (Einigung) oder bei Wiederholung lässt der Bot die Erwähnung weg, und der Dialog ist vorbei. Die letzte Antwort ist ein Fazit.
- Schreibt ein Mensch während eines Dialogs dazwischen, pausiert der Dialog. Ein neues `!dialog` setzt ihn fort.
- Eine Antwort, die noch generiert wurde, als `!stopp` kam, wird verworfen.

## Dateien

- `bot.py` – Discord-Anbindung und Befehle
- `guardrails.py` – alle Leitplanken, ohne Discord, getestet
- `prompting.py` – System-Prompt und Verlauf
- `llm.py` – Anthropic-API, Claude-Abo (`claude -p`), OpenAI-kompatibel
- `config.py` – YAML, Live-Neuladen, `!set`
- `konfigurator.py` + `konfigurator.html` – Weboberfläche
- `slash.py` – Slash-Befehle und Panel
- `settings_schema.py` – alle Einstellungen mit Typ, Grenzen und Hilfetext (gemeinsam für Konfigurator, `!set` und Slash)
- `tests/` – `python -m pytest tests`

## Nächste Stufen

1. Vault- und MediaVault-Zugriff als Werkzeuge (nur freigegebene Ordner)
2. Sprachausgabe im Voicechannel (Piper)
3. Spracheingabe (faster-whisper)
