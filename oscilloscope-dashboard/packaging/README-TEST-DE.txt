Oscilloscope Dashboard 0.1.0-rc2 - Windows-Test nach erster Rueckmeldung

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
Maxim hat Verbindung, erste Aufnahme und Steuerfunktionen mit einem DS1054Z
erfolgreich getestet. rc2 behebt die verzoegerte Plot-Aktualisierung bei weiteren
Aufnahmen und exportiert Zahlen ohne Anfuehrungszeichen. Bitte erneut testen.

HAMEG-TEST
HMO1022 und HMO3524 koennen jetzt ebenfalls versuchsweise ueber RS-232 getestet
werden. Start-Rigol.cmd startet auch diese Treiber; die Auswahl erfolgt nach *IDN?.
Im Browser unter Serial connection settings Baudrate, Handshake und Zeilenende
passend zum Geraet einstellen (8-N-1), dann ASRL...::INSTR auswaehlen und verbinden.
Die Vorgaben 115200 / kein Handshake / LF sind nicht fuer die Laborgeraete bestaetigt.
Bitte Modell, Firmware, COM-Port und funktionierende Einstellungen zurueckmelden.
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
