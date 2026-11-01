# Datenschutz – Cortex QuorumBot

> **Hinweis:** Dieser Text beschreibt sachlich, welche Daten die Software verarbeitet, und enthält eine Vorlage für Betreiber. Er ist **keine Rechtsberatung** und ersetzt keine Prüfung durch eine fachkundige Person. Stand: Version 0.9.3.

Cortex QuorumBot ist eine Software, die **du selbst auf deinem Rechner betreibst**. Der Hersteller (BZi Studio) betreibt keinen Server für den Bot und erhält **keine** Daten: keine Telemetrie, keine Nutzungsstatistik, keine Werbung. Verantwortlich im Sinne der DSGVO ist, **wer einen Bot betreibt** und in einen Discord-Server einlädt.

- **Teil A** erklärt, welche Daten wohin fließen – für dich als Betreiber.
- **Teil B** ist eine **Vorlage**, die du ausfüllst und für die Menschen in deinem Discord-Server sichtbar machst (z. B. als angeheftete Nachricht oder in einem Info-Kanal).

---

## Teil A – Was die Software mit Daten macht

### Datenflüsse

| Was | Wohin | Wann |
|---|---|---|
| Nachrichten in den freigegebenen Kanälen (Text, Anzeigename, Zeitpunkt) | wird vom Bot über Discord **gelesen** | laufend, solange der Bot läuft (Discord-Recht „Message Content“) |
| Die letzten Nachrichten des Kanals (Standard 30) samt Anzeigenamen, die Persönlichkeit des Bots und ggf. eine Kurzfassung früherer Gespräche | an den gewählten **KI-Anbieter** | nur wenn der Bot antwortet oder einen Verlauf zusammenfasst |
| Nachrichten **anderer Menschen** im Kanal | gehören zu diesem Verlauf | abschaltbar: „Nachrichten anderer Menschen an die KI senden“ |
| Inhalte aus freigegebenen Ordnern, GitHub-Repos oder MediaVault | an den KI-Anbieter | nur die Stellen, die die KI beim Antworten nachschlägt |
| **Sprache** (nur wenn eingeschaltet): Ton **nur des Besitzers** | an den Dienst für Spracherkennung | während der Besitzer im Sprachraum spricht; der Ton anderer Teilnehmer wird verworfen, bevor er entschlüsselt wird |
| Antworttext des Bots | an den Dienst für die Stimme | wenn der Bot im Sprachraum spricht |
| Erkannter Text des Besitzers („🎙️ Name: …“) | als Nachricht in den Kanal | abschaltbar |
| Sprachraum-Beitritte (Voice-Melder, nur wenn eingeschaltet) | als kurze Statusmeldung in den Kanal | wird beim Verlassen gelöscht (abschaltbar) |
| GitHub-Token, Repo-Namen | an GitHub | beim Laden der Repos (nur wenn GitHub-Wissen an ist) |
| IP-Adresse | an GitHub | nur bei „Nach Updates suchen“ (Standard: manuell) |

**KI-Anbieter je nach Einstellung**

| Einstellung | Anbieter / Ort | Zu beachten |
|---|---|---|
| Anthropic-API | Anthropic (USA) | Bedingungen des API-Kontos des Betreibers |
| Claude-Abo | Anthropic über Claude Code (USA) | Es gelten die Bedingungen und Datenschutz-Einstellungen des Claude-Kontos des Betreibers – dort prüfen, ob Chats für Training verwendet werden dürfen |
| OpenAI-kompatibel | je nach Server, z. B. OpenAI (USA) – oder **Ollama lokal: Daten bleiben auf dem Rechner** | |

**Sprachdienste je nach Einstellung**

| Zweck | Anbieter / Ort |
|---|---|
| Spracherkennung | Groq (USA), OpenAI (USA), Deepgram (USA) – oder **lokal (faster-whisper), bleibt auf dem Rechner** |
| Stimme | Azure Speech (Microsoft, in der gewählten Region, z. B. EU), ElevenLabs, OpenAI (USA) – oder **Piper lokal, bleibt auf dem Rechner** |

Für Anbieter außerhalb der EU gelten deren Datenschutzbestimmungen und Vereinbarungen zur Datenübermittlung. Betreiber sollten diese bei den jeweiligen Anbietern nachlesen.

### Auf dem Rechner des Betreibers gespeichert

| Datei / Ordner | Inhalt | Löschen |
|---|---|---|
| `config.yaml` | Einstellungen, Discord-IDs, Namen | Datei löschen |
| `.env` | Zugangsdaten (Discord-Token, Keys) – **im Klartext** | Datei löschen, Token/Keys beim Anbieter widerrufen |
| `config.budget.json` | Token-Zähler des Tages | wird täglich zurückgesetzt |
| `config.status.json` | Lebenszeichen des Bots (Zeit, Bot-Name) | Datei löschen |
| `config.kontext.json` | Stand des letzten `!reset`, ggf. Kurzfassung des Gesprächs | Datei löschen |
| `verlauf\` | gespeicherte Zusammenfassungen und Dialoge – **enthalten Chatinhalte und Namen** | Ordner/Dateien löschen |
| `wissen-cache\` | Kopien der freigegebenen GitHub-Repos | Ordner löschen |
| `.update-sicherung\` | Programmstand vor dem letzten Update (keine Chatdaten) | Ordner löschen |

Ein Protokoll erscheint nur im Fenster des Bots und wird nicht in eine Datei geschrieben. Was in Discord gepostet wurde, liegt nach den Regeln von Discord bei Discord; `!reset` mit „Chat löschen“ entfernt die Nachrichten im Kanal (angeheftete bleiben).

### Datensparsam einstellen (empfohlen für öffentliche Server)

- **Eigenen Kanal** für den Bot anlegen und nur diesen unter „Erlaubte Kanal-IDs“ eintragen.
- „Nachrichten anderer Menschen an die KI senden“ **aus**.
- „Mitgelesene Nachrichten“ klein halten (z. B. 10–15).
- Wissen nur mit Inhalten, die öffentlich sein dürfen – alles, was der Bot lesen kann, kann er im Kanal erzählen.
- Sprache nur mit lokalen Diensten (faster-whisper, Piper) oder EU-Region bei Azure.
- „Vor !reset zusammenfassen und speichern“ und „Jeden Dialog automatisch speichern“ nur, wenn wirklich gebraucht.
- Regelmäßig `!reset` (mit „Chat löschen“), damit Verläufe nicht unnötig lange stehen.
- Den Datenschutzhinweis aus Teil B im Server sichtbar machen.

---

## Teil B – Vorlage: Datenschutzhinweis für deinen Discord-Server

> Ausfüllen: alles in **[eckigen Klammern]**. Nicht Zutreffendes streichen. Rechtsgrundlage und Formulierungen bitte selbst prüfen (lassen).

**Datenschutzhinweis zum Bot „[BOT-NAME]“**

**Wer ist verantwortlich?**
[Vor- und Nachname], [Anschrift], E-Mail: [E-Mail-Adresse]

**Was macht der Bot?**
In diesem Server läuft der Discord-Bot „[BOT-NAME]“ (Software: Cortex QuorumBot). Er liest Nachrichten im Kanal **#[KANALNAME]** mit und antwortet nur [BESITZER-NAME]. Andere Personen erhalten auf Erwähnungen nur eine automatische Standardantwort.

**Welche Daten werden verarbeitet?**
- Nachrichten im Kanal #[KANALNAME] mit Anzeigename und Zeitpunkt.
- [Nur wenn „Nachrichten anderer Menschen an die KI senden“ an ist:] Auch Nachrichten anderer Personen in diesem Kanal werden als Gesprächszusammenhang an den KI-Dienst übermittelt.
- [Nur bei Sprache:] Im Sprachraum wird ausschließlich die Stimme von [BESITZER-NAME] verarbeitet; Stimmen anderer Teilnehmer werden nicht ausgewertet.
- [Nur beim Voice-Melder:] Das Betreten bestimmter Sprachräume wird als Statusmeldung angezeigt und beim Verlassen wieder gelöscht.

**An wen werden Daten übermittelt?**
- KI-Dienst: [z. B. Anthropic PBC, USA / lokal ohne Übermittlung]
- [Nur bei Sprache:] Spracherkennung: [z. B. Groq Inc., USA / lokal]; Stimme: [z. B. Microsoft Azure, Region EU / lokal]
- Discord selbst verarbeitet alle Nachrichten nach seinen eigenen Datenschutzbestimmungen.
Bei Diensten außerhalb der EU erfolgt eine Übermittlung in ein Drittland; Grundlage ist [z. B. EU-US Data Privacy Framework / Standardvertragsklauseln des Anbieters – bitte beim Anbieter prüfen].

**Zweck und Rechtsgrundlage**
Zweck ist die Unterhaltung mit dem Bot in diesem Server. Rechtsgrundlage: [z. B. Art. 6 Abs. 1 lit. f DSGVO – berechtigtes Interesse am Betrieb des Bots in einem dafür vorgesehenen Kanal; bitte prüfen].

**Speicherdauer**
Nachrichten bleiben in Discord, bis sie gelöscht werden. Der Verlauf wird [regelmäßig / bei Bedarf] mit `!reset` zurückgesetzt und der Chat dabei [gelöscht / nicht gelöscht]. [Nur wenn Speichern an ist:] Zusammenfassungen bzw. Dialoge werden lokal beim Betreiber gespeichert und nach [ZEITRAUM] gelöscht.

**Deine Rechte**
Du hast das Recht auf Auskunft, Berichtigung, Löschung, Einschränkung der Verarbeitung und Widerspruch sowie das Recht, dich bei einer Datenschutz-Aufsichtsbehörde zu beschweren. Wende dich dafür an [E-Mail-Adresse]. Wenn du nicht möchtest, dass deine Nachrichten verarbeitet werden, schreibe bitte nicht im Kanal #[KANALNAME].
