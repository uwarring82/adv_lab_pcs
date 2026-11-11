# Oscilloscope dashboard

A local browser interface and HTTP API for the FP oscilloscopes. It follows the
Ocean Optics dashboard: Python/FastAPI, plain offline HTML/JS, vendored uPlot, one
instrument owner, simulator and Windows executable packaging. It runs separately
on **127.0.0.1:8778**, so both dashboards can run on the same PC.

This is an initial implementation. On 2026-11-11 Maxim reported successful USB
connection, initial capture, CSV export, acquisition controls and scale/timebase/
coupling changes on a **DS1054Z**. He also found stalled plot updates and unnecessarily
quoted CSV numbers in rc1. **rc2 fixes those two frontend issues; lab retesting is
pending.** Other models, including HAMEG HMO, have not yet been hardware-validated.

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

1. Use the VISA runtime and device drivers from the working PyVISA installation
   on the lab PC. Do not replace working USB drivers as part of dashboard setup.
2. Start `python run.py`. Close other programs holding the scope's USB/COM port.
3. Click **Find resources** and choose the intended scope, or enter its resource
   string. RIGOL uses `USB…::INSTR`; HAMEG RS-232 uses e.g. `ASRL3::INSTR` for COM3.
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
| RIGOL DS1054Z | 8 | RIGOL DS1000Z, USB | One device tested by Maxim on 2026-11-11; rc2 fixes await retest |
| RIGOL DS1074Z | 1 | RIGOL DS1000Z, USB | Pending hardware test |
| RIGOL DS1104Z | 1 | RIGOL DS1000Z, USB | Pending hardware test |
| RIGOL DS1202Z-E | 1 | RIGOL DS1000Z-E, USB, 2 channels | Pending hardware test |
| HAMEG HMO1022 | 3 | HMO, RS-232, 2 channels | Pending hardware test |
| HAMEG HMO3524 | 1 | HMO, RS-232, 4 channels | Pending hardware test, including firmware/header compatibility |
| HAMEG HM1022 | 1 | Unsupported | Confirm the nameplate; not automatically treated as HMO1022 |
| HAMEG HM1508 / HM1508-2 | 3 / 1 | Unsupported | Separate protocol and serial handshake need verification |
| LeCroy LT342, Tektronix TDS1002B, UNI-T UTD2025CL | 1 each | Unsupported | Outside the requested RIGOL/HAMEG starting scope |

DS1000Z Plus analog identities are also recognised. Do not add a model just because
its manufacturer matches: confirm its command dialect, transfer format and scaling.

## Controls and capture semantics

- **Run / Stop / Arm single / Auto setup** send the corresponding instrument command.
  Arm single returns after sending the command; it does not wait for a trigger.
  Auto setup can change timebase, vertical scales and trigger settings.
- **Apply changes** sends only edited settings, then reads settings back. Supported
  UI ranges are 5 ns–50 s/div and 1 mV–10 V/div; the scope may impose narrower limits
  or quantise values. The instrument error queue is checked and errors are shown.
  Multi-setting writes are not transactional: an instrument rejection can leave some
  changes applied. **Read settings** reconciles the UI with the instrument.
- **Capture screen** reads one selected channel's displayed samples. RIGOL uses
  normal/byte transfer (up to 1200 samples); HMO uses default screen points and
  little-endian REAL32 voltages (up to 20000 samples). Transfer settings are changed
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
| GET | `/api/resources` | Enumerate USB/serial VISA resources without probing |
| POST | `/api/connect` | Connect with `resource`, optional serial settings and `timeout_ms` |
| POST | `/api/simulator` | Explicitly switch to synthetic data |
| POST | `/api/disconnect` | Close device and invalidate cached capture |
| GET | `/api/settings?channel=1` | Read channel/timebase/acquisition state |
| POST | `/api/settings` | Set `channel` plus `timebase_s`, `scale_v` and/or `coupling` |
| POST | `/api/action` | `{"action":"run"}`; also `stop`, `single`, `autoscale` |
| POST | `/api/capture` | `{"channel":1}` → seconds, volts, metrics and metadata |
| GET | `/api/capture/{id}/csv` | Export cached capture; never acquire |

Requests with unsupported fields/values return 422; competing operations/stale
capture IDs return 409; unavailable VISA or failed communication returns 503.
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
transfers and the simulator. `manager.py` owns session lifetime, the device lock
and cached captures. `app.py` exposes the API and web files. Tests use synthetic
VISA replies with known time/voltage scaling, malformed/truncated blocks, serial
settings, unknown models, disconnects and concurrent requests.

On Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build_exe.ps1
```

The build runs tests, bundles the web assets and PyVISA/PyVISA-py backends, and writes
`dist\OscilloscopeDashboard.exe` plus license files. The executable keeps a console;
closing it stops the server. The PC still needs the same working VISA/USB/serial
drivers as source execution. CI builds and smoke-tests the executable as a separate
artifact; the spectrometer's release process is unchanged. A local Windows build
cannot be verified on macOS.

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
- [R&S HMO Compact SCPI Programmer's Manual, version 02](https://scdn.rohde-schwarz.com/ur/pws/dl_downloads/dl_common_library/dl_manuals/dl_user_manual/HMO72x_202x_SCPI_ProgrammersManual_en_02.pdf),
  acquisition/channel commands and sections 2.2.6–2.2.7. HMO REAL32 data are already
  volts; time points span the returned start/stop header values. This endpoint
  interpretation and HMO3524 firmware compatibility require the acceptance test.
- [libsigrok HAMEG HMO protocol source](https://github.com/sigrokproject/libsigrok/blob/master/src/hardware/hameg-hmo/protocol.c)
  confirms the shared HMO dialect and HMO3524 identification. No libsigrok code is
  copied or bundled.
- [PyVISA transfer documentation](https://pyvisa.readthedocs.io/en/stable/introduction/rvalues.html).

Instrument manuals and proprietary drivers are not bundled.
