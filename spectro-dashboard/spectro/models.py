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
    wavelengths: list[float]
    mean: list[float] = Field(description="Mean intensity per channel (counts).")
    sem: list[float] = Field(description="std(ddof=1) / sqrt(num_scans) per channel.")


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
