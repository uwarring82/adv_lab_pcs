"""Pydantic request/response models. These also define the student-facing API
schema shown at /docs."""
from __future__ import annotations

from pydantic import BaseModel, Field

from .acquisition import MAX_LIVE_SCANS, MAX_SCANS


class ConfigUpdate(BaseModel):
    integration_time_ms: float | None = Field(
        None, gt=0, description="Integration (exposure) time in milliseconds. Changing it "
        "discards the dark spectrum.")
    scans_to_average: int | None = Field(
        None, ge=1, le=MAX_LIVE_SCANS,
        description="Live view: number of scans averaged (mean +- SEM) per spectrum. When "
        "averaging (2 or more), scans_to_average x integration time is limited to 30 s.")
    boxcar_width: int | None = Field(
        None, ge=0, description="Live view: boxcar smoothing half-width in pixels (0 = off; "
        "at most (pixels - 1) / 2).")
    subtract_dark: bool | None = Field(
        None, description="Live view: subtract the dark spectrum; needs one taken at the "
        "current integration time.")


class Spectrum(BaseModel):
    timestamp: float
    model: str
    wavelengths: list[float] = Field(description="Wavelength per channel (nm); list index = channel number.")
    intensities: list[float] = Field(description="Mean intensity per channel (counts).")
    sem: list[float] = Field(description="Standard error of the mean per channel (0 if one scan).")
    config: dict


class MeasurementRequest(BaseModel):
    num_scans: int = Field(
        200, ge=2, le=MAX_SCANS,
        description="Number of raw scans to take (the lab notebook uses 200).")


class Measurement(BaseModel):
    id: int = Field(description="Increases with every completed measurement.")
    timestamp: float
    model: str
    num_scans: int
    config: dict
    calibration: str = Field(description="Wavelength calibration in use: 'factory' or 'custom'.")
    wavelengths: list[float]
    mean: list[float] = Field(description="Mean intensity per channel (counts), minus the dark "
                              "spectrum if dark_subtracted.")
    sem: list[float] = Field(description="std(ddof=1) / sqrt(num_scans) per channel; with dark "
                             "subtraction combined in quadrature with the dark spectrum's SEM.")
    dark_subtracted: bool = False
    raw_mean: list[float] | None = Field(None, description="Only with dark subtraction: mean before subtracting.")
    raw_sem: list[float] | None = None
    dark: list[float] | None = Field(None, description="Only with dark subtraction: the dark spectrum used.")
    dark_sem: list[float] | None = None
    dark_scans: int | None = None


class CalibrationLine(BaseModel):
    pixel: float = Field(description="Channel (pixel) of the line; may be fractional (peak centre).")
    wavelength_nm: float = Field(description="Known wavelength of the line, e.g. from a Hg lamp.")


class CalibrationRequest(BaseModel):
    coefficients: list[float] | None = Field(
        None, description="c0..c3 of lambda(p) = c0 + c1 p + c2 p^2 + c3 p^3. If given, the lines "
        "are only kept for comparison.")
    lines: list[CalibrationLine] | None = Field(
        None, description="Reference lines to fit (without coefficients).")
    order: int | None = Field(None, ge=1, le=3, description="Polynomial order of the fit "
                              "(default: number of lines - 1, at most 3).")


class CalibrationPreview(BaseModel):
    lines: list[CalibrationLine] = Field(description="Reference lines to fit.")
    order: int | None = Field(None, ge=1, le=3)
    reference: list[float] = Field(description="Coefficients to compare the fit with, e.g. the "
                                   "calibration an example spectrum was recorded with.")
    pixels: int = Field(2048, ge=4, le=100_000, description="Number of channels of that spectrometer.")


class Histogram(BaseModel):
    measurement_id: int
    channel: int
    wavelength_nm: float
    num_scans: int
    counts: list[int]
    bin_edges: list[float]
    bins_capped: bool = Field(description="True if the bin rule asked for more than the maximum number of bins.")
    mean: float
    std: float
    sem: float
