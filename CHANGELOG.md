# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed (oscilloscope 0.1.0-rc6)

- Windows packaging includes the libusb runtime and checks it in the frozen
  executable without opening a device. The HMO3524 USB launcher and German test
  notes describe the USB default and remaining Windows device-driver prerequisite.
- Direct HO720 USB is the default connection for HMO3524 for now, based on the
  Mac hardware checks. RS-232 remains unverified: the current adapter test received
  no identity reply at 115200/8N1/no flow with LF, CRLF or CR endings.
- HMO3524 legacy SCPI dialect: a USB/FTDI byte probe on 2026-11-18 confirmed that
  `:HOR:MAIN:SCAL?` and its long form answer, while `:TIM:SCAL?` and
  `:TIMebase:SCALe?` do not; the error queue reports `-101,"Invalid character"`.
  This explains the failing command on the tested firmware; Windows RS-232 still
  needs a dashboard retest. The driver now selects the HMO3524's legacy horizontal
  and trace commands instead of the HMO Compact dialect.
- HMO3524 capture uses bounded `TRACe` byte blocks and separate X/Y scaling metadata.
  Run/Stop and single acquisition use the legacy acquisition/trigger commands.
  Auto setup is unavailable for this model; use its front panel. A private USB
  check verified settings and a framed 6000-sample transfer through this driver.
  On 2026-11-19, nonzero time/vertical positions and probe-factor conversions
  matched the scope's own CSV output, and single acquisition completed. Windows
  RS-232 still awaits acceptance.
- Direct HO720 USB connection through PyFtdi/libusb, without a COM port or VISA.
  Find resources lists only matching HO720 USB devices; Connect selects one and
  identifies it before control commands. Startup includes a settling pause and
  one identity-only timeout retry. Existing VISA USB/COM connections remain available.
  Serial diagnosis now compares both legacy horizontal query forms with the newer
  timebase forms and accepts either a COM port or direct HO720 USB resource.
  On 2026-11-18 the user confirmed browser capture working on the Mac after
  selecting the explicit status clear; cached exchanges show repeated framed
  6000-sample transfers and zero instrument errors. Subsequent Mac USB API checks
  verified controls/settings; Windows RS-232 acceptance remains pending.
- Collection error handling: recognize macOS USB timeout errno 60 (and other
  libusb timeout forms) within the read deadline, with fixed 100 ms serial polling
  matching the successful private check. Real disconnects still fail and close
  the session; only identity queries may be resent.
- Direct HO720 input handling uses quiet reads, matching the successful private
  checker, rather than hardware purges between requests. Connect never polls the
  SCPI error queue in a loop. "Clear previous status/errors on Connect" explicitly
  requests `*CLS` after supported identification; it is off by default.
- New errors name the operation and distinguish precheck, write and read failures.
  Cached status retains operation errors, and `GET /api/diagnostics` preserves a
  bounded exchange history even after connection failure/disconnect, without
  querying the instrument or requiring the optional file log. Identity replies
  are redacted from that history.
- Hardware checks on 2026-11-19 verified Stop/Run, repeatable stopped captures,
  exact CSV export, and timebase/scale/coupling changes through the API on the Mac.
  The tested HMO3524 selects the next standard timebase step when written its
  nominal value. The driver detects that readback and makes one verified
  correction using the preceding step; firmware that accepts the value directly
  keeps its normal setter. A communication failure never resends a settings write.
- Recognize USB timeouts hidden in PyFtdi's suppressed exception context as well
  as explicit causes. Reads copy only already cached bytes or fetch one new byte,
  so a subsequent packet timeout cannot discard an accumulated waveform prefix.

### Added (oscilloscope 0.1.0-rc5)

- Lab feedback on rc4 (2026-11-17): the HMO3524 (firmware 02.030-01.038-03.046, RS-232,
  115200 baud) still connects and identifies, then fails with a VISA timeout on `:TIM:SCAL?`.
  The cause is not known; rc5 adds tools to find it, not a confirmed fix.
- Serial diagnosis: "Diagnose serial link" opens the COM port, sends a fixed read-only
  sequence (`*IDN?`, `:TIM:SCAL?`, `:TIMebase:SCALe?`, `:SYST:ERR?`, `*CLS`, `*OPC?`,
  `:CHAN1:SCAL?`), records every received byte with its time and writes a text log
  (`oscilloscope-dashboard-logs` in the user's home folder). API: `POST /api/diagnose`.
- "Record serial log" for normal connections (`trace` in `POST /api/connect`) logs every
  command and reply as text and hex; `GET /api/log/latest` downloads the newest log.
- Serial only: unread input is discarded before each query (no stale bytes), an optional
  pause after `*IDN?` (`settle_ms`, default 0), and a timeout error that names baud rate,
  flow control and line ending and suggests the next settings to try. USB behaviour is
  unchanged.

### Changed (oscilloscope 0.1.0-rc4)

- Correct the dashboard, README and Windows test notes to record confirmed rc2 plot
  refresh and the HMO1022 COM-port report. HMO3524 still times out after identification;
  rc3 diagnostics are not a confirmed hardware fix. Driver behavior is unchanged.

### Changed (oscilloscope 0.1.0-rc3)

- Lab feedback on rc2 (2026-11-11): plot refresh confirmed; the HMO1022 works over its
  COM port; the HMO3524 connects and identifies but then times out.
- Connection: found VISA resources now appear in a drop-down list that fills the
  resource field (the free-text field stays for manual entry), replacing a datalist
  that only showed matches for the text already typed.
- Waveform cursor readout uses engineering units (for example 60 µs, 2.5 ns) instead of
  seconds that rounded microsecond times to zero.
- HMO3524 timeout diagnostics: an unanswered essential query now names the failing SCPI
  command in the error (also for waveform block reads); the acquisition-state query is
  optional and reports UNKNOWN instead of failing the connection. The cause of the
  timeout is not yet known; it needs one more test on the real instrument.
### Fixed (oscilloscope 0.1.0-rc2)

- Repeated captures and live preview now redraw the waveform immediately, retaining
  a user-selected zoom and updating the voltage range. Previously, new samples were
  loaded but the canvas stayed stale until Reset zoom.
- Browser CSV export leaves numeric samples unquoted and escapes text only where
  required. Added frontend regression checks, including real uPlot canvas tests.
- Recorded a lab user's initial DS1054Z hardware feedback and added HMO1022/HMO3524 serial
  testing instructions. Clarified that live preview does not record every trigger.

### Added

- Separate local oscilloscope dashboard on port 8778: explicit simulator, PyVISA
  USB/serial selection, RIGOL DS1000Z/Z-E and HAMEG HMO drivers, instrument controls,
  single-channel screen previews, statistics, CSV export and a student HTTP API.
  Includes protocol tests, Windows build script and CI coverage. Hardware validation
  is pending; HM1508/HM1508-2 and the inventory's HM1022 entry are not yet supported.

## [0.4.0] - 2026-10-02

From the first test with a real USB2000+ in the lab course.

### Added

- **Wavelength calibration**: fit λ(p) = c0 + c1·p + c2·p² + c3·p³ to reference lines
  picked in the spectrum (peak centre with sub-channel precision), or enter the
  coefficients. Factory and custom calibration are shown side by side for every line
  (position, deviation, RMS, largest difference); a custom calibration is highlighted
  above the plot and on the axis, saved per spectrometer and can be reset to factory.
  API: `/api/calibration` (GET, POST, DELETE) and `/api/calibration/preview`.
- **Example spectra** from the lab (Hg, Cd, He-Ne and Na lamps, sunlight, candle,
  smartphone screen, desk lamp, iodine absorption), usable without a spectrometer;
  with an example shown, the calibration panel is a practice mode.
- **Install driver** (Windows): installs Ocean Optics' signed WinUSB driver for a
  connected spectrometer without one (Code 28), after Windows' administrator prompt.
  Meant for students' own laptops. API: `POST /api/driver/install`.
- Zoom controls: x range fields and *Reset zoom*.

### Changed

- *Subtract dark* acts at once (no *Apply*), is available only with a stored dark
  spectrum, and a label shows the stored dark spectrum.
- Dark subtraction also applies to **measurements**; the dark spectrum's SEM is added in
  quadrature, and the CSV contains raw values and the dark spectrum too. Histograms stay
  raw counts.
- x axis: whole numbers without thousands separators ("1000", not "1.000"), and no
  2.5/25 steps.
- CSV files record the wavelength calibration.

## [0.3.1] - 2026-10-02

First feedback from a real lab PC: the dashboard fell back to the simulator without
saying why.

### Added

- **Connection diagnostics**: when no spectrometer is found, the dashboard explains why
  and what to do. It checks which seabreeze backend loads, which devices it sees and, on
  Windows, every Ocean Optics USB device with its driver (e.g. a Jungo driver from
  older Ocean software instead of WinUSB). Opens automatically, and from the badge;
  *Copy report* gives a text to send. Also at `GET /api/diagnostics`.
- **Retry hardware** (`POST /api/reconnect`): look for the spectrometer again, e.g.
  after closing OceanView, without restarting.
- The console window prints the spectrometer, or the reason for the fallback, at
  start-up.
- CI starts the executable without `--sim` and checks that the hardware backend loads
  and the USB query works inside the executable.

### Fixed

- The page could become wider than the window and be cut off on the right after the
  window was resized; the plots now follow their container's size.

## [0.3.0] - 2026-10-01: first public version

### Spectrometer dashboard (`spectro-dashboard/`)

- Local FastAPI service with a browser dashboard, packaged as a single Windows `.exe`.
- Live view: mean ± SEM over *scans to average*, dark subtraction, boxcar smoothing,
  streamed over a WebSocket.
- Statistical measurement: N raw scans → per-channel mean and standard error of the
  mean, with a progress indicator, as in the lab's earlier Jupyter workflow.
- Per-channel intensity histograms (`numpy` bin rules or a fixed number of bins).
- Notebook-style figures: saturation line at 2¹⁶, channel or wavelength axis, log
  scale, zoom that survives live updates, and a colour illustration of the visible
  spectrum (CIE 1931).
- CSV export and a documented HTTP API (`/docs`) for student scripts.
- Validation of every request against memory, time and detector limits; clear `422` /
  `409` errors, shown in the dashboard.
- Built-in simulator (same interface as the hardware backend) for development and
  teaching without a device.
- The web page is served with `Cache-Control: no-cache`, so browsers never show a
  stale page after the executable is updated.
- Test suite (pytest) with fake backends for statistics, limits and concurrency.

### Windows lab-PC setup (`windows/ocean-optics-setup/`)

- `Install.ps1`: USB power settings and driver installation (open-source
  python-seabreeze path or a vendor installer you provide), with a checked exit code
  for every step.
- `Verify.ps1`: finds the device, disables per-device USB power saving and acquires a
  test spectrum; distinct exit codes for working / not usable / not connected /
  untested.

### Project

- MIT license, third-party notices, contribution guide, security policy, citation
  file, documentation in `docs/` and a CI workflow.
- Tagged versions are published automatically as GitHub pre-releases (ZIP with the
  executable and its licenses, plus a SHA-256 checksum), downloadable without a
  GitHub account.
