# Bounded local planner candidate investigation

This file preserves the preparation plan. Completed paired results and the
subsequent provisional two-model setup are in
[`docs/planner-selection.md`](../../docs/planner-selection.md).

Date: 2026-10-28. Reference machine verified locally: Apple M4 Pro, 14 CPU cores,
48 GiB unified memory, macOS. This is a model-selection probe, not a runtime
configuration change. Default planner port 1234 and VLM port 1235 remain reserved.

The supplied architecture proposes choosing among 2–3 local planner candidates
using the week-1 benchmark and checking actual tool use, valid specs, time, and
evaluation outcomes. These tests cover language interpretation and executable
graph construction. They do not establish warehouse detector accuracy.

## Candidate shortlist

| Candidate | Official Q4_K_M bytes | License | Reason to consider |
|---|---:|---|---|
| Qwen3-14B | 9,001,752,960 | Apache-2.0 | Selected first: official GGUF, documented tool use and explicit non-thinking mode; tests whether additional capacity helps semantic edits. |
| Qwen2.5-14B-Instruct | 8,988,110,496 across three shards | Apache-2.0 | Official instruct GGUF; model card specifically discusses structured JSON output. A separate candidate if Qwen3 does not improve actual cases. |
| Qwen3-8B | 5,027,783,488 | Apache-2.0 | Smaller fallback if 14B exceeds memory or latency budgets; same documented tool/non-thinking support. |

Primary sources: [Qwen3-14B card](https://huggingface.co/Qwen/Qwen3-14B-GGUF),
[Qwen2.5-14B-Instruct card](https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF),
[Qwen3-8B card](https://huggingface.co/Qwen/Qwen3-8B-GGUF),
[Qwen official llama.cpp guidance](https://github.com/QwenLM/Qwen3/blob/main/docs/source/run_locally/llama.cpp.md),
[llama.cpp function calling](https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md).
These descriptions are publisher claims and compatibility guidance, not measured
quality rankings. File sizes and hashes were read from the Hugging Face repository
API; the selected download is pinned and independently hashed.

Qwen3.5-9B was also inspected. Its official base weights use Apache-2.0, but the
search did not establish an official Qwen GGUF distribution. Some third-party
quantizations add materially different license terms. This bounded probe uses
the unambiguous official Qwen3 GGUF rather than substituting an unverified build.

## Existing environment and test constraints

- Existing llama.cpp is pinned b11963. Its local help confirms Jinja templates,
  `--chat-template-kwargs`, `--reasoning off`, and a local OpenAI-compatible server.
- Existing cache initially contained the Nemotron-3-Nano-4B Q4_K_M planner and
  Cosmos-Reason2-8B Q8_0 plus visual projector. No Qwen GGUF was cached.
- Before the download, the system reported normal pressure (kernel pressure
  level 1) but already used about 8 GiB swap and 13 GiB compressed physical RAM.
  Therefore 48 GiB capacity alone is not a guarantee of comfortable co-residency.
- Free disk was about 38 GiB before the 9.00 GB download. No user applications
  or model servers are stopped as part of preparation.
- Candidate endpoint is exclusively `http://127.0.0.1:1236/v1`, alias
  `visionapp-planner-qwen3-14b`. Context is 8192, one server slot, thinking disabled.
- The harness uses temperature 0 with strict native JSON schema. Its current
  refinement limits remain 25 seconds per request and 90 seconds overall;
  a timeout is a failed integration result, not silently granted more time.
- No model load/warmup/inference begins until the vision-core agent releases the
  shared inference slot after the final initial-planning benchmark.
- Frozen runtime source identity supplied by the harness:
  `4f94d391e5238170979135e9425e4212bd43d8e885d6c66f764264433c191ccb`.

## Planned first smoke comparison

Use the unchanged `evals.run_refinement_live` driver for five existing difficult
cases: `remove_class`, `count_upper`, `sample_seconds`, `eval_recall`, and
`read_text_exact`. This exercises class removal, an upper-bound count condition,
seconds-to-FPS conversion, evaluation metric plus target, and an exact OCR value.
The driver checks the complete intended graph, preserves unrelated fields, and
actually previews successful edits on generated fixture pixels. Native OCR is
provided explicitly through `VISION_APP_BINARY`.

Historical `artifacts/refinement-live-baseline24.json` scored 17/24 on an earlier
source revision. Later fidelity guards intentionally reject incorrect edits.
It is not a source-matched baseline for the new model. Retain separate results,
source identity, model/API provenance, tool calls, actual timings, and failures.
No project labels, training, deployment approval, or external alerts are created
by this isolated probe.

Results are pending. There is no current evidence to change the default model.
