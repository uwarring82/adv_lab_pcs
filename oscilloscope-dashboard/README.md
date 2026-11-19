# Oscilloscope dashboard

A local browser interface and HTTP API for the FP oscilloscopes. It follows the
Ocean Optics dashboard: Python/FastAPI, plain offline HTML/JS, vendored uPlot, one
instrument owner, simulator and Windows executable packaging. It runs separately
on **127.0.0.1:8778**, so both dashboards can run on the same PC.

This is an initial implementation. On 2026-11-11 a lab user reported successful USB
connection, initial capture, CSV export, acquisition controls and scale/timebase/
coupling changes on a **DS1054Z**. They also found stalled plot updates and unnecessarily
quoted CSV numbers in rc1. **Plot refresh is confirmed working with rc2; the HMO1022
also works over its COM port.** rc3 adds a resource drop-down, readable cursor units
and HMO3524 diagnostics; rc4 corrects the displayed hardware-test status. These new
features await a lab retest. **A USB/FTDI probe on 2026-11-18 confirmed that the
HMO3524 answers legacy `:HOR:MAIN:SCAL?` but not the newer `:TIM:SCAL?` used through
rc5. rc6 selects its legacy driver; a private USB check verified settings and a
6000-sample trace transfer whose calibration readings match the display. The new
direct USB browser capture was confirmed working on the Mac after an explicit
status clear; cached exchanges show repeated 6000-sample transfers without
instrument errors. Mac USB API controls/settings passed on 2026-11-19; single
acquisition completed, and time/voltage conversion at changed offsets and probe
factor matched the scope's CSV output. Windows RS-232 still needs acceptance.** Other models
await hardware validation.

## Start

Python 3.10+:

```bash
cd oscilloscope-dashboard
python -m venv .venv
```

Activate with `. .venv/bin/activate` on macOS/Linux or `.venv\Scripts\Activate.ps1`
in Windows PowerShell, then:

```bash
pip install -r requirements.txt
python run.py --sim
```

The browser opens <http://127.0.0.1:8778/>. Click **Capture screen**, or **Start live
preview**. The simulator badge and exported metadata identify synthetic data.
Options: `--sim`, `--port 8778`, `--no-browser`, `--visa-library PATH_OR_@py`.

Without `--sim`, the app starts disconnected. It never substitutes simulated data
for a missing or disconnected instrument. Select **Use simulator** explicitly to
switch to synthetic data.

## Hardware setup

**HMO3524 default for now: direct HO720 USB.** This path passed the Mac hardware
checks. Select **USB** as the active interface on the scope and choose **HO720 USB**
in the dashboard. RS-232 remains unverified: the current adapter test received no
identity reply at 115200/8N1/no flow with LF, CRLF or CR. Further RS-232 testing is
deferred; the USB results do not establish Windows driver compatibility.

1. For a VISA connection, use the runtime and device drivers from the working PyVISA installation
   on the lab PC. Do not replace working USB drivers as part of dashboard setup.
2. Start `python run.py`. Close other programs holding the scope's USB/COM port.
3. Click **Find resources** and choose the intended scope, or enter its resource
   string. RIGOL uses `USB…::INSTR`; HAMEG RS-232 uses e.g. `ASRL3::INSTR` for COM3.
   For direct HO720 USB, select **USB** on the scope and choose **HO720 USB** from
   the list. This route needs PyFtdi (in the requirements) and a libusb runtime,
   and works without a COM port or VISA. On macOS, `brew install libusb` supplies
   the runtime; leave a working VISA/COM setup in place for the Windows lab test.
   Enumeration does not send identification/control commands to every serial port.
4. For HAMEG, match the baud rate, handshake and terminators to the instrument's
   interface menu. The UI offers 9600–115200 baud, no/RTS-CTS/XON-XOFF flow control,
   and LF/CRLF/CR. Framing is 8-N-1. **115200 / no handshake / LF is an editable
   starting value, not a confirmed lab setting.** Per-I/O timeout defaults to 5 s
   and can be increased to 30 s for slow serial transfers.
5. Click **Connect**. Only `*IDN?` is sent until a supported identity is established.
   The UI then reads settings. Unknown models are rejected, with their handle closed.
6. Select an enabled channel and capture it. Enable channels, set probe attenuation,
   and configure triggers on the front panel. The app reads voltages according to
   the scope's existing probe setting.

`python run.py --visa-library @py` selects PyVISA-py, included with pySerial.
For USB using `@py`, additionally install `pyusb` and a working libusb backend;
the exact platform driver setup is separate from this app. A vendor/NI VISA
installation can instead be used through the default PyVISA backend. No VISA
runtime or proprietary device driver is distributed by this project.

Direct HO720 USB resources have the form `ftdi://0x0403:0xed72/1`; discovery adds
a USB bus/address selector to distinguish devices. After unplugging/reconnecting,
click **Find resources** again because the address may change. The direct route
accepts only this HO720 product ID, keeps replies LF-terminated, and rejects
XON/XOFF. USB baud/command-ending sweeps gave identical results on the tested unit;
RS-232 still needs matching settings on both ends. Opening waits 0.5 s, and only a
timed-out `*IDN?` is retried once. Communication failures never retry settings writes.
Connect does not poll the error queue. If previous diagnostics left instrument
errors, select **Clear previous status/errors on Connect** to send `*CLS` after
supported identification (`clear_status: true` in the API); this is off by default.
It clears status/errors without changing acquisition settings. New errors during
Run/capture are reported with their operation context. Generic
macOS USB timeout errno 60 is handled as a read timeout within the I/O deadline;
device loss still closes the connection. This includes timeouts hidden by PyFtdi's
suppressed exception context. Reads copy already cached bytes together and fetch
one new byte when the cache is empty, preserving data across packet timeouts.
No system driver is installed or replaced by the app. Windows packaging includes
the Python USB backend and the libusb runtime. The HO720 still needs a compatible
Windows device driver; an existing VCP/VISA driver may not provide direct PyFtdi
access. Keep working device drivers in place and coordinate changes with local IT.
`OscilloscopeDashboard.exe --check-usb-backend` checks the bundled runtime without
opening or enumerating a device. `Start-HMO3524-USB.cmd` starts the HMO3524 test;
select USB on the scope, then Find resources and choose HO720 USB.

Resource discovery failures explain driver/setup issues. A communication/framing
failure closes the instrument session and clears the server's cached capture;
reconnect after fixing the cause. The browser can still export its previously
displayed snapshot, with its original timestamp and instrument metadata.

## Inventory and coverage

Source: `FP-Osz_Zustand.xlsx`, sheet `Tabelle1`, rows 2–24, read on 2026-11-10.
The supplied local copy has **no yellow fills or conditional formatting**, so the
tested subset cannot be recovered. The later DS1054Z report is recorded separately.
The workbook is not modified or required at runtime. Original ambiguous model names
are retained rather than silently corrected.

| Inventory model | Count | Dashboard driver | Validation |
|---|---:|---|---|
| RIGOL DS1054Z | 8 | RIGOL DS1000Z, USB | Connection, capture and controls reported working; plot refresh confirmed with rc2 on 2026-11-11 |
| RIGOL DS1074Z | 1 | RIGOL DS1000Z, USB | Pending hardware test |
| RIGOL DS1104Z | 1 | RIGOL DS1000Z, USB | Pending hardware test |
| RIGOL DS1202Z-E | 1 | RIGOL DS1000Z-E, USB, 2 channels | Pending hardware test |
| HAMEG HMO1022 | 3 | HMO, RS-232, 2 channels | One unit works over its COM port (rc2, 2026-11-11) |
| HAMEG HMO3524 | 1 | Legacy HMO3524, direct HO720 USB by default; VISA USB/RS-232 paths available, 4 channels | Mac browser capture confirmed 2026-11-18; USB API controls/settings, repeatable stopped records, exact CSV export and single completion checked 2026-11-19. Nonzero offsets/probe-factor conversion matched instrument CSV; RS-232 and Windows acceptance pending |
| HAMEG HM1022 | 1 | Unsupported | Confirm the nameplate; not automatically treated as HMO1022 |
| HAMEG HM1508 / HM1508-2 | 3 / 1 | Unsupported | Separate protocol and serial handshake need verification |
| LeCroy LT342, Tektronix TDS1002B, UNI-T UTD2025CL | 1 each | Unsupported | Outside the requested RIGOL/HAMEG starting scope |

DS1000Z Plus analog identities are also recognised. Do not add a model just because
its manufacturer matches: confirm its command dialect, transfer format and scaling.

## Controls and capture semantics

- **Run / Stop / Arm single / Auto setup** send the corresponding instrument command.
  Arm single returns after sending the command; it does not wait for a trigger.
  Auto setup can change timebase, vertical scales and trigger settings. It is disabled
  for the legacy HMO3524; use the front panel. Single sets its trigger mode to single
  and starts acquisition; subsequent Run uses the current trigger mode.
- **Apply changes** sends only edited settings, then reads settings back. Supported
  UI ranges are 5 ns–50 s/div and 1 mV–10 V/div; the scope may impose narrower limits
  or quantise values. The instrument error queue is checked and errors are shown.
  Multi-setting writes are not transactional: an instrument rejection can leave some
  changes applied. **Read settings** reconciles the UI with the instrument.
  The tested legacy HMO3524 selects the next standard 1-2-5 timebase step when
  written a nominal value. If readback shows that specific behavior, the driver
  writes the preceding step once and verifies the result. Other readbacks receive
  no correction. Stop/Run, stopped-record repeatability, CSV export and changes to
  timebase/scale/coupling passed Mac USB API checks on 2026-11-19. Stopped HMO3524
  acquisition states include `COMP` (complete) and `BRE` (interrupted), as well as
  `STOP`; the displayed state preserves the instrument's reply.
- **Capture screen** reads one selected channel's displayed samples. RIGOL uses
  normal/byte transfer (up to 1200 samples); HMO1022 uses default screen points and
  little-endian REAL32 voltages. HMO3524 uses `TRACe` byte data with X/Y increment,
  origin and reference metadata (up to 20000 samples for both HMO drivers). Transfer settings are changed
  for reading, but a capture does not implicitly run, stop, reset or enable a channel.
- This is a **screen preview**, not full-memory or synchronised multi-channel
  acquisition. Metadata and samples can change while the scope is acquiring. For
  measurement work, wait for a completed trigger and a stable stopped trace. HMO
  peak-detect/envelope records are rejected rather than misinterpreted.
- **Live preview** polls after each completed transfer, with a 750 ms delay. Pause
  stops browser polling; it does not stop the scope. Controls are available after
  the current transfer completes. One device lock rejects competing requests (409).
  This is not a triggered-acquisition recorder: events occurring between polls are
  not saved. Shortening the polling delay would not guarantee lossless recording.
  For an isolated event, arm a single acquisition, wait for completion, then capture
  its stopped screen. Recording every trigger needs a separate acquisition mode
  with model-specific buffering, transfer-rate limits and overrun detection.
- The plot shows volts versus seconds with engineering prefixes, drag-to-zoom and
  reset. Mean, RMS (including DC) and peak-to-peak are calculated from the displayed
  samples, over the entire capture even when zoomed.
- **Export displayed CSV** exports exactly the browser's displayed samples, including
  timestamp, model, serial and simulation flag. It never reacquires. The API exports
  its latest cached capture by ID and returns 409 if another capture has replaced it.
  Numeric fields are unquoted; text is quoted only when CSV escaping requires it.

The UI works offline. Interactive `/docs` currently uses FastAPI's external Swagger
assets; offline scripts can use `/openapi.json` and the examples below.

## Student API

Interactive reference: <http://127.0.0.1:8778/docs>.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Service liveness, even while a transfer is busy |
| GET | `/api/status` | Connected identity, simulation flag, last capture ID and error |
| GET | `/api/diagnostics` | Cached direct-USB exchange history, including after failure; no instrument I/O |
| GET | `/api/resources` | Enumerate VISA USB/serial and HO720 USB resources without SCPI commands |
| POST | `/api/connect` | Connect with `resource`, optional serial settings and `timeout_ms` |
| POST | `/api/simulator` | Explicitly switch to synthetic data |
| POST | `/api/disconnect` | Close device and invalidate cached capture |
| GET | `/api/settings?channel=1` | Read channel/timebase/acquisition state |
| POST | `/api/settings` | Set `channel` plus `timebase_s`, `scale_v` and/or `coupling` |
| POST | `/api/action` | `{"action":"run"}`; also `stop`, `single`, `autoscale` |
| POST | `/api/capture` | `{"channel":1}` → seconds, volts, metrics and metadata |
| GET | `/api/capture/{id}/csv` | Export cached capture; never acquire |

Requests with unsupported fields/values return 422; competing operations/stale
capture IDs return 409; unavailable transport or failed communication returns 503.
Status retains instrument operation errors, including 422 precheck failures;
a subsequent successful settings read, change, action or capture clears that error.
The direct USB diagnostic cache records write/read phases, replies and framing
summaries with a bounded 80-event history. It remains available after disconnect
even with file logging off; identity replies are redacted. A write timeout is
reported as a write failure and never causes an automatic command resend.
All hardware calls run in worker threads. The CLI binds only to loopback; it is
intended for the person at the instrument PC, without remote authentication. Host
and origin checks reject cross-site browser control. There is no arbitrary SCPI
command endpoint.

Example using only Python's standard library, with the simulator or scope already
connected through the dashboard:

```python
import json
from urllib.request import Request, urlopen

base = "http://127.0.0.1:8778"
request = Request(base + "/api/capture", data=json.dumps({"channel": 1}).encode(),
                  headers={"Content-Type": "application/json"})
with urlopen(request) as response:
    data = json.load(response)
print(data["info"], data["rms_v"])
with urlopen(base + f"/api/capture/{data['id']}/csv") as response:
    with open("waveform.csv", "wb") as output:
        output.write(response.read())
```

## Development and Windows packaging

```bash
pip install -r requirements-dev.txt
python -m pytest -q
node --check web/app.js
node --test tests/test_frontend.cjs
```

For real-canvas regression checks, serve this directory locally with
`python -m http.server 8779 --bind 127.0.0.1`, then open
`http://127.0.0.1:8779/tests/frontend.html`. It reproduces the rc1 stale-canvas bug
using the bundled uPlot, then checks repainting, y-axis updates and preserved zoom.

`scope/backends.py` implements model identification, PyVISA setup, bounded binary
transfers and the simulator. `scope/ftdi.py` supplies direct HO720 USB discovery and
bounded text/binary reads. `manager.py` owns session lifetime, the device lock
and cached captures. `app.py` exposes the API and web files. Tests use synthetic
VISA replies with known time/voltage scaling, malformed/truncated blocks, serial
settings, unknown models, disconnects and concurrent requests. Direct USB tests use
the actual PyFtdi serial wrapper with USB creation/discovery replaced; a suite-wide
guard prevents real USB enumeration or claims, including on a developer's bench.

On Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build_exe.ps1
```

The build runs tests, bundles the web assets and PyVISA/PyVISA-py/PyFtdi backends, and writes
`dist\OscilloscopeDashboard.exe` plus license files. The executable keeps a console;
closing it stops the server. The PC still needs the same working VISA/USB/serial
drivers/libusb runtime as source execution. CI builds and smoke-tests the executable as a separate
artifact; the spectrometer's release process is unchanged. A local Windows build
cannot be verified on macOS.

## Connection diagnosis (HMO RS-232 or HO720 USB)

Under *Serial connection settings*: **Record serial log** writes every command and reply
(text and hex, with times) to `oscilloscope-dashboard-logs` in the user's home folder.
**Diagnose serial link / HO720 USB** (disconnected state, ASRL or direct HO720 resource) sends `*IDN?`,
`:HOR:MAIN:SCAL?`, `:HORizontal:MAIN:SCALe?`, `:TIM:SCAL?`,
`:TIMebase:SCALe?`, `:SYST:ERR?`, `*CLS`, `*OPC?` and `:CHAN1:SCAL?`, reads each reply byte
by byte, and stops after a silent `*IDN?`. **Download latest log** saves the file. The log
includes the instrument identity and should be reviewed before sharing. The HMO RS-232 parameters are set on the instrument under
SETUP → INTERFACE → PARAMETER (R&S HMO Compact SCPI manual, section 1.1.2); that manual
does not describe a handshake setting. Serial connections also discard unread input
before each query and accept a pause after `*IDN?` (0–2000 ms).
The diagnosis clears the error queue again at the end, so intentionally unsupported
comparison queries do not block a subsequent normal capture with stale errors.

## Lab acceptance test

For each supported model/firmware, record the `*IDN?` response, VISA resource,
VISA runtime, serial settings (if applicable) and outcome:

1. Connect and compare the reported timebase, scale and coupling to the front panel.
2. Apply one timebase/scale/coupling change, verify readback and front-panel behaviour.
3. Check Run, Stop, Arm single with an actual trigger, and Auto setup.
4. Capture a known calibration signal on every channel. Compare amplitude, DC
   offset and period with the instrument, including nonzero horizontal/vertical
   offsets and the correct probe attenuation. For HMO, verify header endpoint timing.
5. Export and compare CSV samples/units to the displayed preview. Check two-channel
   models do not offer CH3/CH4.
6. Unplug/reconnect, try a disabled channel and a wrong serial setting, and verify
   that errors are clear and simulated data never appears automatically.

## Protocol references

- [RIGOL programming manuals](https://www.rigolna.com/support/downloads/),
  DS1000Z and DS1000Z-E: `WAVeform` preamble and byte scaling, channel/timebase
  commands and acquisition control. RIGOL conversion is
  `t[i] = (i - xreference) * xincrement + xorigin`,
  `V[i] = (byte[i] - yorigin - yreference) * yincrement`.
- [HAMEG HMO3522/3524 SCPI Programmer's Manual, firmware 01.020 and later (manufacturer document, mirror)](https://collab.dvb.bayern/download/attachments/71998702/hmo3524-scpi_commands.pdf?api=v2&modificationDate=1482244152427&version=1),
  pp. 10, 12–15, 19 and 28–32: legacy horizontal, channel, acquisition, trigger and
  trace commands. Byte voltages use `(sample - yreference) * yincrement + yorigin`.
  Time uses `(index - xreference) * xincrement + xorigin`, following the metadata
  definitions. The manual's printed time formula has the opposite origin sign;
  its `XREFerence` query example also repeats `XORigin`. On 2026-11-19, all 6000
  converted sample times matched the instrument's own CSV at trigger delays of
  3.6 and 23.6 microseconds (`XREF=0`), supporting the implemented origin sign.
  Voltage conversion also matched CSV after a vertical-position and probe-factor change.
- [R&S HMO Compact SCPI Programmer's Manual, version 02](https://scdn.rohde-schwarz.com/ur/pws/dl_downloads/dl_common_library/dl_manuals/dl_user_manual/HMO72x_202x_SCPI_ProgrammersManual_en_02.pdf),
  acquisition/channel commands and sections 2.2.6–2.2.7. HMO REAL32 data are already
  volts; time points span the returned start/stop header values. This endpoint
  interpretation requires the HMO1022 acceptance test; this is not the legacy HMO3524 dialect.
- [libsigrok HAMEG HMO protocol source](https://github.com/sigrokproject/libsigrok/blob/master/src/hardware/hameg-hmo/protocol.c)
  lists HMO3524 with the newer HMO dialect. The tested legacy firmware instead
  answers the older horizontal commands; model identification alone does not prove
  command compatibility. No libsigrok code is
  copied or bundled.
- [PyVISA transfer documentation](https://pyvisa.readthedocs.io/en/stable/introduction/rvalues.html).

Instrument manuals and proprietary drivers are not bundled.
