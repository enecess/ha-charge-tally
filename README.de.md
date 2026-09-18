# Charge Tally

[English](README.md) · [简体中文](README.zh-CN.md) · **Deutsch** · [Français](README.fr.md) · [Polski](README.pl.md) · [Italiano](README.it.md)

Behalte Ladeenergie und Kosten in Home Assistant im Blick. Charge Tally erstellt aus deinen vorhandenen Energie- oder Leistungssensoren Ladeeinträge. Jeden Eintrag kannst du einem Fahrzeug, einer Person oder einem frei gewählten Namen zuordnen.

- Nutze einen festen Preis, einen Preissensor oder unterschiedliche Preise je nach Tageszeit.
- Lass Ladevorgänge automatisch erkennen oder starte und beende Einträge selbst.
- Sieh Energie und Kosten pro Identität für heute, diesen Monat und dieses Jahr.
- Trage frühere Ladevorgänge nach und korrigiere ihre Angaben.
- Zeige alles auf einer Dashboard-Karte an und bediene es dort.

> Platzhalter für einen Screenshot: Dashboard-Karte mit Ladestatus, Identitätsauswahl und Statistik.

## Bevor du beginnst

Du brauchst Home Assistant und mindestens einen Sensor, der den Stromkreis deiner Ladestation misst. Charge Tally zeichnet Ladevorgänge auf; es schaltet dein Ladegerät nicht ein oder aus.

Erfordert **Home Assistant 2025.3.4 oder neuer**. Getestet mit 2025.3.4, 2025.12.4, 2026.3.4 und 2026.9.1.

| Vorhandene Sensoren | Auswahl bei der Einrichtung |
| --- | --- |
| Fortlaufender Energiezähler in Wh, kWh oder MWh | **Nur Energie** |
| Leistung in W oder kW | **Nur Leistung** — Home Assistant berechnet die verbrauchte Energie |
| Beides | **Energie und Leistung** — Energie misst den Verbrauch, Leistung erkennt Ladevorgänge |

Ein fortlaufender Energiezähler liefert einen normalerweise steigenden Zählerstand, nicht nur den Verbrauch der letzten Stunde. Die automatische Erkennung benötigt einen Leistungssensor.

## Mit HACS installieren

1. Öffne **HACS** und wähle im Menü **Benutzerdefinierte Repositories**.
2. Trage `https://github.com/enecess/ha-charge-tally` ein und wähle **Integration**.
3. Suche in HACS nach **Charge Tally** und lade es herunter.
4. Starte Home Assistant neu.
5. Öffne **Einstellungen → Geräte & Dienste → Integration hinzufügen** und suche nach **Charge Tally**.

Für eine manuelle Installation kopierst du den Ordner `custom_components/charge_tally` aus dem Repository in den Ordner `custom_components` deiner Home-Assistant-Installation und startest anschließend neu.

## Den ersten Ladepunkt einrichten

1. **Wähle deine Währung.** Sie gilt für alle Ladepunkte. Vor dem ersten Ladepunkt kannst du sie über **Konfigurieren** auf der Integrationsseite ändern, sofern keine Abrechnungsdaten gespeichert sind. Ein Ladepunkt sperrt die Währung, auch vor dem ersten Ladevorgang oder nach dem Entfernen des Punkts. Identitäten allein sperren sie nicht. Historische Beträge werden nicht automatisch umgerechnet oder neu berechnet.
2. **Gib dem Ladepunkt einen Namen**, wähle die Art deiner Sensoren und anschließend die Sensoren selbst.
3. Mit einem Leistungssensor kannst du die **automatische Ladeerkennung** aktivieren. Lege fest, welche Leistung wie lange anliegen muss, bevor ein Ladevorgang beginnt oder endet. Die Endschwelle muss unter der Startschwelle liegen.
4. **Lege deinen Strompreis fest**, wie in der folgenden Tabelle beschrieben.
5. Wähle die gewünschten täglichen, monatlichen oder jährlichen Energiezähler und schließe die Einrichtung ab.

Falls sich das Formular für den Ladepunkt nicht automatisch öffnet, öffne **Charge Tally** unter **Einstellungen → Geräte & Dienste** und wähle **Ladepunkt hinzufügen**.

| Preisoption | Benötigte Angaben |
| --- | --- |
| Fester Preis | Dein Preis pro kWh |
| Dynamischer Preis | Ein Preissensor mit derselben Währung wie Charge Tally |
| Tageszeitabhängiger Preis | Beginn, Ende und Preis jedes Zeitraums, zusammen für den gesamten Tag |

Zeitabhängige Preise wiederholen sich täglich. Zeiträume dürfen über Mitternacht reichen; verwende `24:00` für das Tagesende. Null und negative Preise werden unterstützt.

> Platzhalter für einen Screenshot: Sensorauswahl und Einrichtung der Strompreise.

Um einen weiteren Ladepunkt oder eine Identität hinzuzufügen, öffne **Charge Tally** unter **Einstellungen → Geräte & Dienste**. Dort kannst du auch bestehende Ladepunkte bearbeiten. Beende den aktuellen Ladeeintrag, bevor du Messung oder Erkennung änderst.

## Die Dashboard-Karte hinzufügen

Bearbeite dein Dashboard, wähle **Karte hinzufügen** und suche nach **Charge Tally**. Im Karteneditor wählst du die angezeigten Ladepunkte, Identitäten und Informationen. Die Karte übernimmt Sprache und Design von Home Assistant.

Die Karte steht normalerweise automatisch bereit. Fehlt sie, aktualisiere zuerst den Browser. Wenn du Dashboard-Ressourcen selbst verwaltest, füge `/charge_tally/charge-tally-card.js?v=0.1.2-2` als **JavaScript-Modul** hinzu und aktualisiere erneut.

## Identitäten und Ladeeinträge verwenden

Eine Identität kann für ein Auto, ein Familienmitglied oder etwas anderes stehen, das du getrennt erfassen möchtest. Identitäten gelten für alle Ladepunkte. **Unassigned** steht bereit, wenn du niemanden ausgewählt hast.

Wähle die Identität vor dem Laden. Ein begonnener Eintrag behält diese Zuordnung. Eine Änderung der Auswahl während des Ladens gilt für den **nächsten** Eintrag. Um den aktuellen oder einen älteren Eintrag zu korrigieren, nutze **Identität des Eintrags ändern**.

Bei aktivierter automatischer Erkennung beginnt und endet ein Eintrag, sobald die Leistungsschwellen und Wartezeiten erfüllt sind. Kurze Pausen können Teil desselben Eintrags bleiben. Ohne Erkennung verwendest du **Eintrag starten** und **Eintrag beenden** auf der Karte.

In eigenen Automatisierungen kannst du über die Entität **Identität** des Ladepunkts auswählen, wer lädt. Zum Beispiel kann ein RFID-Leser oder ein Taster diese Auswahl ändern. In der Aktionsauswahl für Automatisierungen findest du auch Charge-Tally-Aktionen zum Starten und Beenden eines Eintrags.

## Frühere Ladevorgänge nachtragen oder korrigieren

1. Wähle auf der Karte **Historischen Eintrag hinzufügen** oder öffne einen beendeten Eintrag und wähle **Eintrag bearbeiten**.
2. Wähle Ladepunkt, Identität sowie Start- und Endzeit.
3. Verwende vorhandene Sensorverlaufsdaten oder gib die gesamte Energie selbst ein. Wähle die Kostenberechnung oder lasse die Kosten offen, wenn du sie noch nicht kennst.
4. Wähle **Änderungen in der Vorschau anzeigen**, prüfe das Ergebnis und wähle **Vorschau speichern**.

Verlaufsdaten stehen nur zur Verfügung, soweit Home Assistant sie aufbewahrt hat. Bei fehlenden Messwerten kannst du die Gesamtenergie aus einer anderen Quelle eintragen, etwa aus der Aufzeichnung deines Ladegeräts. Zwei Einträge desselben Ladepunkts dürfen sich zeitlich nicht überschneiden.

Mit **Eintrag stornieren** schließt du einen falschen Eintrag aus den Summen aus. Seine bisherigen Angaben bleiben zum Nachlesen erhalten.

> Platzhalter für einen Screenshot: früherer Ladeeintrag und Änderungsvorschau vor dem Speichern.

## Die Summen verstehen

- **Laden über Mitternacht:** Der Verbrauch wird den jeweiligen Tagen zugeordnet. Das gilt auch für Monats- und Jahreswechsel. Liegen zwei Zählerstände auf unterschiedlichen Seiten einer solchen Grenze, wird die Aufteilung anhand der verstrichenen Zeit geschätzt.
- **Ladevorgang läuft noch:** Werte können sich mit weiteren Messungen oder der Bestätigung der endgültigen Endzeit ändern.
- **Kosten ausstehend:** Einige Preise fehlen. Der angezeigte bekannte Betrag ist nur ein Teil der Kosten und noch kein Endbetrag.
- **Zähler- und Eintragssummen können abweichen:** Zähler erfassen auch Energie außerhalb von Ladeeinträgen, etwa Standby-Verbrauch. Identitätssummen enthalten nur zugeordnete Einträge. Eine Korrektur aktualisiert die Eintragsstatistik, nicht den Zählerverlauf.

## Häufige Fragen

**Warum gibt es keinen Ladeeintrag?** Prüfe, ob die gewählten Sensoren verfügbar sind. Prüfe bei automatischer Erkennung, ob sie aktiviert ist und die Leistung lange genug über der Startschwelle bleibt. Starte den Eintrag andernfalls manuell.

**Warum sind die Kosten ausstehend?** Prüfe den Preissensor und seine Währung oder öffne den Eintrag und gib einen bekannten Gesamtbetrag ein. Fehlende Daten werden nicht als kostenlose Energie gewertet.

**Warum fordert Home Assistant eine Reparatur des Ladepunkts an?** Einer der für diesen Punkt erstellten Energiezähler wurde möglicherweise entfernt oder verändert. Öffne die Reparaturmeldung und folge den Anweisungen.

**Wie aktualisiere ich sicher?** Erstelle ein Home-Assistant-Backup, aktualisiere Charge Tally über HACS und starte Home Assistant neu. Das Entfernen der Integration löscht die gespeicherten Ladeeinträge nicht.

Brauchst du Hilfe? [Melde ein Problem](https://github.com/enecess/ha-charge-tally/issues) mit deiner Home-Assistant-Version, der Charge-Tally-Version und einer Beschreibung des Problems.

[MIT-Lizenz](LICENSE)
