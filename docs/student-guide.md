# Student guide: using the spectrometer dashboard

This guide is for students working with an Ocean Optics USB spectrometer (for example a
USB2000+) in the lab course. You need no programming to take and save spectra; if you
want to automate measurements, see [Scripting](#scripting-your-own-measurements).

![Dashboard with a measurement, colour strip and histogram](images/dashboard.png)

## Starting and stopping

1. Double-click **SpectrometerDashboard.exe** on the lab PC (or the shortcut your
   instructor set up). A console window opens and your browser shows the dashboard at
   <http://127.0.0.1:8777/>.
2. The badge at the top right shows the spectrometer model and serial number. If it
   says **SIMULATED**, no spectrometer was found and you are looking at simulated
   data: check the USB cable, close other programs that use the spectrometer (e.g.
   OceanView) and restart. Hover over the badge to see the reason.
3. To stop, close the console window. Closing only the browser tab leaves the app
   running; open <http://127.0.0.1:8777/> again to get back.

## The screen

### Controls (top bar)

| Control | What it does |
|---|---|
| Integration time (ms) | Exposure time of one scan. Longer means more signal, but watch for saturation. |
| Scans to average | Live view: average this many scans into each displayed spectrum. The grey band then shows the standard error of that mean. |
| Boxcar half-width (px) | Live view: smooth over ±N neighbouring channels (0 = off). |
| Subtract dark | Live view: subtract the stored dark spectrum (see [Dark spectrum](#dark-spectrum)). |
| Apply | Sends the changed settings. Invalid settings are rejected with a red message and nothing changes. |
| Start live / Stop live | Continuous acquisition. |
| Single shot | Take one spectrum. |
| Store dark / Clear dark | Record or discard the dark spectrum. |
| Live CSV | Save the current live spectrum as a CSV file. |

Messages appear below the controls: grey when a setting was applied, amber for a
warning, red when something was rejected, always with the reason.

### Spectrum plot

- The **blue line** is the (mean) intensity per channel in detector counts. Channels 0
  and 1 are hidden in the plot, following the lab's earlier analysis notebooks; they
  are still included in the CSV files.
- The **red line** is the saturation level of the 16-bit detector (2¹⁶ counts).
  If a peak touches it, the measurement at that wavelength is invalid: reduce the
  integration time.
- The **grey band** is ± one standard error of the mean (switch it off with *±SEM*).
  It is only visible when you average several scans and zoom in.
- **Channel / Wavelength** switches the horizontal axis between pixel number and
  calibrated wavelength.
- **Log y** uses a logarithmic intensity axis, useful for weak features next to strong
  lines.
- **Autoscale y** fits the vertical axis to the data you are looking at (otherwise it
  is fixed to 0 … 2¹⁶).
- **Zoom**: drag across the plot. The zoom is kept while live data updates. Double-click
  to reset.
- **Click a channel** to select it (orange dashed line) and show its histogram.

### Visible-spectrum strip

The coloured strip under the plot shows roughly what the spectrum would look like to
the eye: each wavelength in its colour (CIE 1931 colour matching), brighter where the
intensity is higher. The brightest line in the current view sets full brightness, so
zooming in changes the strip. Wavelengths outside the visible range (below 380 nm or
above 780 nm) are shown grey and marked UV / IR. Switch it off with *Color*.

## Measurements with statistics

The live view is for aligning and looking. For data you want to analyse, use
**Measure**:

1. Set the integration time (and apply it).
2. Enter the **Number of scans** N (200 by default) and click **Measure**. A progress bar
   shows how far it is; it takes N × integration time.
3. The plot then shows the **mean** of the N scans per channel, with the **standard
   error of the mean** `SEM = σ / √N` as the grey band (σ = sample standard deviation
   of the N scans).
4. **Save CSV** stores channel, wavelength, mean and SEM for every channel.

Measurements always use the **raw counts** of the detector: no dark subtraction and no
smoothing, so the statistics are those of the detector itself. If you need a dark
correction, measure a dark spectrum the same way (light blocked) and subtract it in
your analysis.

### Histogram of one channel

After a measurement, click any channel in the plot (or type its number) to see the
**distribution of its N readings**, with mean, standard deviation σ and SEM. Try:

- Compare a channel on a strong line with one on the dark background: how do σ and
  the shape of the distribution differ?
- The variance σ² of a channel grows with its mean signal (shot noise). Plotting σ²
  against the mean for many channels lets you estimate the detector's gain and read
  noise.
- Watch what happens to a channel that is saturated.

## Dark spectrum

The dark spectrum is what the detector reads without light (electronic offset and dark
current). To use it in the live view:

1. Block the light path (cap the fibre, or switch off the source).
2. Click **Store dark**. It averages *Scans to average* scans at the current
   integration time.
3. Unblock the light, tick **Subtract dark** and click **Apply**.

A dark spectrum only fits the integration time it was taken at. If you change the
integration time, it is discarded automatically, subtraction switches off, and an
amber message asks you to store a new one.

## Limits you may run into

- Live averaging is limited to 30 s per spectrum (scans × integration time). For longer
  runs, set *Scans to average* to 1 and use **Measure**.
- A measurement can have up to 5000 scans and last up to 30 minutes.
- Only one measurement runs at a time. While it runs, the other controls are locked.

The full list is in the [API reference](api.md#limits).

## Scripting your own measurements

Everything on the page is also available over HTTP. The *Scripting* box on the page
shows a starting point; the link *Open API docs* leads to an interactive reference where
you can try every request. A minimal Python script:

```python
import requests
import matplotlib.pyplot as plt

base = "http://127.0.0.1:8777"
requests.post(f"{base}/api/config", json={"integration_time_ms": 100}).raise_for_status()
m = requests.post(f"{base}/api/measurement", json={"num_scans": 100}).json()

plt.errorbar(m["wavelengths"], m["mean"], yerr=m["sem"], fmt="-", ecolor="gray")
plt.xlabel("Wavelength (nm)")
plt.ylabel("Intensity (counts)")
plt.show()
```

See the [API reference](api.md) for all endpoints and
[`examples/student_client.py`](../spectro-dashboard/examples/student_client.py) for a
complete example with a histogram.
