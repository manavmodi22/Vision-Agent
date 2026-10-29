# Native-fed live runtime

The native capture process owns camera/screen permission and source selection. The
engine creates a private 0600 file under its 0700 `.live-ingress` directory and
returns its absolute path and 32 MiB capacity. The producer maps that file, writes
one complete BGRA8 frame (top-left origin, row stride in bytes), then POSTs only
metadata. It must wait for that response before touching shared bytes again.
There is no image/header transport through JSON. The engine copies bytes before
inference, so stop can unlink ingress without invalidating the in-flight image.

`POST /projects/{id}/live` accepts `candidate_index`, `source_kind` (`camera`,
`screen_capture`, `recorded_video`), `source_label`, and `preview_only` (default
false). `POST /projects/{id}/live/{session_id}/frames` accepts `sequence`, `width`,
`height`, `bytes_per_row`, `timestamp_s`. Sequence is strictly increasing; source
timestamps begin at zero or greater and strictly increase. Capture must honor the
returned `sample_fps`. `GET /projects/{id}/live/{session_id}` reads status;
`POST /projects/{id}/live/{session_id}/stop` stops capture acceptance immediately.

Frame responses contain `session_id`, `state`, `result` (FrameResult),
`processing_ms`, `processed_frames`, `retained_frames`, and `retained_bytes`.
Status additionally returns the mmap path/capacity, source/mode, sequence and time,
retention limits, duration/idle limits, warnings, and optional error. Preview
results use `live://session/sequence` image references; the native UI displays its
captured image. Recorded results refer to engine-owned retained PNGs.

Preview requires an explicit flag and never saves frames, events, reviews or
alerts. Recording requires a current deployment for the exact candidate. The
engine rechecks candidate/model/zone, approved evaluation labels/images, imported
media and deployment identity before inference and before committing evidence.
Changes close the session and discard in-flight results. Each session has its own
ExecutionState so temporal rules preserve their history across admitted frames.
No workspace lock is held during model inference.

Limits are visible in status and must be shown before capture: two active sessions,
one frame request per session, 32 MiB ingress, 240 retained frames or 256 MiB of
logical evidence payload per recording, 2 GiB of retained live files in total,
256 retained recording sessions, one-hour duration and five-minute idle timeout.
A limit stops the session; old evidence is never silently deleted. SQLite page and
index overhead is additional to the logical evidence bytes. Preview retains no
evidence, so its frame count is bounded by duration and sampling rate instead.
A stopped session returns HTTP 410 for further frames. Busy/over-rate submission
returns 409 without consuming sequence numbers. Invalid ordering fails the session.

Stop cannot interrupt a running native model kernel. It closes/unlinks ingress
and prevents that kernel's result from being recorded or delivered. Approved
session manifests survive restart and running sessions become failed/interrupted;
preview sessions are ephemeral. An exclusive process lease prevents a second
engine from cleaning an active engine's ingress files. Engine shutdown closes all
sessions and the idle sweeper. The protocol trusts the same-user native producer
to obey the single-writer handshake; it is not a hostile shared-memory channel.

Verification: two frames from the public NVIDIA SmartSpaces Warehouse_026
Camera_0000 recording were decoded, copied as BGRA into the returned mmap, and
submitted through the actual HTTP routes to local OWLv2. The frames produced 12
and 11 detection hypotheses (5.66 s cold and 0.72 s warm in this run). Preview
persisted zero events, created no deployment approval, and removed ingress at
stop. `artifacts/vision-verification/live-recorded-mmap.json` contains the measured
responses; the adjacent overlay is a model-output illustration, not an accuracy
benchmark. Synthetic isolated tests separately cover approved recording, real
JPEG crops, low-confidence review, stale approvals, temporal continuity, in-flight
stop, transaction cleanup, capacity limits and restart recovery.
