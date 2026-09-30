"""Example: control the spectrometer and grab data from your own script.

The dashboard app exposes a plain HTTP API on the lab PC, so you can automate
measurements in Python (or any language). Start the dashboard, then run this.

    pip install requests matplotlib
    python student_client.py                       # one live spectrum
    python student_client.py --measure 200         # N-scan measurement + histogram

List index = channel number throughout the API.
"""
from __future__ import annotations

import argparse
import csv

import requests


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--integration", type=float, default=100.0, help="integration time (ms)")
    ap.add_argument("--average", type=int, default=5, help="live: scans averaged per spectrum")
    ap.add_argument("--measure", type=int, default=0, metavar="N",
                    help="take an N-scan statistical measurement instead of one live spectrum")
    ap.add_argument("--channel", type=int, default=None, help="channel for the histogram")
    ap.add_argument("--out", default="my_spectrum.csv")
    args = ap.parse_args()

    base = f"http://{args.host}:{args.port}"

    # 1. Configure the acquisition.
    requests.post(f"{base}/api/config", json={
        "integration_time_ms": args.integration,
        "scans_to_average": args.average,
    }).raise_for_status()

    # 2. Acquire: either one live spectrum, or N raw scans -> mean and SEM per channel.
    if args.measure:
        r = requests.post(f"{base}/api/measurement", json={"num_scans": args.measure})
        r.raise_for_status()
        m = r.json()
        wl, mean, sem = m["wavelengths"], m["mean"], m["sem"]
        print(f"Measured N={m['num_scans']} scans on {m['model']}.")
    else:
        s = requests.get(f"{base}/api/spectrum").json()
        wl, mean, sem = s["wavelengths"], s["intensities"], s["sem"]
        print(f"Got one live spectrum ({len(wl)} channels) from {s['model']}.")

    peak = max(range(2, len(mean)), key=mean.__getitem__)  # skip channels 0-1
    print(f"Peak: channel {peak}, {wl[peak]:.2f} nm, {mean[peak]:.1f} +- {sem[peak]:.1f} counts")

    # 3. Save it yourself (or fetch /api/spectrum.csv or /api/measurement.csv directly).
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["channel", "wavelength_nm", "mean_counts", "sem_counts"])
        w.writerows((i, x, y, e) for i, (x, y, e) in enumerate(zip(wl, mean, sem)))
    print(f"Wrote {args.out}")

    # 4. Per-channel noise statistics (needs a measurement).
    hist = None
    if args.measure:
        ch = peak if args.channel is None else args.channel
        hist = requests.get(f"{base}/api/measurement/histogram", params={"channel": ch}).json()
        print(f"Channel {ch}: mean {hist['mean']:.1f}, std {hist['std']:.2f}, "
              f"SEM {hist['sem']:.2f} counts over {hist['num_scans']} scans")

    # Optional quick look, in the style of the lab notebook:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return
    ch_axis = list(range(len(mean)))[2:]
    fig, axes = plt.subplots(1, 2 if hist else 1, figsize=(14, 4), squeeze=False)
    ax = axes[0][0]
    ax.errorbar(ch_axis, mean[2:], yerr=sem[2:], fmt="-", ecolor="gray", elinewidth=1, capsize=2)
    ax.axhline(2 ** 16, lw=3, color="red")
    ax.set(xlabel="Channel number", ylabel="Intensity (a.u.)", ylim=(0, 2 ** 16))
    ax.grid(True)
    if hist:
        e = hist["bin_edges"]
        ax2 = axes[0][1]
        ax2.bar(e[:-1], hist["counts"], width=[b - a for a, b in zip(e, e[1:])],
                edgecolor="black", align="edge", alpha=0.75)
        ax2.set(xlabel="Intensity (a.u.)", ylabel="Counts",
                title=f"Intensity Histogram for Channel {hist['channel']}")
        ax2.grid(True)
    fig.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
