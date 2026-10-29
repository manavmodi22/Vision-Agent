# Executable block reference (spec 0.1)

Only these blocks are currently executable. Unknown blocks are rejected.

| Block | Inputs | Outputs | Behavior |
| --- | --- | --- | --- |
| `frame_sample` | `frames: frames` | `frame: image` | Sample frames at a bounded rate. |
| `detect` | `image: image` | `dets: detections` | Run a locally installed detector. |
| `detect_open_vocab` | `image: image` | `dets: detections` | Detect text-prompted classes using local OWLv2. |
| `zone_filter` | `dets: detections` | `dets: detections` | Keep objects whose center is inside a polygon. |
| `count_per_zone` | `dets: detections` | `counts: counts` | Count detections in each named zone. |
| `rule` | `value: counts` | `event: event` | Compare zone counts using a small safe expression language. |
| `sink_event` | `event: event` | `event: event` | Emit local evidence events; delivery is separately approved. |
| `ocr` | `image: image` | `text: text` | Read text with native Apple Vision. |
| `barcode` | `image: image` | `text: text` | Read barcode payloads with native Apple Vision. |
| `match` | `text: text` | `event: event` | Compare recognized text with an expected value. |
| `vlm_judge` | `image: image` | `judgement: judgement`, `text: text`, `event: event` | Bounded local model judgement with model identity and crop evidence. |
| `resize` | `image: image` | `image: image` | Resize input pixels; normalized boxes remain unchanged. |
| `crop` | `image: image` | `image: image` | Crop a normalized rectangle and preserve coordinate transforms. |

Parameter schemas are returned by MCP `block_schema` / the block registry.

One detector and one zone filter are allowed per candidate so the displayed and
evaluated detection set is unambiguous. Different detector alternatives belong
in different candidate specs. Each frame source uses a common sampling rate.

Coordinates are normalized top-left xyxy. Cropping carries a transform back to
the original image. Zones use the object center; overlapping polygons use the
first matching zone. Counts include zero-valued configured zones.

Rules accept only `count OP NUMBER`, with `>= <= == != > <`. A positive `hold_s`
can be authored using independent sample images, with an explicit warning that
duration is not evaluated there. Image enumeration has no elapsed-time meaning,
and every independent image gets fresh temporal state. Duration events require
timestamped video or a native live session. Events are emitted for each matching
sampled frame after the hold period; there is no implied cross-run debounce or tracking.

`sink_event.alert` records the requested target in an event; actual delivery
requires an independently configured and approved alert channel in the service.

Unavailable: tracking, segmentation, tiling, line crossing, dwell of individual
tracked objects, arbitrary classification, Core ML export.
They are not advertised as working block types.

Native camera/screen/video capture uses the shared-memory ingress described in
`live-runtime.md`; source permissions remain the native application's responsibility.

VLM candidates use `text_accuracy` on reviewed `expected_texts` labels. A missing
or incompatible vision model fails explicitly; evidence from endpoints without
verifiable weight identity cannot pass the evaluation gate. Confidence is the
model’s self-estimate, not measured accuracy.
