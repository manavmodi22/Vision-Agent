# Approved external alerts

Owner: integration; native target editor owned by Mac app. Interface: project
GET/PUT `/alerts`, GET `/alert-deliveries`, explicit POST `/alerts/test` and
`/alert-deliveries/{id}/retry`. Every target save/test/retry requires a human action;
no MCP approval tool is added. Optimistic revision checks reject stale editors.

Typed webhook/SMTP/MQTT targets use HTTPS or TLS, except loopback test servers.
Passwords/Bearer tokens are write-only and held in macOS Keychain; no plaintext
fallback. Public responses expose only has_secret. Errors omit secret values.

Only committed rule events from an approved deployment enqueue production alerts.
Preview/eval cannot enqueue. Durable SQLite outbox records revision, deployment,
condition key, attempts, timestamps and receipt/error. Worker rechecks approval
and configuration before delivery. Changed/revoked destinations cancel old jobs.
Cooldown is per condition and destination. Retries are bounded, survive restarts,
and use stable webhook idempotency keys / SMTP Message-ID / MQTT QoS1. Delivery is
at-least-once: remote acceptance followed by a crash may cause a duplicate.

Tests use actual loopback HTTP, SMTP and MQTT receivers, plus deterministic failure,
revision, approval, credential redaction, cooldown and recovery cases. A received
local protocol message proves transport integration, not a configured customer
endpoint. No external recipients are configured or contacted by test runs.
