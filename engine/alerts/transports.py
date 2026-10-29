"""Real webhook, SMTP and QoS1 MQTT adapters with bounded acknowledgments."""
from __future__ import annotations

import json
import smtplib
import ssl
from email.message import EmailMessage

import httpx

from engine.alerts.models import AlertDelivery, AlertTarget


class DeliveryError(ValueError):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


def deliver(target: AlertTarget, delivery: AlertDelivery, secret: str | None) -> None:
    """Return only on transport acknowledgment; never include credentials in errors."""
    if target.kind == "webhook":
        headers = {"Idempotency-Key": delivery.id, "User-Agent": "VisionApp/0.1"}
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        try:
            with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
                response = client.post(str(target.url), json=delivery.payload, headers=headers)
            if not 200 <= response.status_code < 300:
                raise DeliveryError(f"Webhook returned HTTP {response.status_code}",
                                    retryable=response.status_code == 429 or response.status_code >= 500)
        except httpx.HTTPError as exc:
            raise DeliveryError("Webhook connection, certificate or timeout failure") from exc
    elif target.kind == "smtp":
        send_email(target, delivery, secret)
    else:
        publish_mqtt(target, delivery, secret)


def send_email(target: AlertTarget, delivery: AlertDelivery, secret: str | None) -> None:
    message = EmailMessage()
    message["From"] = str(target.from_address)
    message["To"] = ", ".join(target.recipients or [])
    message["Subject"] = f"VisionApp {'test' if delivery.test else 'vision event'}: {target.name}"
    message["Message-ID"] = f"<{delivery.id}@visionapp.local>"
    message.set_content(json.dumps(delivery.payload, indent=2, ensure_ascii=False))
    try:
        if target.tls_mode == "tls":
            smtp: smtplib.SMTP = smtplib.SMTP_SSL(str(target.host), target.port or 465,
                                               timeout=10, context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(str(target.host), target.port or 587, timeout=10)
        with smtp:
            smtp.ehlo()
            if target.tls_mode == "starttls":
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            if target.username:
                if not secret:
                    raise DeliveryError("SMTP username requires a stored credential", retryable=False)
                smtp.login(target.username, secret)
            rejected = smtp.send_message(message)
            if rejected:
                raise DeliveryError("SMTP rejected some recipients; others may have received the message", retryable=False)
    except (smtplib.SMTPException, OSError) as exc:
        raise DeliveryError("SMTP connection, authentication, certificate or delivery failure") from exc


def publish_mqtt(target: AlertTarget, delivery: AlertDelivery, secret: str | None) -> None:
    import paho.mqtt.client as mqtt
    from paho.mqtt.enums import CallbackAPIVersion

    client = mqtt.Client(CallbackAPIVersion.VERSION2,
                         client_id=f"visionapp-{delivery.id[:16]}", reconnect_on_failure=False)
    client.connect_timeout = 10
    if target.username:
        client.username_pw_set(target.username, secret)
    if target.tls_mode == "tls":
        client.tls_set_context(ssl.create_default_context())
    started = False
    try:
        if client.connect(str(target.host), target.port or 8883, keepalive=20) != mqtt.MQTT_ERR_SUCCESS:
            raise DeliveryError("MQTT broker connection failed")
        client.loop_start()
        started = True
        receipt = client.publish(str(target.topic), json.dumps(delivery.payload), qos=1, retain=False)
        receipt.wait_for_publish(timeout=10)
        if not receipt.is_published():
            raise DeliveryError("MQTT broker did not acknowledge the publication")
    except (OSError, RuntimeError, ValueError) as exc:
        if isinstance(exc, DeliveryError):
            raise
        raise DeliveryError("MQTT connection, certificate or acknowledgment failure") from exc
    finally:
        client.disconnect()
        if started:
            client.loop_stop()
