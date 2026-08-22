from __future__ import annotations

from pydantic import BaseModel, Field


class ManualMessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4096)


class AcceleratedRunIn(BaseModel):
    sequence_code: str = "prepurchase_masterclass"
    time_scale: float = Field(default=1 / 720, gt=0, le=1)
    reset_technical_state: bool = True


class TrackingLinkIn(BaseModel):
    platform: str = Field(min_length=1, max_length=80)
    placement: str = Field(min_length=1, max_length=255)
    campaign: str | None = Field(default=None, max_length=255)
    target_sequence_code: str = "prepurchase_masterclass"


class ContentUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    body_source: str | None = Field(default=None, max_length=20000)
    labels: list[str] | None = None
    media_kind: str | None = Field(default=None, max_length=32)
    media_path: str | None = Field(default=None, max_length=2000)


class StepUpdateIn(BaseModel):
    position: int | None = Field(default=None, ge=1)
    delay_seconds: int | None = Field(default=None, ge=0)
    enabled: bool | None = None
    configuration: dict | None = None


class BroadcastIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=4096)
    segment: dict = Field(default_factory=lambda: {"status": "active"})
    scheduled_at: str | None = None
    media_kind: str | None = Field(default=None, max_length=32)
    media_path: str | None = Field(default=None, max_length=2000)
