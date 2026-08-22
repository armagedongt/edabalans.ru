from __future__ import annotations

from pydantic import BaseModel, Field


class ManualMessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4096)


class AcceleratedRunIn(BaseModel):
    sequence_code: str = "welcome_intensive"
    time_scale: float = Field(default=1 / 720, gt=0, le=1)
    reset_technical_state: bool = True


class TrackingLinkIn(BaseModel):
    platform: str = Field(min_length=1, max_length=80)
    placement: str = Field(min_length=1, max_length=255)
    campaign: str | None = Field(default=None, max_length=255)
    target_sequence_code: str = "welcome_intensive"


class LinkRuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    target_kind: str = Field(default="bot_start", pattern="^(bot_start|channel_invite)$")
    route_kind: str = Field(default="root", pattern="^(root|published_step)$")
    target_sequence_code: str = Field(default="welcome_intensive", max_length=100)
    target_step_key: str | None = Field(default=None, max_length=120)
    tag_ids: list[str] = Field(default_factory=list)
    create_alias: bool = True


class LinkRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    status: str | None = Field(default=None, pattern="^(active|archived|disabled)$")
    route_kind: str | None = Field(default=None, pattern="^(root|published_step)$")
    target_sequence_code: str | None = Field(default=None, max_length=100)
    target_step_key: str | None = Field(default=None, max_length=120)
    tag_ids: list[str] | None = None


class AliasCreateIn(BaseModel):
    alias_kind: str = Field(default="short", pattern="^(short|legacy)$")
    token: str | None = Field(default=None, min_length=1, max_length=64)


class AliasStatusIn(BaseModel):
    status: str = Field(pattern="^(active|archived|disabled)$")


class UtmParseIn(BaseModel):
    url: str = Field(min_length=1, max_length=5000)


class UtmRuleIn(BaseModel):
    parameter_name: str = Field(min_length=1, max_length=128)
    raw_value: str = Field(max_length=2000)
    tag_id: str


class TagCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)


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


class StepPresentationIn(BaseModel):
    button_text: str = Field(min_length=1, max_length=64)


class BroadcastIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=4096)
    segment: dict = Field(default_factory=lambda: {"status": "active"})
    scheduled_at: str | None = None
    media_kind: str | None = Field(default=None, max_length=32)
    media_path: str | None = Field(default=None, max_length=2000)
