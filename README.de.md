# Charge Tally

[English](README.md) · [简体中文](README.zh-CN.md) · **Deutsch** · [Français](README.fr.md) · [Polski](README.pl.md) · [Italiano](README.it.md)

Erfasse Ladeenergie und Kosten in Home Assistant nach Ladepunkt und Identität und prüfe die Abrechnung jedes Ladevorgangs. Charge Tally nutzt vorhandene Energie- oder Leistungssensoren. Es führt Buch und steuert nicht den Lader.

- Ein Buch für mehrere Ladepunkte; Fahrzeuge, Fahrer oder Familienmitglieder als gemeinsame Identitäten.
- Kumulierte Energie, Energie aus Leistung oder Energiemessung mit Leistungserkennung.
- Feste, dynamische und tägliche zeitabhängige Preise, einschließlich null und negativer Preise.
- Automatische Erkennung oder Start und Ende über Karte und HA-Automationen.
- Live-Werte, Tages-, Monats-, Jahres-, Gesamt- und Bereichsstatistik mit nach Zeitraum gruppierten Diagrammen.
- Historische Einträge ergänzen, beendete Einträge bearbeiten, Identitäten ändern, Fehler stornieren und Kostendetails prüfen.
- Archivierte Punkte und Identitäten verwalten und Buchungsdaten dauerhaft entfernen.

**Einstellungen → Geräte & Dienste → Charge Tally** verwaltet die Konfiguration. Die **Charge Tally**-Karte im Dashboard zeigt und bearbeitet Einträge. Sie enthält mehrere Bereiche; Details und Bearbeitung öffnen sich in Dialogen.

> Screenshot-Platzhalter 01: Gesamte Karte mit Ladepunkten, Statistik und Einträgen.

## Aktuelles Verhalten von Karte und Abrechnung

Beim Öffnen sind nur die Ladesteuerungen aufgeklappt. Statistik und Datensätze bleiben zunächst eingeklappt. Live-Aktualisierungen erhalten geöffnete Bereiche und Bedienelemente; ein Neuladen setzt die Ansicht zurück. Diagramm und Verlauf werden beim Aufklappen des jeweiligen Bereichs geladen.

Diagramme gruppieren Heute nach Stunden, Diesen Monat nach Tagen, Dieses Jahr nach Monaten und Gesamt nach Jahren. Bei einem eigenen Zeitraum zählt die Differenz der lokalen Kalendertage: bis 2 Tage stündlich, bis 90 Tage täglich, bis 730 Tage monatlich, darüber jährlich. Es gelten die Zeitzone des Kontobuchs und Sommerzeitwechsel. Diagramme und Summen verwenden denselben Zeitraum; unbekannte Kosten bleiben unbekannt.

Kostendetails in Vorschau und Details fassen benachbarte Zeiträume mit gleicher Abrechnungsgrundlage und gleichem Preis zusammen. Änderungen der Messqualität teilen einen Preiszeitraum nicht auf; tatsächliche Energielücken werden gesondert angezeigt. Zeitraumstatistiken verwenden weiterhin die ursprünglichen Messintervalle. Das Kontobuch speichert intern Prüfschnappschüsse beim Start, Ende und bei ausdrücklichen Änderungen, einschließlich Zuordnung und Stornierung. Laufende Messwerte aktualisieren den Datensatz ohne weiteren Schnappschuss; interne Revisionsnummern können Lücken haben.

Nach Entfernen einer Ladepunktkonfiguration bleiben offene Datensätze erhalten. Unter **Konfigurieren → Archivierte Daten verwalten → Archivierte Ladepunkte** den entfernten Punkt wählen, Anzahl offener Datensätze und Umfang prüfen und die endgültige Löschung ausdrücklich bestätigen. Abbrechen erhält die Daten. Gelöscht werden zugehörige Datensätze, Revisionen, Messwerte und Preise, jedoch keine HA-Recorder-Daten oder Backups.

Das aktuelle Entwicklungsformat des Kontobuchs hat sich geändert. Nicht unterstützte ältere Formate werden ohne automatische Migration oder Löschung abgelehnt. Ein entbehrliches Testkontobuch muss nach einer Sicherung eventuell neu erstellt werden; das Update führt diese Bereinigung nicht aus.

## Navigation

- [Voraussetzungen](#voraussetzungen)
- [Integration installieren](#integration-installieren)
- [Erste Einrichtung](#erste-einrichtung)
- [Identitäten und spätere Änderungen](#identitäten-und-spätere-änderungen)
- [Dashboard-Karte hinzufügen und einstellen](#dashboard-karte-hinzufügen-und-einstellen)
- [Bereiche der Karte](#bereiche-der-karte)
- [Ladeeinträge im Alltag](#ladeeinträge-im-alltag)
- [Historische Einträge hinzufügen und bearbeiten](#historische-einträge-hinzufügen-und-bearbeiten)
- [Statistik und Datenqualität verstehen](#statistik-und-datenqualität-verstehen)
- [Native Entitäten und Automationen](#native-entitäten-und-automationen)
- [Archivierte Daten und Währung verwalten](#archivierte-daten-und-währung-verwalten)
- [Updates, Sicherung und Wiederherstellung](#updates-sicherung-und-wiederherstellung)
- [Häufige Fragen](#häufige-fragen)

## Voraussetzungen

Du benötigst **Home Assistant 2025.9.0 oder neuer**, mindestens einen Sensor für den Ladestromkreis und ein Administratorkonto zur Einrichtung. Die Oberfläche folgt der HA-Sprache. Hier stehen die tatsächlichen deutschen Beschriftungen; allgemeine HA-Menüs können je nach Version anders angeordnet sein.

| Messwerte | „Energieerfassungsmodus“ | Verwendung |
| --- | --- | --- |
| Kumulierte Energie in Wh, kWh oder MWh | **Nur Energie** | Zählerbasierte Erfassung; über Karte oder Automation starten und beenden |
| Leistung in W oder kW | **Nur Leistung (natives Integral)** | Automatisch erstellter HA-Helfer berechnet Energie; Erkennung möglich |
| Energie und Leistung | **Energie und Leistung** | Energie messen, Leistung zur Erkennung nutzen; keine doppelte Zählung |

Kumulierte Energie ist ein normalerweise steigender Zählerstand, gegebenenfalls nach Rücksetzung, nicht der Verbrauch der letzten Stunde. Sensoren müssen als Energie oder Leistung gekennzeichnet sein und gültige, nicht negative Werte liefern. Dieselbe Quelle darf nicht mehreren Punkten zugeordnet werden.

Dynamische Preise benötigen einen Sensor in der Buchwährung. Für historische Ergänzungen muss HA die Quellsensoren aufzeichnen und den benötigten Zeitraum noch gespeichert haben.

## Integration installieren

### Möglichkeit 1: HACS

Installiere bei Bedarf zuerst HACS nach der [offiziellen Anleitung](https://hacs.dev/docs/use/download/download/).

**Mit einem Klick zu HACS hinzufügen:**

[![Charge Tally in HACS öffnen](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=enecess&repository=ha-charge-tally&category=integration)

Klicke auf die Schaltfläche, gib deine Home-Assistant-Adresse ein oder bestätige sie und füge Charge Tally in HACS hinzu oder öffne es. Fahre unten mit Schritt 3 fort, um die Integration herunterzuladen, HA neu zu starten und die Integration hinzuzufügen. Für das manuelle Hinzufügen des Repositorys beginne mit Schritt 1.

1. Öffne **HACS**, dann im Menü oben rechts **Benutzerdefinierte Repositories**.
2. Füge `https://github.com/enecess/ha-charge-tally` als **Integration** hinzu.
3. Suche **Charge Tally**, öffne es und lade die gewünschte Version herunter.
4. **Starte Home Assistant neu.**
5. Öffne **Einstellungen → Geräte & Dienste → Integration hinzufügen** und wähle **Charge Tally**.
6. Fahre mit der ersten Einrichtung fort. Der Download allein erstellt weder Buch noch Ladepunkt.

> Screenshot-Platzhalter 02: HACS-Repository, Download und Suche beim Hinzufügen der Integration.

### Möglichkeit 2: Manuelle Installation

1. Lade das Repository herunter, entpacke es und suche `custom_components/charge_tally`.
2. Öffne das HA-Konfigurationsverzeichnis mit `configuration.yaml`.
3. Erstelle nötigenfalls `custom_components` und kopiere den gesamten Ordner `charge_tally` einschließlich Unterordnern hinein.
4. Prüfe den Pfad `custom_components/charge_tally/manifest.json`; vermeide eine zusätzliche Repository-Verzeichnisebene.
5. **Starte HA neu** und öffne **Einstellungen → Geräte & Dienste → Integration hinzufügen → Charge Tally**.

Die Karte wird mitgeliefert und braucht keine separate HACS-Installation. Fehlt die Integration, prüfe Ordnerstruktur und Neustart, aktualisiere die Seite und prüfe die HA-Protokolle.

## Erste Einrichtung

### 1. Abrechnungsbuch erstellen

Wähle unter **Charge Tally-Abrechnungsbuch** die **Währung** aus allen von Home Assistant unterstützten Währungen. Die Liste zeigt lokalisierte Namen mit ISO-Code, etwa Renminbi Yuan (CNY), und wird nach Namen in der Oberflächensprache sortiert. Bei der ersten Einrichtung ist die Währung aus den Haushaltseinstellungen von Home Assistant vorausgewählt. Pro HA-Instanz gibt es ein Buch mit gemeinsamer Währung für alle Punkte und Einträge.

- Ohne Ladepunkte, einschließlich archivierter, und ohne gespeicherte Buchungsdaten ist sie änderbar. Identitäten allein sperren sie nicht.
- Ein hinzugefügter Punkt sperrt sie bereits vor dem ersten Laden.
- Das Löschen einzelner Punkt- oder Identitätskonfigurationen bewahrt die Historie; erst vollständiges Bereinigen aller Punkte und ihrer Daten ermöglicht Währungsänderungen.
- Das Entfernen der gesamten Integration löscht ihr Buch und ihre eigenen Daten dauerhaft. Beim erneuten Hinzufügen entsteht ein neues Buch in der gewählten Währung.
- Beim Absenden werden auch Buchdateien gelöscht, die nach dem Entfernen einer älteren Version zurückgeblieben sind.

> Screenshot-Platzhalter 03: Buchanlage mit Währung und Hinweisen.

### 2. Ladepunkt hinzufügen

HA-Versionen mit direktem Folgeablauf öffnen danach den Punktdialog. Andernfalls öffne **Einstellungen → Geräte & Dienste → Charge Tally → Ladepunkt hinzufügen**.

Unter **Ladepunkt** füllst du **Name**, beispielsweise „Garage“, und **Energieerfassungsmodus** aus. Ein Punkt entspricht einem separat gemessenen Ladestromkreis.

### 3. Messquellen auswählen

Öffne unter **Messquellen** den Bereich **Messung und Erkennung**:

| Feld | Eingabe |
| --- | --- |
| **Sensor für kumulierte Energie** | Zähler des Stromkreises; nicht bei „Nur Leistung (natives Integral)“ |
| **Leistungssensor** | Leistung des Stromkreises; nicht bei „Nur Energie“ |
| **Zähler kann zurückgesetzt werden** | Aktiv lassen, wenn Rücksetzungen möglich sind; fallende Werte markieren ein unvollständiges Rücksetzungsintervall |
| **Maximales Zuordnungsintervall (Sekunden)** | Standard 600; längere Messintervalle werden zu prüfenden Lücken |
| **Automatische Ladeerkennung** | Nur bei Modi mit Leistung; aktiviert den nächsten Schritt |

### 4. Automatische Erkennung einstellen (optional)

Mit **Automatische Ladeerkennung** folgt **Automatische Erkennung**:

- **Startschwelle (W)**: Bei Erreichen oder Überschreiten beginnt die Startbestätigung.
- **Startdauer (Sekunden)**: Nach durchgehend erfüllter Bedingung entsteht ein Eintrag; Standard 30 Sekunden.
- **Endschwelle (W)**: Unterhalb beginnt die Endbestätigung; muss niedriger als die Startschwelle sein.
- **Enddauer (Sekunden)**: Danach endet der Eintrag; Standard 300 Sekunden.

Passe die Schwellen an Standby- und Ladeleistung an. Nach Bestätigung gilt rückwirkend der Beginn der erfüllten Bedingung. Kürzere Pausen bleiben im selben Eintrag. Bis zum Abschluss der Startbestätigung kannst du die Identität für diese Ladung ändern; Startzeit und Bestätigungsfortschritt bleiben erhalten.

Auch ohne Erkennung funktionieren **Erfassung manuell starten** und **Erfassung beenden**.

> Screenshot-Platzhalter 04: Messquellen mit Erkennung und deren Parameterdialog.

### 5. Strompreis konfigurieren

Auswahl bei **Preismodus** und Folgedialog heißen teilweise unterschiedlich:

| Auswahl | Dialog | Eingabe |
| --- | --- | --- |
| **Fest** | **Fester Preis** | **Preis pro kWh** in der Buchwährung |
| **Dynamischer Sensor** | **Dynamischer Preis** | **Preissensor**, bei Bedarf **Bestätigte Einheit** |
| **Täglicher zeitabhängiger Tarif** | **Täglicher Zeitplan für zeitabhängige Tarife** | Preiszeiträume für den ganzen Tag |

Feste und zeitabhängige Preise dürfen null oder negativ sein. Dynamische Preise unterstützen Buchwährung pro Wh, kWh oder MWh. Energieeinheiten werden umgerechnet, Währungen nicht. **Bestätigte Einheit** ergänzt nur eine fehlende Einheit und überschreibt keine falsche vorhandene Währung oder Einheit.

Für **Täglicher Zeitplan für zeitabhängige Tarife**:

1. Wähle unter **Aktion** den Eintrag **Zeitraum hinzufügen**.
2. Fülle unter **Preiszeitraum bearbeiten** die Felder **Startzeit**, **Endzeit (24:00 = Tagesende)** und **Preis pro kWh** aus.
3. Wiederhole dies. Zum Ändern oder Löschen wähle einen **Zeitraum**, dann **Zeitraum bearbeiten** oder **Zeitraum entfernen**.
4. Wähle **Zeitplan abschließen**, wenn der ganze Tag abgedeckt ist.

Format: `HH:MM`, etwa `00:00–08:00`, `08:00–22:00`, `22:00–24:00`. Auch `22:00–06:00` ist möglich. Keine Überschneidungen, Lücken oder gleichen Endpunkte; ganztägig ist `00:00–24:00`. Der Plan gilt täglich ohne Unterscheidung von Werktagen und Wochenenden.

> Screenshot-Platzhalter 05: Preisauswahl, dynamische Einheit, Zeitplan und Zeitraumdialog.

### 6. Zeitraumstatistiken und Zusammenfassung prüfen

Prüfe unter **Zeitraumstatistiken und Zusammenfassung** Name, Mess- und Preismodus. Wähle unter **Zeiträume für Energiestatistiken** **Täglich / Monatlich / Jährlich**. Alle sind standardmäßig gewählt; keine Auswahl ist ebenfalls erlaubt.

Dies bestimmt zusätzliche native Energiehelfer, nicht die Verfügbarkeit der Eintrags- oder Identitätsstatistik. Prüfe danach Punktanzeige, Quellsensoren und eventuelle Helfer-Reparaturmeldungen.

> Screenshot-Platzhalter 06: Zusammenfassung und fertig eingerichtete Integrationsseite.

## Identitäten und spätere Änderungen

Unter **Einstellungen → Geräte & Dienste → Charge Tally**:

| Einstieg | Zweck |
| --- | --- |
| **Ladepunkt hinzufügen** | Weiteren separat gemessenen Stromkreis anlegen |
| **Ladepunkt konfigurieren** | Name, Sensoren, Erkennung, Preise und Statistikzeiträume ändern |
| **Gemeinsame Identität hinzufügen** | Identität für Fahrzeug, Person oder anderen Zweck |
| **Identität konfigurieren** | Namen oder **Aktiviert** ändern |
| **Konfigurieren** an der Hauptintegration | **Bucheinstellungen** und **Archivierte Daten verwalten**; **NFC-Identitätsverknüpfungen** |

**Gemeinsame Identität** enthält nur **Name** und **Aktiviert**. Identitäten gelten für alle Punkte; Namen dürfen nicht mit anderen konfigurierten Identitäten übereinstimmen. Die eingebaute Identität **Unassigned** für nicht zugeordnete Einträge behält diesen englischen Namen im Auswahlfeld.

Umbenennen erhält die historische Zuordnung. Ohne **Aktiviert** ist die Identität nicht mehr neu auswählbar; Historie bleibt. Auch Konfiguration löschen erhält den Verlauf; erst danach lässt sich die Identität dauerhaft über die Archivverwaltung entfernen. Deaktivieren ist kein Löschen.

Beende vor Änderungen an Messung oder Erkennung den Eintrag und warte, bis **Laden wird bestätigt / Ende wird bestätigt** endet. Preisänderungen gelten ab Änderung und berechnen erfasste Beträge nicht neu. Beende Einträge auch vor dem Löschen eines Punkts: Konfiguration löschen beendet laufende Erfassung nicht automatisch.

> Screenshot-Platzhalter 07: Gemeinsame Identität und getrennte Konfigurationseinstiege.

## Dashboard-Karte hinzufügen und einstellen

1. Konfiguriere mindestens einen Punkt und öffne das Dashboard.
2. Aktiviere die Bearbeitung. Im Abschnittslayout nutze das Plus im Abschnitt, sonst **Karte hinzufügen**.
3. Suche den Kartentyp **Charge Tally** und wähle ihn.
4. Stelle die folgenden Optionen im visuellen Editor ein, speichere und beende die Dashboard-Bearbeitung.

| Editorfeld | Wirkung |
| --- | --- |
| **Titel** | Eigener Titel; leer verwendet Charge Tally |
| **Ladepunkt** | Anfangs gewählter Punkt oder **Alle** |
| **Identitätsfilter** | Anfangs gewählte Identität oder **Alle** |
| **Einträge anzeigen** | Liste samt Einstieg zum Hinzufügen historischer Einträge ein-/ausblenden |
| **Diagramm anzeigen** | Balkendiagramm ein-/ausblenden; Statistikwerte bleiben verfügbar |

Mehrere Karten können unterschiedliche Punkte oder Identitäten zeigen. Die Filter erteilen keine Rechte; Benutzer sehen nur durch HA erlaubte Daten. Die Karte unterstützt Deutsch, Englisch, vereinfachtes Chinesisch, Französisch, Polnisch und Italienisch und folgt dem Design.

> Screenshot-Platzhalter 08: Kartenauswahl und visueller Editor mit fünf Einstellungen.

### Karte fehlt in der Auswahlliste

Prüfe, ob die Integration geladen ist, und aktualisiere den Browser. Bei über die Oberfläche verwalteten Dashboard-Ressourcen registriert sie die Karte normalerweise automatisch.

Falls nötig, öffne im Menü unter **Einstellungen → Dashboards** die **Ressourcen**. Fehlt der Einstieg, aktiviere im Profil den **Erweiterten Modus**. Füge folgende Ressource hinzu und aktualisiere:

| Feld | Inhalt |
| --- | --- |
| URL | `/charge_tally/charge-tally-card.js?v=0.1.2-10` |
| Ressourcentyp | **JavaScript-Modul** |

Aktualisiere vorhandene Ressourcen mit demselben Pfad, statt sie doppelt anzulegen. Bei YAML-Ressourcenverwaltung trage dieselbe Adresse als Modul ein. Installiere keine zweite Karte. Siehe [HA-Dashboard-Dokumentation](https://www.home-assistant.io/dashboards/dashboards/).

## Bereiche der Karte

### Verbindung und Filter oben

Neben dem Titel steht **Verbunden** oder **Verbindung getrennt · aktuelle Momentaufnahme wird erwartet**. Nach Verbindungswiederherstellung kannst du **Erneut versuchen** nutzen. Alte Anzeigen sind keine aktuellen Abrechnungsergebnisse.

**Ladepunkt** und **Identitätsfilter** wirken auf Statistik und Liste. Die Punktauswahl bestimmt zusätzlich die Live-Bereiche; der Identitätsfilter ändert keine gewählte Punktidentität. Historische Objekte können **Archiviert** heißen. Archivierte Punkte zeigen Historie, aber keinen Live-Bereich zum Starten. Auch deaktivierte Identitäten können die Markierung tragen; für dauerhaftes Löschen ist die Archivverwaltung maßgeblich.

### Live-Bereich des Ladepunkts

Der Bereich zeigt Erfassung, **Leistung** und **Erkennung** getrennt. **Keine Erfassung**, **Manuelle Erfassung läuft** und **Automatische Erfassung läuft** beschreiben den Eintrag; ein aktiver Eintrag bedeutet nicht, dass der Lader gerade Strom bezieht. Die Erkennung zeigt separat Warten, Bestätigung, Pause während manueller Erfassung, fehlende Daten oder Warten auf Leistungsabfall.

Während der Startbestätigung zeigt **Identität für diese ausstehende Ladung** die aktuelle Kandidatenidentität. **Identität für ausstehenden / manuellen Eintrag** ändert diese ausstehende Ladung oder einen sofortigen manuellen Start. Startzeit und Bestätigungsfortschritt bleiben erhalten; bestehende Einträge behalten ihre Identität.

Jeder aktuelle Punkt zeigt Name, Status, **Leistung**, **Aktueller Preis** und **Erkennung**. Fehlende Leistung oder Preise können leer sein. **Erkennung** ist hier eine Anzeige; ändere Einstellungen in der Punktkonfiguration oder über den nativen Schalter **Ladeerkennung**.

| Anzeige | Bedeutung |
| --- | --- |
| **Ausgewählte Identität** | Ohne aktiven Eintrag: Identität der ausstehenden oder nächsten Ladung |
| **Dieser Eintrag** | Bereits zugeordnete Identität des aktiven Eintrags |
| **Identität für den nächsten Eintrag** | Nächste Zuordnung vorbereiten, ohne den laufenden Eintrag zu ändern |
| **Erfassung läuft · Bisherige Summe** | Energie, Kosten, Beginn, Dauer und Qualität des laufenden Eintrags |
| **Details** | Aktuellen Eintrag öffnen |
| **Identität des Eintrags ändern** | Aktuelle Zuordnung korrigieren |
| **Erfassung manuell starten / Erfassung beenden** | Erfassung zum aktuellen Zeitpunkt |

> Screenshot-Platzhalter 09: Laufender Eintrag mit aktueller/nächster Identität und vorläufigen Kosten.

### Eintragsstatistik und Diagramm

Wähle unter **Eintragsstatistik → Statistikzeitraum** zwischen **Heute / Dieser Monat / Dieses Jahr / Gesamter Zeitraum / Benutzerdefinierter Zeitraum**. Für eigene Daten fülle **Beginn** und **Ende (ausschließlich)** aus und wähle **Zeitraum anwenden**. Für den ganzen 1. September gilt Beginn 1. September, Ende 2. September.

Die Zusammenfassung zeigt **Energie**, **Kosten**, **Aktiv / abgeschlossen** und Qualität. **Aktualisieren** lädt neue Ergebnisse. **Diagrammkennzahl** wechselt zwischen **Energie** und **Kosten** im nach Zeitraum gruppierten Diagramm. **Details** darunter öffnet die Tabelle mit Werten je Zeitabschnitt.

**PDF exportieren** lädt einen durchsuchbaren A4-Bericht in der Sprache der Karte herunter. Es gelten Ladepunkt, Identität und Statistikzeitraum beim Klicken; noch nicht übernommene Datumsentwürfe zählen nicht. Alle passenden lesbaren Einträge sind enthalten, auch bei ausgeblendeter Eintragsliste oder einer anderen Listenseite. **Alle** Identitäten erstellt einen gemeinsamen Bericht. Spätere Filteränderungen und Live-Aktualisierungen ändern den laufenden Export nicht.

Die Zeilen zeigen die vollständigen Eintragszeiten und nur den Energie- und Kostenanteil im gewählten Zeitraum. Laufende Einträge sind vorläufig; unvollständige Kosten erscheinen als bekannte Teilsumme mit Qualitätshinweisen. Unbekannte Werte sind keine Nullwerte. Abgeschlossene Einträge sind solche, die im Zeitraum begonnen haben und beendet sind. Summen basieren auf ungerundeten Werten; Energie wird mit bis zu 3, Kosten mit 2 Nachkommastellen angezeigt. Gerundete Zeilen können daher in der letzten Stelle von der Summe abweichen.

Warten Sie auf die PDF-Erstellung; danach kann ein weiterer Export versucht werden. Bei zu großen Berichten den Zeitraum verkürzen oder nach Ladepunkt oder Identität filtern. Schriftfehler nennen Feld, gegebenenfalls Eintragszeile und Unicode-Codepunkte. Ändern Sie diese Zeichen im Namen oder in der Notiz und versuchen Sie es erneut. Verbindungsabbruch oder Entladen der Integration beendet den Download.

> Screenshot-Platzhalter 10: Statistik, Datumsbereich, Diagrammkennzahl und aufgeklappte Werte je Zeitabschnitt.

### Einträge · alle Zeiträume

Die Liste zeigt aktive und beendete Einträge, absteigend nach Beginn, 25 pro Seite. **Zurück / Weiter** blättert. Zeilen enthalten Punkt, Identität, Beginn, Status, Energie, Kosten und Qualität; die ganze Zeile öffnet Details.

Nur Punkt- und Identitätsfilter gelten: **Der Statistikzeitraum schränkt die Liste nicht ein.** „Heute“ lässt ältere Einträge sichtbar. Neben dem Titel steht **Historischen Eintrag hinzufügen**; eine leere Liste zeigt **Keine Einträge**.

> Screenshot-Platzhalter 11: Liste, historisches Hinzufügen, Eintragszeilen und Seitennavigation.

## Ladeeinträge im Alltag

### Manuell starten und beenden

1. Wähle die Identität und **Erfassung manuell starten**; während der Startbestätigung heißt der Knopf **Erfassung jetzt starten**.
2. Prüfe **Manuelle Erfassung läuft** und die aktuellen Summen. Ein sofortiger manueller Start verwendet die aktuell ausgewählte Identität und verwirft den automatischen Kandidaten.
3. Wähle **Erfassung beenden** und prüfe den Eintrag in der Liste.

Die Knöpfe erfassen Zeitpunkte und schalten den Lader nicht. Ein manuell gestarteter Eintrag muss über die Karte oder eine Automationsaktion ausdrücklich beendet werden. Die automatische Erkennung pausiert währenddessen und beendet ihn auch bei null Leistung nicht. Zum Start ist ein gültiger Energie-Ausgangswert erforderlich; ein bestehender Eintrag kann auch bei fehlenden Messdaten beendet werden.

### Laden automatisch erkennen

Bei eingerichteter und aktivierter Erkennung ist die Folge **Laden wird bestätigt → Automatischer Eintrag wird erfasst → Ende wird bestätigt → Warten auf automatische Erkennung** möglich. Entfällt während der Bestätigung die Leistungsbedingung, wird die ausstehende Bestätigung verworfen. Die automatische Bestätigung verwendet die letzte vor Abschluss erfolgreich ausgewählte Identität, einschließlich **Unassigned**. Mit **Erfassung manuell beenden** kannst du einen automatischen Eintrag vorzeitig beenden; während der Endbestätigung heißt der Knopf **Erfassung jetzt beenden**.

Nach ausdrücklichem Beenden wartet die Erkennung normalerweise auf Leistung unter der Endschwelle. Sie kann sofort fortfahren, wenn die letzte gültige niedrige Leistungsmessung nicht nach dem Endbefehl liegt, nicht älter als die unter **Maximales Zuordnungsintervall (Sekunden)** eingestellte Gültigkeitsdauer ist und weder fehlende Daten noch ein Neustart sie ungültig gemacht haben. Hohe, fehlende, zukünftige oder veraltete Messwerte lösen die Sperre nicht. Nach `unknown` oder nicht verfügbarer Leistung ist eine neue gültige Messung unter der Endschwelle nötig. Während der Sperre bleibt manuelles Starten möglich.

Beende vor dem Pausieren mit **Ladeerkennung** aktive Einträge und offene Bestätigungen. Fehlen Schwellenwerte, ergänze sie unter **Ladepunkt konfigurieren**.

### Eintragsdetails ansehen

Details zeigen Zuordnung, Energie, Kosten, einen kompakten Datums- und Zeitbereich mit Dauer, Abrechnungszeitzone, Status, Quelle und Notiz. Hinweise nennen fehlende Energie oder Preise. Unbekannte Kosten erscheinen nicht als null; manuelle Kosten behalten auch bei unvollständiger Messabdeckung den eingegebenen Gesamtbetrag.

- **Kostendetails** sind zunächst eingeklappt. Aufgeklappt zeigen sie Preiszeiträume chronologisch mit Zeit, Preis, Energie und Kosten sowie gesonderte Energielücken. Datumsangaben sind gruppiert; bei mehr als 12 Zeiträumen lassen sich die übrigen aufklappen.
- Aktive Einträge erlauben **Identität des Eintrags ändern**; nur beendete bieten **Eintrag bearbeiten** und **Eintrag stornieren**.

> Screenshot-Platzhalter 12: Beendeter Eintrag mit aufklappbaren Kostendetails und Aktionen.

### Identität korrigieren

Öffne Details und **Identität des Eintrags ändern**, wähle die **Zugeordnete Identität** und **Vorschau speichern**. So heißt die Bestätigung dieses Dialogs tatsächlich; ein separater Vorschau-Schritt ist nicht nötig. Der ganze Eintrag erhält die neue Zuordnung, ohne Energie oder Beträge neu zu berechnen.

### Falschen Eintrag stornieren

Wähle beim beendeten Eintrag **Eintrag stornieren**, prüfe und wähle **Stornierung bestätigen**. Er verschwindet aus Statistik und normaler Liste; Original und Revisionen bleiben im Buch. Es gibt keine Ansicht zum Einblenden stornierter Einträge und keine Wiederherstellungsschaltfläche. Stornieren ist kein dauerhaftes Löschen.

## Historische Einträge hinzufügen und bearbeiten

**Historischen Eintrag hinzufügen** öffnet **Neuer historischer Eintrag**. Zum Ändern öffne einen beendeten Eintrag und **Eintrag bearbeiten**.

1. Prüfe **Zeitzone der Abrechnung**, **Ladepunkt** und **Zugeordnete Identität**. Neue Einträge benötigen aktuelle Punkte und aktivierte Identitäten. Auch wenn archivierte Punkte in der Auswahl erscheinen, sind dort keine neuen Einträge möglich. Beim Bearbeiten ist der Punkt fest.
2. Gib Datum und Uhrzeit für **Beginn** und **Ende (ausschließlich)** ein; das Ende muss später liegen.
3. Gib manuelle Energie ein oder lasse sie leer und wähle die Kostengrundlage.
4. Ergänze bei Bedarf **Notiz**, maximal 2000 Zeichen.
5. Wähle **Änderungen in der Vorschau anzeigen**. Prüfe unter **Vorschau · vor dem Speichern prüfen** Beträge, Abschnitte, Qualität und **Messabdeckung**; beim Bearbeiten auch **Vorher / Nachher**.
6. Ohne Überschneidung kannst du **Vorschau speichern** wählen. Formularänderungen erfordern eine neue Vorschau; **Schließen** speichert nicht.

| Feld oder Option | Verhalten |
| --- | --- |
| **Manuelle Energie (kWh, leer: Verlaufsdaten verwenden)** beim Hinzufügen | Leer versucht verfügbare Messhistorie zu nutzen, sonst gilt die eingegebene Gesamtenergie |
| **Manuelle Energie (kWh, leer: bestehende Grundlage beibehalten)** beim Bearbeiten | Leer erhält die bisherige Grundlage und löscht keine frühere manuelle Energie |
| **Kostengrundlage → Verfügbare Verlaufsdaten und Preise verwenden** | Standard beim Hinzufügen, benötigt tatsächlich vorhandene Historie und Preise |
| **Kostengrundlage → Bestehende Kostengrundlage beibehalten** | Standard beim Bearbeiten, damit Notizänderungen keine unbeabsichtigte Neuberechnung auslösen |
| **Kostengrundlage → Manuelle Gesamtkosten** | Aktiviert das Betragsfeld gleichen Namens; null und negative Beträge erlaubt |
| **Kostengrundlage → Ausstehend** | Kosten ausdrücklich unbekannt, nicht kostenlos |

Einträge desselben Punkts dürfen sich nicht überschneiden. Überschneidungen verhindern Speichern. Bei veralteter Vorschau oder geändertem Eintrag aktualisiere und erstelle eine neue Vorschau.

Historische Ergänzung hängt von erhaltenen HA- und Buchdaten ab; beliebig alte Zeiträume sind nicht garantiert wiederherstellbar. Fehlende Energie und Kosten können anhand einer Laderabrechnung ergänzt werden. Manuelle Gesamtwerte werden zeitlich verteilt; **Manuell überschrieben / Geschätzt** beschreibt diese Berechnungsgrundlage.

Zeiten gelten in der angezeigten Abrechnungszeitzone, nicht der Browserzeitzone. Bei Sommerzeit-Dopplungen wähle unter **Doppelte Ortszeit: UTC-Zeitpunkt auswählen** den passenden Zeitpunkt. Nicht existierende Ortszeiten sind unzulässig.

> Screenshot-Platzhalter 13: Historisches Hinzufügen/Bearbeiten, Kostengrundlage und Vorschau mit Messabdeckung.

## Statistik und Datenqualität verstehen

| Hinweis | Bedeutung |
| --- | --- |
| **Vorläufig / Abrechnung ausstehend** | Eintrag oder Messgrenzen noch nicht endgültig; spätere Werte können Ergebnisse ändern |
| **bekannte Teilsumme · ausstehend** | Bekannte Kosten, keine vollständige Rechnung; unbekannt ist nicht null |
| **Preis fehlt / Preis unbekannt** | Kein gültiger Preis; Währung, Einheit, Verfügbarkeit und Historie prüfen |
| **Energiedaten fehlen / Erfassungslücke** | Fehlende Daten oder zu großer Messabstand; prüfen und nötigenfalls ergänzen |
| **Zähler zurückgesetzt** | Fallender Zählerstand macht das Intervall unvollständig |
| **Manuell überschrieben / Geschätzt** | Manuelle Werte oder zeitliche Verteilung, keine durchgehende reale Messung |

Energie wird auf Tage, Monate und Jahre verteilt; Mitternacht überschreitende Ladung gehört nicht komplett zum Starttag. Historische Einträge behalten ihre Abrechnungszeitzone. Die Anzahl abgeschlossener Einträge folgt dem Beginn: Ein Eintrag kann Energie zum Bereich beitragen, ohne dessen Anzahl abgeschlossener Einträge zu erhöhen.

Karte und Identitätsstatistik summieren nur Ladeeinträge. Native Energiezähler können auch Standby außerhalb von Einträgen enthalten. Änderungen aktualisieren Buchstatistiken, nicht die native HA-Zählerhistorie. Kostendiagramme zeigen bekannte Beträge; die angezeigten Dezimalstellen ändern keine gespeicherte Genauigkeit.

## Native Entitäten und Automationen

Daten sind auch in HA-Entitätsansichten, anderen Karten und Automationen verfügbar. Beispiele mit Punkt „Garage“ und Identität „Familienauto“:

| Sichtbare Entität | Zweck |
| --- | --- |
| **Garage Energie** | Kumulierte Energie des Punkts |
| **Garage Status** | Lade- oder Verfügbarkeitszustand |
| **Garage Energie des Eintrags / Garage Kosten des Eintrags** | Aktiver Eintrag; ohne aktiven Eintrag kein aktueller Wert, nicht der vorherige Eintrag |
| **Garage Identität** | Identität des nächsten Eintrags, beispielsweise über RFID oder Taster |
| **Garage Ladeerkennung** | Erkennung bei Leistungsmodi; schaltet nicht die Stromversorgung |
| **Familienauto Tagesenergie / Tageskosten, Monatsenergie / Monatskosten, Jahresenergie / Jahreskosten, Gesamtenergie / Gesamtkosten** | Identitätsstatistik; entsprechende Entitäten auch für Unassigned |

Bei unvollständigen Kosten können native Kostenentitäten ohne vollständigen Wert bleiben, während die Karte bekannte Teilsummen zeigt. Die zusätzlichen täglichen/monatlichen/jährlichen Energiehelfer dienen einem anderen Zweck als die Identitätsstatistik. Lösche oder verändere verwaltete Helfer nicht manuell.

Die Aktionsauswahl bietet **Charge Tally: Erfassung starten / Erfassung beenden / Identität des Eintrags neu zuordnen**. Start und Ende verwenden die aktuelle Serverzeit; historische Zeitpunkte ergänzt du über die Karte.

Alle Buchungsaktionen benötigen eine **Anfrage-ID**, Beenden und Neuzuordnen außerdem **Erwartete Eintragsrevision**. Eine Geräteauswahl allein genügt nicht. Neue Operationen verwenden unterschiedliche IDs; Wiederholungen derselben Operation behalten ID und Parameter. Für die nächste Identität genügt **Garage Identität**. Wer diese Prüffelder nicht verwenden möchte, erfasst direkt über die Kartenknöpfe.

## Archivierte Daten und Währung verwalten

### Konfiguration löschen, stornieren und dauerhaft bereinigen

| Vorgang | Ergebnis |
| --- | --- |
| Identität deaktivieren | Nicht neu auswählbar; Konfiguration und Historie bleiben |
| Punkt- oder Identitätskonfiguration löschen | Historie bleibt; Kandidat für Archivverwaltung. Deaktivieren ist kein Löschen |
| Einzelnen Eintrag stornieren | Aus normaler Liste und Statistik ausgeschlossen, Prüfverlauf bleibt |
| Dauerhafte Archivoperation | Buchobjekte und zugehörige Daten werden entfernt; keine Rücknahme in der Oberfläche |

### Archivierten Ladepunkt dauerhaft bereinigen

1. Öffne an der Hauptintegration **Konfigurieren → Archivierte Daten verwalten → Archivierte Ladepunkte**.
2. Wähle unter **Archivierte Objekte auswählen** einen oder mehrere Punkte mit gelöschter Konfiguration.
3. Prüfe unter **Dauerhaften Vorgang bestätigen** Objekt, Vorgang, Einträge einschließlich stornierter, Revisionen, UTC-Zeitraum, Energie und bekannte Kosten.
4. Aktiviere **Ich verstehe die Auswirkungen und bestätige das dauerhafte Löschen** und bestätige. **Archivvorgang abgeschlossen** zeigt die Zahl gelöschter Einträge.

Dies löscht Einträge, zugehörige Revisionen, Messwerte und Preisverlauf des Punkts aus dem Buch, statt nur einen Namen auszublenden.

### Archivierte Identität dauerhaft entfernen

Öffne **Konfigurieren → Archivierte Daten verwalten → Archivierte Identitäten** und wähle ein oder mehrere Objekte. Hat mindestens eines Einträge, wähle unter **Identitätseinträge übertragen** dieselbe **Empfängeridentität** für alle: eine aktivierte Identität oder **Unassigned**. Ohne Einträge folgt direkt die Bestätigung.

Alle ausgewählten Objekte werden gemeinsam verarbeitet. Bei Änderungen oder Fehlern bleibt die gesamte Auswahl unverändert.

Alle Einträge einschließlich stornierter werden mit unveränderten Beträgen übertragen. Die ursprüngliche Identität wird entfernt, alte Revisionen behalten ihren Namen. Unassigned kann nicht gelöscht werden. Wird das Objekt verwendet oder ändern sich Daten während der Bestätigung, wird der Vorgang blockiert: Beende aktive Einträge oder öffne die Vorschau neu.

Die Bereinigung betrifft nur Charge Tally und **löscht weder native HA-Historie noch Langzeitstatistiken oder Sicherungen**. Energie und bekannte Kosten der Bestätigung enthalten stornierte Einträge und beschreiben den Umfang; sie sind nicht direkt mit der normalen Statistik ohne stornierte Einträge vergleichbar.

> Screenshot-Platzhalter 14: Archivkategorien, Objektauswahl, Übertragung und Bestätigung.

### Währung ändern

Öffne **Konfigurieren → Bucheinstellungen** an der Hauptintegration. Die Liste behält die aktuelle Buchwährung als Auswahl bei, auch wenn sich die Systemwährung von Home Assistant ändert. Nur ohne Ladepunkte, einschließlich archivierter, und ohne gespeicherte Buchungsdaten erscheint das Änderungsformular. Sonst zeigt **Währung gesperrt** die Gründe. Identitäten allein sperren nicht.

Für einen Neustart in anderer Währung sichere benötigte Daten, lösche nicht mehr verwendete Punktkonfigurationen, bereinige ihre Archivdaten und öffne die Bucheinstellungen erneut. Das ist eine neue Währungswahl nach Bereinigung, keine Umrechnung alter Beträge.

## Updates, Sicherung und Wiederherstellung

1. Erstelle vor Updates eine Sicherung einschließlich HA-Konfigurationsverzeichnis.
2. Aktualisiere HACS-Installationen in HACS; manuell installierte Integrationen durch Austausch des gesamten Ordners mit vollständiger Struktur.
3. Starte HA neu und aktualisiere das Dashboard im Browser oder in der App. Prüfe bei eigener Ressourcenverwaltung die Version der oben genannten Adresse.
4. Prüfe Punkte, Einträge und Statistik; bearbeite nötige Helferreparaturen über den Reparaturablauf.

Das Buch liegt im HA-Konfigurationsverzeichnis. HA-Sicherungen erhalten eine konsistente Kopie. Das Entfernen der gesamten Integration löscht Buch, interne Sicherung und eigene Einstellungen dauerhaft; beim erneuten Hinzufügen entsteht ein neues Buch in der gewählten Währung. Neustart, Neuladen und Updates bewahren die Daten. Nur Programmdateien zu entfernen führt keine Bereinigung aus. HA-Historie, native Statistik, externe Sicherungen und Benutzerautomationen bleiben erhalten. Stelle passende Konfiguration und Buch gemeinsam wieder her.

Lokale Markenbilder werden ab **Home Assistant 2026.3** unterstützt. Die Symbolanzeige älterer Versionen beeinflusst die Abrechnung nicht.

## Häufige Fragen

| Problem | Prüfung |
| --- | --- |
| Integration fehlt nach Download | Integration installiert, Verzeichnis korrekt, Neustart erfolgt? Unter „Integration hinzufügen“ suchen |
| Karte fehlt | Integration laden, Frontend aktualisieren, Ressourcenadresse und JavaScript-Modul prüfen |
| **Keine zugänglichen Ladepunkte. Charge Tally konfigurieren oder Berechtigungen prüfen.** | Mindestens einen Punkt und Leserechte sicherstellen; Identitäten allein erzeugen keinen Live-Punkt |
| Keine automatischen Einträge | Leistungsquelle, vollständige Erkennung, Schalter, Schwellen und Bestätigungsdauer prüfen |
| „Erfassung manuell starten“ nicht verfügbar | Messquelle, Identitätsentität und Lade-/Reparaturzustand prüfen |
| Identitätsauswahl ändert laufenden Eintrag nicht | Auswahl gilt für den nächsten; für bestehende „Identität des Eintrags ändern“ nutzen |
| Alte Einträge trotz „Heute“ | Statistikzeitraum gilt nicht für „Einträge · alle Zeiträume“ |
| Nur bekannte Kosten oder leere native Kostenentität | Messlücken, Preisverlauf, Währung und Qualität in Details prüfen; nicht kostenlos |
| Veraltete Vorschau, Änderung oder Überschneidung | Aktualisieren, neu öffnen und Vorschau erstellen; überlappende Zeiten ändern, Prüfung nicht überspringbar |
| **Helfer des Ladepunkts müssen repariert werden** | HA-Reparatur öffnen und **Verwaltete Helfer reparieren** bestätigen; eigene fehlerhafte Helfer werden erneuert, Historie bleibt |
| Währung nach Konfigurationslöschung gesperrt | Archivierte Punkte und Buchungsdaten unter „Archivierte Daten verwalten“ prüfen |
| Normales Konto sieht Archive nicht oder kann nicht handeln | HA-Lese-/Steuerrechte prüfen, Archivverwaltung als Administrator; Kartenfilter erteilen keine Rechte |

> Screenshot-Platzhalter 15: Helfer-Reparaturmeldung und „Verwaltete Helfer reparieren“.

Brauchst du Hilfe? [Erstelle ein Issue](https://github.com/enecess/ha-charge-tally/issues) mit HA- und Charge-Tally-Version, Mess- und Preismodus, Schritten und tatsächlicher Meldung. Verberge private Informationen in Screenshots.

[MIT-Lizenz](LICENSE)

## NFC-Identitätsverknüpfungen

Administratoren öffnen **Einstellungen → Geräte & Dienste → Charge Tally → Konfigurieren → NFC-Identitätsverknüpfungen**. Registriere zuerst einen Tag in HA und wähle Tag, Ladepunkt sowie Geräte und Identitäten. Mehrere Gerätezuordnungen oder nur eine Standardidentität sind möglich. Je Tag/Ladepunkt-Paar entsteht eine verwaltete Automation; ein gemeinsamer Tag kann mehrere Punkte unabhängig steuern.

Gerätespezifische Zuordnungen haben Vorrang, andere Geräte verwenden den optionalen Standard. Ohne Standard geschieht nichts. Scannen wählt eine Identität aus. Vor Abschluss der Startbestätigung gilt sie für diese Ladung; Startzeit und Bestätigungsfortschritt bleiben erhalten. Bestehende Einträge behalten ihre Identität. Umbenennungen einer Identität bleiben gültig. Gelöschte Tags, Geräte oder Punkte und deaktivierte Identitäten sperren die ganze Verknüpfung bis zur Korrektur; es gibt keinen stillen Rückfall auf eine andere Identität.

Die Automation ist als von Charge Tally verwaltet gekennzeichnet. Bearbeite Zuordnungen in der Integration; HA bietet Ablaufverfolgung und Pausieren. Speichern behält die Pause bei. Eine native Änderung der HA-Entitäts-ID kann die Automation wieder einschalten; prüfe danach den Schalter. Externe Änderungen erfordern eine ausdrückliche Wiederherstellung, gelöschte Automationen eine Neuerstellung. Ausstehende Vorgänge nach Verbindungsabbrüchen verwenden dieselbe Automation.

Vor Wiederherstellung oder Neuerstellung lassen sich ungültige Zuordnungen korrigieren. Das Überschreiben externer Änderungen muss bestätigt werden. Ein ausstehender Löschvorgang kann abgebrochen werden, solange die Automation noch existiert; ihre aktuelle HA-Konfiguration bleibt erhalten.

Lösche Verknüpfungen vor dem Entfernen der Integration auf dieser Seite, um ihre Automationen aufzuräumen. Die Verwaltung benötigt Administratorrechte und geladene HA-Komponenten für Automation und Konfiguration. Sie beschreibt keine NFC-Tags und schaltet kein Ladegerät.
