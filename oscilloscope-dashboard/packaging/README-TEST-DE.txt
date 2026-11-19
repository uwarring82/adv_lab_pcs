Oscilloscope Dashboard 0.1.0-rc6 - HMO3524 direkt per HO720 USB

Windows-Testversion fuer Windows 10/11 x64. Python muss nicht installiert sein.
Die ZIP enthaelt die Python-USB-Bibliotheken und die libusb-Laufzeit. Sie installiert
oder ersetzt keine Geraetetreiber. Der physische Windows-USB-Test steht noch aus;
Aufnahmen, Steuerung und Skalierung wurden am HMO3524 unter macOS geprueft.

HMO3524: STANDARDVERBINDUNG USB
1. ZIP vollstaendig entpacken und die alte Dashboard-Version schliessen.
2. Scope direkt mit einem USB-Kabel verbinden; am Scope USB als aktive
   Schnittstelle waehlen. Der USB-RS232-Adapter wird dafuer nicht benoetigt.
3. Andere Scope-Programme schliessen und Start-HMO3524-USB.cmd starten.
   Der Browser oeffnet http://127.0.0.1:8778/. Das Konsolenfenster offen lassen.
4. Find resources -> HO720 USB auswaehlen -> Connect. Modell/Seriennummer mit
   dem Scope vergleichen. Flow control None und Line ending LF belassen.
5. CH1 am Scope einschalten, Kalibriersignal anschliessen, Capture screen klicken.
   Zeitbasis, Spannung und Kurve mit dem Scope vergleichen. Export displayed CSV
   speichert genau die angezeigten Samples in Sekunden und Volt.

Falls fruehere Diagnosen Fehler hinterlassen haben: Disconnect, Serial connection
settings oeffnen, Clear previous status/errors on Connect (*CLS) bewusst auswaehlen,
dann Connect. Dies loescht Status/Fehler, aber keine Aufnahmeeinstellungen.
Normales Verbinden fragt keine Fehlerliste in einer Schleife ab.

WINDOWS-USB-TREIBER
Die enthaltene libusb-DLL ersetzt keinen Windows-Geraetetreiber. Der direkte
PyFtdi-Weg braucht einen libusb-kompatiblen Treiber fuer das HO720; ein vorhandener
VCP-/VISA-Treiber kann dafuer ungeeignet sein. Keine funktionierende Installation
ungeprueft ersetzen. Wenn kein HO720 USB erscheint: USB-Aktivierung, Geraetename
und Treiber im Geraete-Manager notieren und mit der lokalen IT abstimmen.
Die bisherigen VISA-/COM-Pfade bleiben fuer vorhandene funktionierende Setups nutzbar.

Die Laufzeit kann ohne Geraetezugriff geprueft werden:
  OscilloscopeDashboard.exe --check-usb-backend
Die Versionsabfrage lautet:
  OscilloscopeDashboard.exe --version

GEPRUEFT UND NOCH OFFEN
Am Mac mit HMO3524/HO720 geprueft: Einstellungen, 6000-Sample-Aufnahmen,
Run/Stop, wiederholte gestoppte Aufnahmen, exakter CSV-Export, Zeitbasis-/V/div-/
Kopplungsaenderungen und abgeschlossene Single-Aufnahme. Zeit-/Spannungswerte
stimmen auch nach horizontaler/vertikaler Verschiebung und Aenderung des
Tastkopffaktors mit dem Scope-CSV ueberein (innerhalb dessen Rundung).
Der aeltere HMO3524 verwendet HORizontal/TRACe statt des neueren TIMebase-Befehls.
Der getestete Zeitbasis-Setter waehlt die naechste 1-2-5-Stufe. Nur bei genau diesem
Rueckleseverhalten korrigiert der Treiber einmal und prueft das Ergebnis.
Gestoppte Aufnahmen koennen als COMP (vollstaendig) oder BRE (abgebrochen) erscheinen.
RS232 bleibt unbestaetigt; weitere RS232-Tests sind zurueckgestellt.

BEDIENUNG
- Run/Stop steuert das Scope. Pause live preview pausiert nur die Browserabfrage.
- Arm single setzt den Triggermodus auf Einzelaufnahme und wartet auf dessen
  Trigger. Danach Capture screen. Run verwendet den aktuellen Triggermodus.
- Auto setup am HMO3524 an der Frontplatte ausfuehren; im Dashboard deaktiviert.
- Die Vorschau liest einen Kanal des Bildschirms, nicht den gesamten Speicher.
  Live preview ist keine lueckenlose Aufzeichnung aller Trigger.
- SIMULATED DATA kennzeichnet kuenstliche Daten. Bei Verbindungsfehlern wird
  niemals automatisch auf den Simulator gewechselt.
- Beenden: Konsolenfenster schliessen oder dort Strg+C druecken.

RIGOL UND WEITERE HAMEG-GERAETE
Fuer RIGOL die vorhandene funktionierende VISA-/USB-Installation beibehalten,
Scope anschliessen, Start-Rigol.cmd starten, Find resources und USB...::INSTR waehlen.
DS1054Z wurde im Labor geprueft; DS1074Z, DS1104Z/Plus und DS1202Z-E sind erkannt,
aber noch nicht am Geraet getestet. Ein HMO1022 funktioniert laut Laborrueckmeldung
ueber seinen COM-Port. HM1508/HM1508-2 und die ungeklaerte Bezeichnung HM1022
werden nicht automatisch als unterstuetzte Modelle behandelt.
Ohne Geraet kann Simulator.cmd gestartet werden.

FEHLERBERICHT
Vollstaendige Browser-/Konsolenmeldung, Modell/Firmware, Windows-Version und
Geraetetreiber notieren. Record serial log VOR Connect aktivieren; Download latest
log liefert das Protokoll. Cached connection diagnostics zeigt die letzten USB-
Austausche auch ohne Dateilog; diese Abfrage sendet keine Geraetebefehle.
Dateilogs liegen in %USERPROFILE%\oscilloscope-dashboard-logs und enthalten die
Geraeteidentitaet. Bei belegtem Port andere Scope-Programme schliessen; bei belegtem
Web-Port OscilloscopeDashboard.exe --port 8779 verwenden.
Die EXE ist nicht signiert; bei einer Windows-Sperre die lokale IT hinzuziehen.

LIZENZEN
LICENSE.txt, THIRD_PARTY_NOTICES.md, THIRD_PARTY_LICENSES.txt und LIBUSB-LICENSE.txt
zusammen mit dem Programm weitergeben. sources/ enthaelt den genauen libusb- und
libusb-package-Quellcode; LIBUSB-SOURCE.txt erklaert Zuordnung und Austausch der DLL.
Quellcode und Releases: https://github.com/uwarring82/adv_lab_pcs
