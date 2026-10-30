# Cortex QuorumBot

**Download – neueste Version:**
- **[⬇ Windows-Programm (CortexQuorumBot-Windows.zip)](https://github.com/LowKI2/cortex-quorumbot-release/releases/latest/download/CortexQuorumBot-Windows.zip)** – ohne Python, eigenes Programmfenster. Nicht signiert: Windows warnt beim ersten Start (siehe unten).
- **[⬇ Python-Variante (CortexQuorumBot.zip)](https://github.com/LowKI2/cortex-quorumbot-release/releases/latest/download/CortexQuorumBot.zip)** – braucht Python 3.11+, offener Quellcode, Konfigurator im Browser.

[Alle Versionen](https://github.com/LowKI2/cortex-quorumbot-release/releases) · Entpacken, `CortexQuorumBot.exe` bzw. `konfigurator.bat` doppelklicken. Updates danach direkt im Konfigurator.

**Text- und Sprachbot für Discord** – eine Runde aus Menschen und KI-Bots, mit festen Leitplanken. Ein Werkzeug von BZi Studio.

> **Status: Beta (v0.8.1).** Leitplanken und Abo-Anbindung sind automatisch getestet, der Betrieb mit zwei Bots in echtem Discord noch nicht. Bitte erst in einem eigenen Test-Server ausprobieren.

Gedacht für eine Runde aus zwei Menschen und zwei KIs. Jede Person betreibt **einen eigenen Bot** auf dem eigenen Rechner, mit eigenem API-Key **oder eigenem Claude-Abo**. Gleicher Code, eigene `config.yaml`.

## Was der Bot tut

- Antwortet **nur seinem Besitzer** (standardmäßig nur bei @-Erwähnung) und **nur dem Partner-Bot**.
- Liest alles im Kanal mit, damit er weiß, worum es geht.
- Führt auf Befehl einen **Dialog mit dem Partner-Bot**, innerhalb fester Leitplanken.
- LLM: Anthropic-API, Claude-Abo über Claude Code oder jede OpenAI-kompatible API (z. B. Ollama lokal).

**➜ Schritt-für-Schritt-Anleitung mit Tests: [INSTALLATION.md](INSTALLATION.md).** Kurz: Python installieren, `konfigurator.bat` starten, dem Assistenten folgen.

> Cortex QuorumBot ist ein unabhängiges Projekt und steht in keiner Verbindung zu Anthropic oder Discord. „Claude“ und „Discord“ sind Marken ihrer jeweiligen Inhaber.

## ⚠️ Wichtige Hinweise

- **Zugangsdaten gehören nur in die `.env`.** Discord-Token und API-Key niemals in die `config.yaml`, in Chats oder in ein Repo. Die `.gitignore` schließt `.env` und `config.yaml` aus – prüf trotzdem vor jedem Commit. Ist ein Token einmal öffentlich, sofort im Developer Portal bzw. in der Anthropic-Konsole neu erzeugen.
- **Mitlesen:** Der Bot liest im freigegebenen Kanal alle Nachrichten mit und schickt die letzten Nachrichten als Kontext an das KI-Modell (Anthropic bzw. den gewählten Anbieter). Sag allen im Kanal Bescheid und nutze einen eigenen Kanal (`allowed_channel_ids`). Keine sensiblen oder personenbezogenen Daten Dritter in den Kanal.
- **Kosten:** Mit API-Key kostet jede Antwort Geld. Setz in der Anthropic-Konsole ein Ausgabelimit und halte `max_tokens_per_day` und `max_requests_per_hour` niedrig.
- **Abo-Variante:** Läuft über dein eingeloggtes Claude-Abo und zählt auf dein Nutzungskontingent. Ein dauerhaft laufender Bot über ein Abo ist nicht dasselbe wie normale Nutzung – prüf die aktuellen Nutzungsbedingungen von Anthropic, bevor du ihn dauerhaft betreibst. Nur du solltest deinen Bot auslösen (das erzwingt `owner_id`). Ist `ANTHROPIC_API_KEY` gesetzt, nutzt Claude Code den Key statt des Abos.
- **Werkzeuge:** In der Abo-Variante hat der Bot standardmäßig keine Werkzeuge. Gib über `claude_code.mcp_config`/`allowed_tools` nur frei, was der Bot wirklich braucht – alles, worauf er zugreifen kann, kann er auch im Kanal ausplaudern.
- **Konfigurator:** läuft nur auf `127.0.0.1` und ist nicht für den Betrieb im Netzwerk gedacht. Nicht per Portfreigabe o. Ä. ins Internet stellen.
- Ohne Gewähr: Der Bot gibt KI-Antworten wieder, die falsch sein können.

## Einrichtung (pro Person, ca. 15 Minuten)

1. Python 3.11+ installieren („Add to PATH“ anhaken).
2. `konfigurator.bat` doppelklicken – der Assistent führt durch Discord-Bot, Modellzugang, Einladen, IDs und Test.
3. Wenn der Test „Startklar“ meldet: `start.bat` doppelklicken (oder im Assistenten „Bot jetzt starten“).

Ausführlich mit Funktionstest in Discord und Fehlerhilfe: **[INSTALLATION.md](INSTALLATION.md)**. Ohne Windows: `pip install -r requirements.txt`, dann `python konfigurator.py`, `python pruefen.py`, `python bot.py config.yaml`.

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

Beim ersten Start öffnet sich ein **Einrichtungsassistent** (Discord-Bot anlegen, Modellzugang, Einladen und IDs, Namen, Test). Später über den Knopf „Assistent“ erneut aufrufbar. „Vollständiger Test“ prüft Discord-Token, Message Content Intent, Server, Kanal, IDs und Modell und sagt bei jedem Fehler, was zu tun ist.

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

## Wissen: lokale Ordner und GitHub-Repos

Der Bot kann in Ordnern und GitHub-Repos nachschlagen, die du freigibst – **nur lesend**, mit **jedem Anbieter** (Claude-Abo, Anthropic-API, OpenAI-kompatibel mit Werkzeug-fähigem Modell). Alles im Konfigurator unter **Wissen**, ohne Dateien von Hand zu bearbeiten. Wichtig: Alles, was der Bot lesen kann, kann er im Kanal auch erzählen.

1. Konfigurator → **Wissen** → „Lokale Ordner“ einschalten → **Ordner wählen …** (mehrere Ordner möglich). **Speichern.**
2. **Wissen prüfen** zeigt, ob die Ordner da sind und wie viele Dateien lesbar sind.
3. Gelesen werden nur Textdateien (`.md`, `.txt`, `.csv`, `.json`, `.yaml`, `.html` …, unter „Erweitert“ änderbar) bis 200 KB. Nie gelesen: versteckte Ordner (`.git`, `.obsidian` …), `.env`, Schlüssel-, Passwort- und Token-Dateien, alles außerhalb der gewählten Ordner. Lieber einen eigenen Wissensordner wählen statt ganz `C:\` oder „Dokumente“.

**GitHub-Repos** (mehrere möglich, öffentlich und privat):
1. Konfigurator → **Wissen** → „GitHub-Repos nutzen“ einschalten → Repos eintragen, eins pro Zeile: `Besitzer/Repo`, die GitHub-Adresse oder mit Branch `Besitzer/Repo@dev`. **Speichern.**
2. Für private Repos auf GitHub einen **Fine-grained-Token** anlegen (*Settings → Developer settings → Fine-grained tokens*): nur die gewünschten Repos, Berechtigung **Contents: Read-only**. Im Konfigurator unter **Zugangsdaten** bei `GITHUB_TOKEN` einfügen → **Setzen**.
3. **Repos jetzt laden**, dann **Wissen prüfen**.

Der Bot lädt die Repos als Kopie neben die `config.yaml` (`wissen-cache/`, nur Textdateien, ohne versteckte Ordner, `.env`- und Schlüsseldateien) und prüft im eingestellten Abstand (Standard 60 min), ob es Neues gibt. Der Token bleibt beim Bot – Claude Code bekommt ihn nie. Die Prüfung warnt nur bei einem klassischen Token mit Schreib-Scope; die Rechte eines Fine-grained-Tokens kann GitHub nicht abfragen lassen – dort einfach nur „Contents: Read-only“ vergeben.

Technik bei der **API**: Der Bot gibt dem Modell die drei Lese-Werkzeuge `list_files`, `search`, `read_file` und führt sie selbst aus (höchstens 6 Schritte pro Antwort, unter *Wissen → Erweitert* einstellbar). Jeder Schritt kostet Tokens und zählt aufs Tagesbudget.

Technik beim **Abo**: Pro Antwort erzeugt der Bot eine temporäre MCP-Konfiguration für den mitgelieferten Lese-Server `wissen_ordner.py` (Ordner und geladene Repos), startet `claude -p` mit genau diesen Werkzeugen und löscht die Datei danach. An Claude Code werden keine Schlüssel oder Tokens aus der Umgebung weitergegeben. Antworten mit Nachschlagen dauern länger (10–30 s) und verbrauchen mehr Abo-Kontingent.

Der Konfigurator sucht nichts automatisch auf deinem Rechner – alle Angaben trägst du selbst ein. (Unter *Wissen → Erweitert* gibt es zusätzlich eine Anbindung an einen eigenen MediaVault-Server; die ist nur für dessen Betreiber gedacht.)

## Verlauf zurücksetzen und speichern

Damit der Kontext (und damit Kosten bzw. Kontingent) nicht immer weiter wächst:

- **`!reset`** setzt den Verlauf zurück. Der Partner-Bot macht automatisch mit und bestätigt ebenfalls.
- **Speichern** (Konfigurator → *Persönlichkeit & Kontext* → „Vor !reset zusammenfassen und speichern“): Vorher fasst die KI den Verlauf zusammen und legt ihn als Markdown in `verlauf\` ab – jeder Bot nach seiner eigenen Einstellung auf seinem eigenen Rechner. Auf Wunsch bleibt die Kurzfassung als Startkontext erhalten.
- Ohne Speichern antwortet der Bot nur „🤷 Mir egal – Verlauf vergessen, nichts gespeichert.“ (Text änderbar).
- **Dialoge einzeln:** `!speichern` legt den letzten Dialog in `verlauf\dialoge\` ab. Mit „Jeden Dialog automatisch speichern“ passiert das am Ende jedes Dialogs von selbst.
- **Chat löschen** (Schalter „Nach !reset den Chat im Kanal löschen“): Nachdem beide Bots gesichert haben, löscht der Bot alle Nachrichten im Kanal bis zum Reset – angeheftete bleiben. Er wartet dafür auf die Bestätigung des Partner-Bots (höchstens 3 Minuten). Braucht das Discord-Recht **Nachrichten verwalten** für die Rolle des Bots; ohne das löscht er nur seine eigenen Nachrichten. Es reicht, das in einem der beiden Bots einzuschalten.
- Der Reset-Stand bleibt auch nach einem Neustart erhalten.

## Varianten und Updates

| | Windows-Programm | Python-Variante |
|---|---|---|
| Paket | `CortexQuorumBot-Windows.zip` | `CortexQuorumBot.zip` |
| Voraussetzung | nichts (Windows 10/11) | Python 3.11+ |
| Konfigurator | eigenes Fenster (WebView2) | im Browser |
| Start | `CortexQuorumBot.exe` / `konfigurator.bat`, Bot: `start.bat` | `konfigurator.bat`, Bot: `start.bat` |

**Hinweis zum Windows-Programm:** Die exe ist nicht digital signiert. Windows SmartScreen zeigt beim ersten Start „Der Computer wurde durch Windows geschützt“ → **Weitere Informationen** → **Trotzdem ausführen**. Manche Virenscanner melden mit PyInstaller gebaute Programme fälschlich. Wer das nicht möchte, nimmt die Python-Variante – gleicher Funktionsumfang, Quellcode offen. Für die Abo-Variante muss in beiden Fällen Claude Code installiert sein.

**Updates** (Konfigurator → **Updates**): *manuell* (nur per Knopf, Standard – kein Online-Check beim Start), *hinweis* (beim Start prüfen und anzeigen) oder *automatisch* (Bot und Konfigurator installieren beim Start selbst und starten neu). Geladen wird nur aus dem offiziellen Release-Repo, die SHA-256-Prüfsumme wird geprüft. `config.yaml`, `.env` und alle Einstellungen bleiben unangetastet; der alte Stand landet in `.update-sicherung\` und lässt sich per Knopf **Vorige Version** zurückholen. Vor dem Update den Bot beenden. In einem Ordner mit `.git` (Entwicklung) wird nie automatisch installiert.

> Von v0.4.0 oder älter einmalig von Hand umsteigen: neues Paket entpacken, `config.yaml`, `.env` und ggf. `config.*.json` aus dem alten Ordner hineinkopieren. Ab v0.5.0 geht es über den Knopf.

## Profilbild des Bots

Konfigurator → **Bot & Personen** → **Bild wählen …** setzt das Profilbild des Bots direkt bei Discord (PNG, JPG, GIF, WebP, max. 8 MB). Discord erlaubt nur wenige Wechsel kurz hintereinander. Alternativ wie bisher im Developer Portal unter *Bot → Icon*.

## Voice-Join-Melder

Eigenständiges Modul (`voice_notifier.py`), läuft **ohne KI**: Betritt jemand einen überwachten Sprachraum (oder wechselt hinein), postet der Bot in den zugeordneten Textkanal:

> 🎙️ Max ist in 🔊 Lounge.

- Im Konfigurator unter **Voice-Melder** einschalten und Paare eintragen: `Sprachraum-ID = Textkanal-ID` (eine Zeile pro Paar, mehrere Server möglich).
- Verlassen wird nicht gemeldet, Bots werden ignoriert, Pings (@everyone, @here, Nutzer) werden nie ausgelöst.
- Raus und gleich wieder rein wird innerhalb der Pause (Standard 60 s, pro Person und Raum) nicht erneut gemeldet.
- Nachricht als Vorlage: `{name}`, `{channel}` (Sprachraum als Link), `{channel_name}`.
- Fehlt der Textkanal oder das Schreibrecht, wird nur ins Log geschrieben – der Bot läuft weiter.
- Per Chat schaltbar: `!set voice_notifier.enabled nein` bzw. `/nova set`.

> ⚠️ **Pro Server darf der Melder nur in EINEM Bot aktiv sein** – sonst kommt jede Meldung doppelt (z. B. nicht bei Nova *und* Kai einschalten). Für einzelne Server abschaltbar unter „Erweitert → Server ohne Melder“.
> Der Bot braucht im Ziel-Textkanal **Kanal ansehen** und **Nachrichten senden**; den Sprachraum muss er sehen können.

Das Modul ist unabhängig vom Rest des Bots und lässt sich in jeden discord.py-Bot einhängen: `attach_voice_notifier(client, {"enabled": True, "watch": {VOICE_ID: TEXT_ID}})`.

## Text-Befehle (nur der Besitzer)

| Befehl | Wirkung |
|---|---|
| `@Nova <Frage>` | Bot antwortet dir |
| `!dialog [runden] <thema>` | Bot eröffnet einen Dialog mit dem Partner-Bot (alternativ: beide Bots in einer Nachricht erwähnen) |
| `!stopp` | beendet einen laufenden Dialog (darf **jeder** Mensch im Kanal) |
| `!status` | aktuelle Einstellungen und Budget |
| `!set <schlüssel> <wert>` | Einstellung live ändern, z. B. `!set llm.temperature 0.4` |
| `!unset <schlüssel>` | zurück auf den Wert aus der `config.yaml` |
| `!reset` | Verlauf zurücksetzen – bei **beiden** Bots. Je nach Einstellung vorher zusammenfassen und speichern |
| `!speichern` | Letzten Dialog als Markdown-Datei speichern (ohne KI, kostet nichts) |
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

- Ein Dialog startet **nur durch einen Menschen**: `!dialog`, `/name dialog` oder indem der Besitzer **beide Bots in einer Nachricht erwähnt** (`@MeinBot @PartnerBot was meint ihr zu …?`). Von selbst fangen die Bots nie an.
- Erwähnt ein **anderer Mensch** den Bot, antwortet er nur mit einer kurzen Standardantwort ohne KI (Text im Konfigurator unter *Leitplanken* änderbar, höchstens alle 10 min pro Person). Erwähnt der Besitzer des Partner-Bots beide Bots, bleibt dieser Bot still – der Partner eröffnet.
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
- `checks.py` + `pruefen.py`/`pruefen.bat` – Selbsttest (auch im Konfigurator)
- `voice_notifier.py` – Voice-Join-Melder, eigenständig und ohne KI
- `knowledge.py` – Wissensquellen (lokale Ordner, optional eigener MediaVault; nur lesend) für die Abo-Variante
- `wissen_ordner.py` – Lese-Server für lokale Wissensordner (MCP, ohne Zusatzpakete)
- `verlauf.py` – Verlauf zurücksetzen, zusammenfassen und speichern, Dialoge speichern
- `wissen_github.py` – GitHub-Repos laden und aktuell halten (Zip über die API, kein git nötig)
- `updater.py` + `version.py` – Updates aus dem Release-Repo (Prüfsumme, Sicherung, Zurücksetzen)
- `quorumbot.py` – Einstieg der Windows-exe; `tools/build_exe.py` baut sie (PyInstaller, nur unter Windows)
- `settings_schema.py` – alle Einstellungen mit Typ, Grenzen und Hilfetext (gemeinsam für Konfigurator, `!set` und Slash)
- `tests/` – `python -m pytest tests`

## Nächste Stufen

1. Vault- und MediaVault-Zugriff als Werkzeuge (nur freigegebene Ordner)
2. Sprachausgabe im Voicechannel (Piper)
3. Spracheingabe (faster-whisper)
