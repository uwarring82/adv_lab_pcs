"""Validated requests; all quantities use SI units."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Connection(RequestModel):
    resource: str = Field(min_length=1, max_length=256)
    baud_rate: Literal[9600, 19200, 38400, 57600, 115200] = 115200
    flow_control: Literal["none", "rts_cts", "xon_xoff"] = "none"
    termination: Literal["LF", "CRLF", "CR"] = "LF"
    timeout_ms: int = Field(default=5000, ge=100, le=30000)


class Settings(RequestModel):
    channel: int = Field(default=1, ge=1, le=4)
    timebase_s: float | None = Field(default=None, ge=5e-9, le=50)
    scale_v: float | None = Field(default=None, ge=0.001, le=10)
    coupling: Literal["DC", "AC", "GND"] | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if all(getattr(self, key) is None for key in ("timebase_s", "scale_v", "coupling")):
            raise ValueError("Provide at least one setting.")
        return self


class Action(RequestModel):
    action: Literal["run", "stop", "single", "autoscale"]


class Capture(RequestModel):
    channel: int = Field(default=1, ge=1, le=4)
