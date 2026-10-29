# Native alert configuration and receipts

Owner: native_app. The Alerts screen is scoped to one selected project. It owns
its draft in `AlertWorkspace` and uses the existing HTTP-over-Unix-socket client.
No delivery, configuration write or retry occurs on page load or refresh.

`AlertConfiguration` and `AlertTarget` are Codable public DTOs; no password/token
field exists in a target. `AlertSaveRequest` separates public configuration from
credential changes. An omitted secret preserves its stored value, a JSON null
removes it, and a string replaces it. SecureField values are memory-only and are
cleared on a successful save, refresh, target removal or project change. Responses
only expose `has_secret`; errors do not interpolate submitted secret values.

Every write is reviewed in an explicit sheet: the master enabled state, rate
limit, each destination and transport, and credential change status. The final
button sends `approved: true`. Testing names the saved target and sends only a
generated test message. Retry shows the event and current saved destination and
requires its own final click. Editing a draft cannot silently redirect a saved
target's test or retry. Unknown/removed targets cannot be retried from the UI.

The configuration revision is retained and submitted unchanged so the server can
reject stale edits. A rejection leaves the draft visible for inspection; Refresh
is a separate action that confirms discarding any draft/credential changes.

Validation covers Codable wire keys, omitted/present/null secret semantics,
destination summaries and validation. Native build and executable self-tests run
without XCTest. UI QA will use a local generated-test receiver only; this task does
not authorize sending to any real external email, webhook or broker destination.
