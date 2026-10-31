# Cortex QuorumBot – Installation Schritt für Schritt

Dauer: etwa 15 Minuten pro Person. Jeder Mensch in der Runde richtet **seinen eigenen** Bot auf **seinem eigenen** Rechner ein. Diese Anleitung ist für Windows; unter macOS/Linux statt der `.bat`-Dateien die jeweiligen `python …`-Befehle verwenden.

> **Kurzfassung:** Zip entpacken → `CortexQuorumBot.exe` (Windows-Programm) bzw. `konfigurator.bat` (Python-Variante) doppelklicken → dem Assistenten folgen → Test grün → `start.bat`.
>
> **Welche Variante?** Das **Windows-Programm** braucht kein Python und öffnet den Konfigurator im eigenen Fenster. Es ist nicht signiert – Windows warnt beim ersten Start (siehe Schritt 3). Die **Python-Variante** braucht Python, ist dafür offen einsehbar. Beide können sich selbst aktualisieren.

---

## 1. Was du brauchst

- [ ] Ein **Discord-Konto** und einen **Server**, auf dem du Bots hinzufügen darfst. Für den ersten Test am besten einen eigenen, leeren Server anlegen (in Discord links auf **+** → **Eigenen erstellen**).
- [ ] Nur für die Python-Variante: **Python 3.11 oder neuer** – <https://www.python.org/downloads/>. Beim Setup unbedingt **„Add python.exe to PATH“** anhaken.
- [ ] Einen **Modellzugang**, eins davon:
    - **Anthropic-API-Key** – <https://console.anthropic.com/settings/keys> (kostet pro Nutzung), oder
    - **Claude-Abo** (Pro/Max) mit **Claude Code** – <https://claude.com/claude-code>, oder
    - **Ollama** lokal – <https://ollama.com>

**Prüfen (nur Python-Variante):** Eingabeaufforderung öffnen (Windows-Taste, `cmd`), `python --version` eingeben. Es muss `Python 3.11` oder höher erscheinen.

## 2. Herunterladen und entpacken

1. Neueste Version laden – **[⬇ Windows-Programm](https://github.com/LowKI2/cortex-quorumbot-release/releases/latest/download/CortexQuorumBot-Windows.zip)** oder **[⬇ Python-Variante](https://github.com/LowKI2/cortex-quorumbot-release/releases/latest/download/CortexQuorumBot.zip)** (alle Versionen: <https://github.com/LowKI2/cortex-quorumbot-release/releases>).
2. Entpacken, z. B. nach `Dokumente\Cortex-QuorumBot`. Nicht in einen Ordner, der automatisch in die Cloud synchronisiert wird – dort landen später deine Zugangsdaten.

## 3. Konfigurator starten

**Windows-Programm:** `CortexQuorumBot.exe` doppelklicken. Beim ersten Mal zeigt Windows „Der Computer wurde durch Windows geschützt“ → **Weitere Informationen** → **Trotzdem ausführen** (das Programm ist nicht digital signiert). Der Konfigurator öffnet sich in einem eigenen Fenster.

**Python-Variante:** `konfigurator.bat` doppelklicken. Beim ersten Mal werden die Python-Pakete installiert (1–2 Minuten). Danach öffnet sich der Browser mit dem Konfigurator.

Der **Einrichtungsassistent** startet automatisch.

> Öffnet sich kein Browser: <http://127.0.0.1:8765> von Hand aufrufen. Das Fenster mit der schwarzen Konsole offen lassen, solange du konfigurierst.

## 4. Der Assistent

### Schritt 1 – Start
Wähle, womit dein Bot denkt: **Anthropic-API**, **Claude-Abo** oder **Lokal / anderes**.

### Schritt 2 – Discord-Bot anlegen
1. <https://discord.com/developers/applications> → **New Application** → Name eingeben (z. B. „Nova“) → **Create**.
2. Links **Bot** → bei **Privileged Gateway Intents** den **Message Content Intent** einschalten → **Save Changes**.
3. Auf derselben Seite **Reset Token** → bestätigen → **Copy**. Der Token wird nur einmal angezeigt.
4. Im Assistenten in das Feld **Discord-Token** einfügen → **Setzen**.

**Prüfen:** Der Assistent zeigt „Bot erkannt“, den Namen deines Bots und **„Message Content an“**. Steht dort „aus“, Punkt 2 wiederholen und **erneut prüfen** klicken.

### Schritt 3 – Modell
- **API:** In der Anthropic-Konsole unter **API Keys** einen Key erstellen und unter **Limits** ein Ausgabelimit setzen. Key einfügen → **Setzen**. Modell: `claude-sonnet-5-5` ist ein guter Standard.
- **Abo:** Claude Code installieren. Einmal eine Eingabeaufforderung öffnen, `claude` eingeben und einloggen. Dann testen mit `claude -p "sag hallo"` – es muss eine Antwort kommen. Im Assistenten **Prüfen** klicken. Modell: `sonnet`. **Den API-Key-Platz leer lassen.**
- **Lokal:** Ollama starten, Modell laden (`ollama pull llama3.3`), Base-URL `http://localhost:11434/v1` und Modellname eintragen.

### Schritt 4 – Einladen und IDs
1. **Einladungslink öffnen** → deinen Server wählen → **Autorisieren**. Der Bot erscheint offline in der Mitgliederliste – das ist richtig, er läuft ja noch nicht.
2. In Discord: **Einstellungen (Zahnrad) → Erweitert → Entwicklermodus** einschalten.
3. Rechtsklick auf **deinen eigenen Namen** → **ID kopieren** → ins Feld „Deine User-ID“.
4. Rechtsklick auf den **Bot der anderen Person** → **ID kopieren** → „User-ID des anderen Bots“. Hat sie noch keinen: leer lassen, später im Konfigurator nachtragen.
5. Rechtsklick auf **euren Kanal** → **ID kopieren** → „Kanal-ID(s)“.

> Häufigster Fehler: Bei Punkt 4 die ID der **Person** statt die ihres **Bots** kopiert. Der Test meldet das.

### Schritt 5 – Namen und Persönlichkeit
Namen eintragen und die Persönlichkeit frei beschreiben. Die Leitplanken gelten unabhängig davon.

### Schritt 6 – Sprache (optional, Beta)
Nur wenn der Bot im Sprachraum sprechen und zuhören soll – geht auch später. Sonst „Nur Text“ und weiter.
1. **FFmpeg** installieren: Eingabeaufforderung öffnen, `winget install Gyan.FFmpeg`, danach den Konfigurator schließen und neu starten.
2. **Spracherkennung:** Groq-Konto anlegen, unter <https://console.groq.com/keys> einen Key erstellen, im Assistenten setzen.
3. **Stimme:** Im <https://portal.azure.com> „Speech-Dienst“ suchen → Erstellen → Region z. B. **West Europe**, Tarif **Free F0** (Germany West Central nimmt teils keine Neukunden an) – die Region im Assistenten unter „Azure-Region“ passend eintragen (`westeurope`) → unter **Schlüssel und Endpunkt** „Schlüssel 1“ kopieren und setzen. (Alternativ Piper lokal, ElevenLabs oder OpenAI.)
4. **Hörprobe** klicken – die Stimme ist direkt zu hören.

### Schritt 7 – Test
**Test starten.** Geprüft werden:

| Prüfung | Was sie bedeutet |
|---|---|
| Python, Pakete | Installation vollständig |
| Konfiguration | Pflichtfelder und Grenzwerte in Ordnung |
| Discord-Token | Token gültig, Bot gefunden |
| Message Content Intent | Bot darf Nachrichtentexte lesen |
| Application-ID | passt zum Token (für den Einladungslink) |
| Server | Bot ist mindestens auf einem Server |
| Kanal | Bot sieht den eingetragenen Kanal |
| Deine User-ID / Partner-Bot | IDs zeigen auf die richtigen Konten |
| API-Key / Claude Code / Modell-Server | Modellzugang vorhanden |
| Testanfrage | echte Antwort vom Modell (kostet minimal bzw. etwas Abo-Kontingent) |
| Sprach-Pakete, Opus, FFmpeg, Keys | nur wenn Sprache aktiv |
| Rundlauf Stimme → Erkennung | Bot spricht einen Satz, die Erkennung muss ihn verstehen |

Bei jedem Fehler steht direkt darunter, was zu tun ist. Wenn unten **„Startklar“** steht: **Bot jetzt starten**.

## 5. Funktionstest in Discord

1. Im Kanal schreiben: `@Nova hallo` (dein Bot-Name). → Der Bot tippt kurz und antwortet.
2. Schreibt **jemand anderes** `@Nova hallo`, darf der Bot **nicht** antworten. → Leitplanke „nur Besitzer“ funktioniert.
3. `/nova status` eingeben. → Nur du siehst Einstellungen und Verbrauch.
4. Sobald beide Bots laufen: `!dialog 4 Testthema`. → Die Bots reden 4 Runden und ziehen am Ende ein Fazit. Die letzte Nachricht endet mit „Runde 4/4 · Ende“.
   Alternativ: `@DeinBot @PartnerBot Testthema` – startet einen Dialog mit der Standard-Rundenzahl.
   Wichtig: In **beiden** Bots muss die User-ID des jeweils anderen Bots unter *Bot & Personen → User-ID(s) des Partner-Bots* stehen.
5. Nochmal `!dialog 10 Testthema`, nach zwei Antworten `!stopp` schreiben. → Beide hören auf.

Alle fünf Punkte erfüllt: Die Runde ist einsatzbereit.

## Optional: Sprache testen (Beta)

1. In einen Sprachraum gehen. → Dein Bot kommt nach (grüner Rand, wenn er spricht).
2. „Cortex, hörst du mich?“ sagen (dein Bot-Name). → Im Textkanal erscheint „🎙️ Dein Name: …“ und der Bot antwortet gesprochen.
3. Ohne Rufnamen etwas sagen. → Text erscheint, der Bot bleibt still.
4. Während er spricht, selbst reden. → Er hört auf.
5. Am Handy im Textkanal eine Sprachnachricht schicken. → Er antwortet.

## Optional: Wissen

Der Bot kann in **lokalen Ordnern** und **GitHub-Repos** nachschlagen – nur lesend, mit Abo und mit API. Bei der API kostet Nachschlagen zusätzliche Tokens.

1. Konfigurator → Bereich **Wissen** → „Lokale Ordner nutzen“ einschalten.
2. **Ordner wählen …** → Ordner aussuchen → **Speichern**. Am besten einen eigenen Wissensordner nehmen, nicht ganz „Dokumente“.
3. **Wissen prüfen** – alles grün? Dann Bot neu starten.

**GitHub-Repos** (auch mehrere, auch private):

1. „GitHub-Repos nutzen“ einschalten, Repos eintragen – eins pro Zeile, z. B. `BBZGames/Bratratz_lore` – **Speichern**.
2. Nur für private Repos: auf GitHub unter *Settings → Developer settings → Fine-grained tokens* einen Token anlegen – nur diese Repos, **Contents: Read-only** – und im Konfigurator bei `GITHUB_TOKEN` einfügen → **Setzen**.
3. **Repos jetzt laden** → **Wissen prüfen**. Der laufende Bot holt danach selbst neue Stände (Standard: stündlich).

> Alles, was der Bot lesen kann, kann er im Kanal auch erzählen. Versteckte Ordner, `.env`, Schlüssel- und Passwortdateien liest er nie.

## Updates

Konfigurator → **Updates** → **Nach Updates suchen** → **installieren**. Vorher den Bot beenden. Deine Einstellungen und Schlüssel bleiben erhalten, der Konfigurator startet danach neu. Bei Problemen: **Vorige Version**. Unter „Nach Updates suchen“ lässt sich einstellen, ob nur per Knopf (Standard), mit Hinweis beim Start oder automatisch aktualisiert wird.

## Optional: Profilbild

Konfigurator → **Bot & Personen** → **Bild wählen …** – das Bild wird sofort bei Discord gesetzt.

## Optional: Voice-Join-Melder

Der Bot meldet im Textkanal, wenn jemand einen Sprachraum betritt – ohne KI, kostet nichts.

1. In Discord Rechtsklick auf den Sprachraum → **ID kopieren**, dann Rechtsklick auf den Textkanal für die Meldungen → **ID kopieren**.
2. Konfigurator → **Voice-Melder** → einschalten → `Sprachraum-ID = Textkanal-ID` eintragen → **Speichern**.
3. **Vollständiger Test** prüft, ob der Bot beide Kanäle sieht.
4. **Test in Discord:** in den Sprachraum gehen → genau eine Meldung. Raus und sofort wieder rein → keine zweite Meldung. Ein Bot tritt bei → keine Meldung. Anderer Sprachraum → keine Meldung.

> Nur in **einem** Bot pro Server einschalten (also nicht bei beiden Bots der Runde), sonst kommt jede Meldung doppelt.

## 6. Im Alltag

- **Starten:** `start.bat` doppelklicken. Läuft, solange das Fenster offen ist.
- **Einstellungen ändern:** `konfigurator.bat` – auch während der Bot läuft. Änderungen gelten ab der nächsten Nachricht. Nur ein neuer Discord-Token braucht einen Neustart.
- **Prüfen:** `pruefen.bat` macht denselben Test wie der Assistent, ohne Browser.
- **Update:** neue Version laden ([⬇ CortexQuorumBot.zip](https://github.com/LowKI2/cortex-quorumbot-release/releases/latest/download/CortexQuorumBot.zip)), entpacken und `config.yaml`, `.env` und `config.overrides.json` aus dem alten Ordner hineinkopieren.

## 7. Wenn etwas nicht geht

| Problem | Lösung |
|---|---|
| `python` wird nicht gefunden | Python neu installieren, „Add to PATH“ anhaken, Rechner neu anmelden. |
| Bot ist offline | `start.bat` läuft nicht oder wurde geschlossen. Fenster auf Fehlermeldungen prüfen. |
| Bot antwortet nicht | Mit `@Name` angesprochen? Richtiger Kanal? Deine User-ID korrekt? `pruefen.bat` ausführen. |
| Slash-Befehle fehlen | Bot mit dem Einladungslink aus dem Konfigurator **neu** einladen (braucht `applications.commands`). Discord-App einmal neu laden (Strg+R). |
| „setzt aus: Stundenlimit“ | Budget erreicht – im Konfigurator unter Leitplanken erhöhen oder warten. |
| Abo: „claude -p fehlgeschlagen“ | In der Eingabeaufforderung `claude` starten und neu einloggen. Kontingent prüfen. |
| Voice-Melder meldet nichts | Ist er an? Stimmt die Reihenfolge (erst Sprachraum, dann Textkanal)? „Vollständiger Test“ zeigt, ob der Bot beide Kanäle sieht. Meldet ein anderer Bot schon? |
| Meldungen doppelt | Der Melder ist in zwei Bots aktiv – in einem ausschalten. |
| Bot spricht nicht | FFmpeg installiert? Konfigurator → „Vollständiger Test“. Ist „Antworten im Sprachraum sprechen“ an? |
| Bot reagiert nicht auf Sprache | Rufnamen sagen. Im Textkanal prüfen, wie dein Satz erkannt wurde – abweichende Schreibweise unter „Weitere Rufnamen“ eintragen. Klappt Live nicht: Sprachnachricht schicken. |
| Bot antwortet sich selbst | Kopfhörer benutzen oder „Unterbrechen“ ausschalten. |
| Token versehentlich geteilt | Sofort im Developer Portal **Reset Token**, neuen Token im Konfigurator setzen, Bot neu starten. |

## ⚠️ Sicherheit

- Token und API-Key stehen nur in der `.env` in diesem Ordner. Die Datei niemals weitergeben, hochladen oder in einen Chat kopieren.
- Der Bot schickt die letzten Nachrichten im Kanal an das gewählte Modell. Alle im Kanal sollten das wissen.
- Den Konfigurator nicht über das Netzwerk erreichbar machen.
