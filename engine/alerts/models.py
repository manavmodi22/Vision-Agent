"""Public alert contracts, independent from transport and secret storage."""
from __future__ import annotations

import ipaddress
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, JsonValue, model_validator

from engine.store.models import Record, now


def is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class AlertTarget(Record):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["webhook", "smtp", "mqtt"]
    enabled: bool = True
    url: str | None = Field(default=None, max_length=2048)
    host: str | None = Field(default=None, max_length=253)
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=256)
    has_secret: bool = False
    from_address: str | None = Field(default=None, max_length=254)
    recipients: list[str] | None = Field(default=None, max_length=20)
    topic: str | None = Field(default=None, max_length=512)
    tls_mode: Literal["tls", "starttls", "none"] | None = None

    @model_validator(mode="after")
    def valid_transport(self) -> AlertTarget:
        strings = [self.name, self.url, self.host, self.username, self.from_address, self.topic]
        if any(value is not None and any(ord(c) < 32 for c in value) for value in strings):
            raise ValueError("Alert fields cannot contain control characters")
        if not self.name.strip():
            raise ValueError("Enter a target name")
        if self.kind == "webhook":
            if not self.url:
                raise ValueError("Webhook requires a URL")
            address = urlsplit(self.url)
            if not address.hostname or address.username or address.password or address.fragment:
                raise ValueError("Webhook URL must have a host and no embedded credentials or fragment")
            if address.scheme != "https" and not (address.scheme == "http" and is_loopback(address.hostname)):
                raise ValueError("Webhooks require HTTPS; HTTP is allowed only for loopback testing")
            if any(v for v in (self.host, self.port, self.username, self.from_address, self.recipients, self.topic, self.tls_mode)):
                raise ValueError("Webhook target contains settings for a different transport")
        else:
            if not self.host or self.port is None or not self.tls_mode:
                raise ValueError("SMTP/MQTT requires host, port and TLS mode")
            if any(c in self.host for c in "/@?# "):
                raise ValueError("Enter a hostname or IP address, not a URL")
            if self.url:
                raise ValueError("SMTP/MQTT target cannot contain a webhook URL")
            if self.tls_mode == "none" and not is_loopback(self.host):
                raise ValueError("Unencrypted delivery is allowed only for loopback testing")
            if self.kind == "smtp":
                if not self.from_address or not self.recipients or self.topic:
                    raise ValueError("SMTP requires sender and recipients, and no MQTT topic")
                for email_address in [self.from_address, *self.recipients]:
                    if not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+", email_address):
                        raise ValueError("Enter plain email addresses without display names or line breaks")
            elif not self.topic or any(c in self.topic for c in "+#") or self.tls_mode == "starttls":
                raise ValueError("MQTT requires a publish topic without wildcards and TLS or none")
            elif self.from_address or self.recipients:
                raise ValueError("MQTT target cannot contain email recipients")
        return self


class AlertConfiguration(Record):
    revision: int = Field(default=0, ge=0)
    enabled: bool = False
    minimum_interval_s: float = Field(default=60, ge=0, le=86400, allow_inf_nan=False)
    targets: list[AlertTarget] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def unique_targets(self) -> AlertConfiguration:
        if len({target.id for target in self.targets}) != len(self.targets):
            raise ValueError("Target IDs must be unique")
        return self


class SaveAlerts(Record):
    approved: bool
    configuration: AlertConfiguration
    secrets: dict[str, str | None] = Field(default_factory=dict)


class TestAlert(Record):
    approved: bool
    target_id: str


class Approval(Record):
    approved: bool


class AlertDelivery(Record):
    id: str
    project_id: str
    target_id: str
    target_name: str
    event_id: str
    created_at: str = Field(default_factory=now)
    status: Literal["queued", "sending", "sent", "failed", "cancelled"] = "queued"
    attempts: int = Field(default=0, ge=0)
    error: str | None = None
    sent_at: str | None = None
    revision: int
    deployment_id: str | None = None
    test: bool = False
    condition_key: str
    next_attempt_at: float = 0
    payload: dict[str, JsonValue]
