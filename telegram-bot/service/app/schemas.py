from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class PublicMessengerStartLinkIn(BaseModel):
    """Browser-safe input for issuing an attributed direct bot deep link."""

    model_config = ConfigDict(extra="forbid")

    messenger: Literal["tg", "max"]
    entry: Literal["button", "qr"] = "button"
    alias: str | None = Field(default=None, min_length=2, max_length=64)
    rule_id: str | None = Field(default=None, min_length=1, max_length=36)
    landing_variant: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_-]+$",
    )
    utm_source: str | None = Field(default=None, max_length=500)
    utm_medium: str | None = Field(default=None, max_length=500)
    utm_campaign: str | None = Field(default=None, max_length=500)
    utm_content: str | None = Field(default=None, max_length=500)
    utm_term: str | None = Field(default=None, max_length=500)
    yclid: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def select_exactly_one_campaign_reference(self):
        if bool(self.alias) == bool(self.rule_id):
            raise ValueError("provide exactly one of alias or rule_id")
        return self


class PublicMessengerTouchIn(BaseModel):
    """Browser-safe acknowledgement that a prepared button link was clicked."""

    model_config = ConfigDict(extra="forbid")

    payload: str = Field(pattern=r"^U[A-Za-z0-9_-]+$", min_length=2, max_length=64)


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
    purpose: str | None = Field(default=None, max_length=2000)
    writer_brief: str | None = Field(default=None, max_length=10000)
    editorial_status: str | None = None
    source_format: str | None = None
    expected_version: int | None = Field(default=None, ge=1)


class ContentPublishIn(BaseModel):
    expected_version: int = Field(ge=1)
    body_source: str = Field(max_length=20000)
    purpose: str = Field(min_length=1, max_length=2000)
    writer_brief: str = Field(min_length=1, max_length=10000)
    confirm: Literal[True]


class ContentValidateIn(BaseModel):
    expected_version: int = Field(ge=1)
    body_source: str = Field(max_length=20000)
    purpose: str = Field(min_length=1, max_length=2000)
    writer_brief: str = Field(min_length=1, max_length=10000)


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
    buttons: list[dict] = Field(default_factory=list, max_length=4)


class BroadcastConfirmIn(BaseModel):
    confirmed_recipient_count: int = Field(ge=0)


class BroadcastTestIn(BaseModel):
    contact_id: str


class BroadcastScheduleIn(BroadcastConfirmIn):
    scheduled_at: str
