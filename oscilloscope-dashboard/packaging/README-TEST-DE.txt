Oscilloscope Dashboard 0.1.0-rc5 - Windows-Test nach dritter Rueckmeldung

Voraussetzung: Windows 10/11, 64 Bit (x64).
Python muss nicht installiert sein. Fuer ein echtes RIGOL werden weiterhin eine
64-Bit-VISA-Laufzeit und der passende USB-Treiber benoetigt. Am besten dieselbe
VISA-/Treiberinstallation verwenden, mit der der PyVISA-Test bereits funktioniert.
Die ZIP installiert oder ersetzt keine Geraetetreiber.

START
1. ZIP vollstaendig in einen Ordner entpacken.
2. Ohne Geraet: Simulator.cmd doppelklicken.
   Mit RIGOL: Scope per USB verbinden, andere Steuerprogramme schliessen,
   dann Start-Rigol.cmd oder OscilloscopeDashboard.exe doppelklicken.
3. Der Browser oeffnet http://127.0.0.1:8778/ automatisch.
   Falls nicht, diese Adresse manuell oeffnen. Das Konsolenfenster offen lassen.
4. Find resources -> USB...::INSTR auswaehlen -> Connect.
   Modell und Seriennummer mit dem angeschlossenen Scope vergleichen.
5. Einen am Scope eingeschalteten Kanal auswaehlen -> Capture screen.
   Mit Start live preview wird die Vorschau regelmaessig aktualisiert.
6. Export displayed CSV speichert genau die angezeigten Daten in Sekunden/Volt.
7. Beenden: Konsolenfenster schliessen oder dort Strg+C druecken.

RIGOL-MODELLE
DS1054Z, DS1074Z, DS1104Z (auch Plus), DS1202Z-E.
Ein Laborbenutzer hat Verbindung, erste Aufnahme und Steuerfunktionen mit einem DS1054Z
erfolgreich getestet. rc2 behebt die verzoegerte Plot-Aktualisierung bei weiteren
Aufnahmen und exportiert Zahlen ohne Anfuehrungszeichen. rc3 zeigt gefundene
Ressourcen in einer Auswahlliste und die Cursor-Zeit in passenden Einheiten (z. B. us, ns).
Die Plot-Aktualisierung mit rc2 wurde im Labor bestaetigt. rc4 korrigiert die
Hardware-Testhinweise; die Treiber entsprechen rc3.

HMO3524 PER RS232: DIAGNOSE-ABLAUF (rc5, 5 Schritte, ca. 10 Minuten)
Der HMO3524 meldet sich mit *IDN?, antwortet danach aber nicht auf :TIM:SCAL?.
Die Ursache ist unbekannt; rc5 schreibt ein Protokoll, mit dem wir sie finden koennen.
1. Am Geraet: SETUP -> INTERFACE -> RS-232 waehlen, dann PARAMETER. Baudrate, Datenbits,
   Parity, Stopbits und (falls vorhanden) Handshake notieren oder fotografieren.
   Ist kein Handshake-Eintrag da, ist das in Ordnung; bitte vermerken "nicht vorhanden".
2. Im Browser: Serial connection settings aufklappen. Baud rate wie am Geraet (115200),
   Flow control None, Line ending LF, Timeout 5. Die ASRL...::INSTR des COM-Ports waehlen
   (Disconnect, falls verbunden). Dann "Diagnose serial link" klicken und ca. 20 s warten.
3. Wiederholen mit Baud rate 9600 am Geraet UND im Browser (Geraet zuerst aendern).
   Danach wieder auf 115200 zurueckstellen, falls 9600 nichts aendert.
4. Mit 115200: Record serial log anhaken, Pause after *IDN? auf 500, Connect klicken.
   Die Fehlermeldung vollstaendig kopieren. Falls Flow control am Geraet einstellbar ist,
   Schritt 2 zusaetzlich mit RTS / CTS wiederholen (an beiden Enden gleich).
5. "Download latest log" klicken (oder die Dateien aus dem Ordner
   %USERPROFILE%\oscilloscope-dashboard-logs senden: alle diagnose-*.txt und serial-log-*.txt)
   und zusammen mit den Notizen aus Schritt 1 und der Fehlermeldung zurueckschicken.

HAMEG-TEST
Ein HMO1022 funktioniert laut Laborrueckmeldung ueber seinen COM-Port.
Beim HMO3524 ist der Timeout nach der Erkennung weiterhin ungeloest.
Start-Rigol.cmd startet auch diese Treiber; die Auswahl erfolgt nach *IDN?.
Im Browser unter Serial connection settings Baudrate, Handshake und Zeilenende
passend zum Geraet einstellen (8-N-1), dann ASRL...::INSTR auswaehlen und verbinden.
Die Vorgaben 115200 / kein Handshake / LF sind nicht fuer die Laborgeraete bestaetigt.
Bitte Modell, Firmware, COM-Port und funktionierende Einstellungen zurueckmelden.
Bekanntes Problem: Der HMO3524 verbindet, antwortet danach aber nicht rechtzeitig. rc3
nennt in der Fehlermeldung den SCPI-Befehl, der keine Antwort bekam; bitte die
vollstaendige Meldung, die Firmware und Schnittstelle/Baudrate/Handshake am Geraet melden.
HM1508/HM1508-2 werden noch nicht unterstuetzt; bei HM1022 bitte zuerst den genauen
Modellnamen am Typenschild pruefen. Nicht einfach als HMO1022 behandeln.

KURZER TEST AM GERAET
- Kalibriersignal anschliessen; Tastkopf und Tastkopffaktor am Scope korrekt setzen.
- Modell, Seriennummer, Firmware und VISA-Installation notieren.
- Zeitbasis, V/div und Kopplung mit der Frontplatte vergleichen.
- Jeweils eine Einstellung aendern und die Wirkung am Scope pruefen.
- Run und Stop pruefen. Arm single wartet auf einen Trigger; danach Capture screen.
- Auto setup veraendert auch Trigger- und Kanaleinstellungen.
- Amplitude, Offset und Periodendauer der Vorschau mit dem Scope vergleichen.
- Alle Kanaele testen; CSV pruefen; Kabel abziehen und erneut verbinden.

Die Vorschau liest nur Bildschirmdaten eines Kanals, nicht den gesamten Speicher.
Fuer eine stabile Kurve erst eine abgeschlossene Aufnahme am Scope stoppen.
Pause live preview stoppt nur die Browserabfrage, nicht die Erfassung am Scope.
Die Vorschau ist KEINE lueckenlose Aufzeichnung aller Trigger: Zwischen zwei
Abfragen auftretende Aufnahmen werden nicht gespeichert. Eine schnellere Abfrage
allein verhindert das nicht. Fuer ein einzelnes Ereignis Arm single verwenden,
den abgeschlossenen Trigger abwarten und danach Capture screen anklicken.
SIMULATED DATA kennzeichnet kuenstliche Daten; bei Verbindungsfehlern wird niemals
automatisch auf den Simulator umgeschaltet.

WENN ETWAS NICHT FUNKTIONIERT
- Konsolenmeldung und Browserfehlermeldung notieren oder fotografieren.
- Bei fehlendem VISA: die zuvor funktionierende VISA-/USB-Installation pruefen.
- Bei belegtem Port: andere Scope-Software schliessen.
- Bei belegtem Web-Port: OscilloscopeDashboard.exe --port 8779 starten.
- Bei einem Fehler beim Programmstart Start-Rigol.cmd verwenden; das Fenster
  bleibt dann offen und zeigt den Fehler.
- Die EXE ist nicht digital signiert. Windows kann eine Herausgeberwarnung zeigen.
  Keine Sicherheitsrichtlinien deaktivieren; bei einer Sperre die lokale IT nutzen.

Bitte Testbericht mit Modell/Firmware, Windows-Version, VISA-Laufzeit, USB-Ressource,
getestetem Kanal, Schritten, Soll-/Ist-Verhalten und Fehlermeldung zurueckgeben.
Version abfragen: OscilloscopeDashboard.exe --version

Quellcode und Releases: https://github.com/uwarring82/adv_lab_pcs
Lizenzdateien bitte zusammen mit dem Programm weitergeben.
