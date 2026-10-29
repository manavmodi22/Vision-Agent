# gpt-oss-20b local planner feasibility

Assessment on 2026-10-29: **an actionable isolated planner experiment on this M4 Pro with 48 GiB, not a qualified replacement.** This assessment fetched metadata only, without weights, inference, cache deletion, server/settings changes or production edits. Root's subsequent authorized download is separate. Machine-readable provenance is in `model-feasibility-gpt-oss.json` beside this note.

OpenAI documents a text-only, Apache-2.0 model with approximately 21B total/3.6B active parameters, configurable reasoning, function calling and structured outputs. It can plan over CV observations but does not itself inspect image pixels. OpenAI's local guide supports Apple Silicon and gives a general 16 GB memory requirement. Neither establishes our planner quality or exact runtime allocation. [Model documentation](https://developers.openai.com/api/docs/models/gpt-oss-20b), [local guide](https://developers.openai.com/cookbook/articles/gpt-oss/run-locally-lmstudio)

## Exact candidate

Use the **llama.cpp maintainers' conversion**, not a claimed OpenAI-published GGUF. The runtime guide explicitly points to this repository. No GGUF was listed in OpenAI's upstream model repository. The maintainer repository also contains small Eagle3 draft models; those are not substitutes for this primary artifact. [Maintainer guide](https://github.com/ggml-org/llama.cpp/discussions/15396)

| Field | Verified publisher metadata |
| --- | --- |
| Repository | `ggml-org/gpt-oss-20b-GGUF` |
| Immutable revision | `15dcfc7e7c608c6161507211ed43c5b590801b4b` |
| Filename | `gpt-oss-20b-MXFP4.gguf` — case-sensitive |
| Bytes | **12,109,566,624**, about 11.28 GiB |
| Expected LFS SHA256 | `27cd6c432c7672cb812a92f611cf3ba7bbc35928262bb1e1253ff4ee6ae35901` |
| Declared license | Apache-2.0; upstream license fetched and hashed |
| Declared source | `openai/gpt-oss-20b` at `6cee5e81ee83917806bbde320786a8fb61efebee` |

The pinned [API metadata](https://huggingface.co/api/models/ggml-org/gpt-oss-20b-GGUF/revision/15dcfc7e7c608c6161507211ed43c5b590801b4b?blobs=true) supplies the size/LFS hash. The publisher's [.src_sha](https://huggingface.co/ggml-org/gpt-oss-20b-GGUF/blob/15dcfc7e7c608c6161507211ed43c5b590801b4b/.src_sha) explicitly identifies that source commit as `PRIMARY`. This is publisher provenance, not an independently reproduced conversion. The [upstream license](https://huggingface.co/openai/gpt-oss-20b/blob/6cee5e81ee83917806bbde320786a8fb61efebee/LICENSE) is 11,357 bytes, SHA256 `58d1e17ffe5109a7ae296caafcadfdbe6a7d176f0bc4ab01e12a689b0499d8bd`.

[Pinned weight download](https://huggingface.co/ggml-org/gpt-oss-20b-GGUF/resolve/15dcfc7e7c608c6161507211ed43c5b590801b4b/gpt-oss-20b-MXFP4.gguf). Use one project-owned staging file, verify exact bytes and SHA256, then rename in place. Avoid another full cache copy. This assessment verifies metadata, not a local weight digest; the download receipt must establish that separately.

## Disk and memory

At **18:52:02 UTC**, available disk was **15,236,505,600 bytes**. Download plus an 8 GiB reserve requires **20,699,501,216 bytes**. These task-owned caches were previously audited as stopped, with no open `lsof` users; root subsequently rechecked them and authorized their removal. The pre-cleanup arithmetic is preserved here:

| Previously reclaimable cache | Bytes | Preserved receipts |
| --- | ---: | --- |
| `~/.lmstudio/models/Qwen/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf` | 5,027,783,488 | `artifacts/stronger-planner/model-provenance-qwen8.json`, `server-qwen8.json` |
| `.visionapp/model-qualification/Qwen3.5-9B-Q6_K/Qwen3.5-9B-Q6_K.gguf` | 7,458,301,152 | `artifacts/a0-investigation/qwen35-9b-qualification.json`, `qwen35-qualification-unload.json` |

At that snapshot, Qwen8-only cleanup would leave **8,154,722,464 bytes** after the download, below the reserve. Both would leave **15,613,023,616 bytes (14.54 GiB)**. Active Qwen14, Cosmos and unrelated user data are excluded. Root's separate cleanup/download receipts supersede this snapshot for actual current disk availability.

The maintainer guide reports approximately 14.9 GB total at 8K and 15.5 GB at 32K, including compute buffers, and demonstrates Metal on 32/36 GB Macs. **About 15–16 GB for an isolated 16K trial is a plausible planning estimate, not a measurement here.** Its older-build benchmark speeds are not predictions for this M4 Pro. [Runtime hardware guidance](https://github.com/ggml-org/llama.cpp/discussions/15396)

Physical RAM is 51,539,607,552 bytes. At 18:40, pressure was normal but swap usage was about 10.8 GiB, with active Qwen14 roughly 13.2 GiB RSS. RSS omits some Metal/shared allocations. Schedule the experiment after the competing task-owned planner is idle and explicitly unloaded; preserve Cosmos and native/user apps. Cache deletion alone does not establish RAM headroom. Confirm actual allocation, pressure and swap growth during the trial.

## Pinned runtime and transport

The existing `.visionapp/runtime/llama-b11963/llama-server` reports build11963, commit `39febd2ad`, Darwin arm64. Its help supports the proposed flags; binary libraries contain gpt-oss/MXFP4 Metal implementation identifiers. Server SHA256: `3d81b7997317e5ffd13ed3ba32436658e0f4067172cea3674b4215b39d4635be`; libllama: `e20dcf1d00324fc1fb336259462dfcaaf1d314dd7adced2cfce774226584d7af`. These findings do not indicate a required binary upgrade.

The [parser at the exact runtime commit](https://github.com/ggml-org/llama.cpp/blob/39febd2ad/common/parsers/gpt-oss.cpp#L94) permits analysis messages followed by a final message whose content is constrained by the supplied JSON schema. It extracts analysis separately and supports native tool-call parsing. This supports our typed-decision design in source; execution still needs a smoke test. The [pinned server documentation](https://github.com/ggml-org/llama.cpp/blob/39febd2ad/tools/server/README.md) defines `deepseek` as the output-field format placing reasoning in `message.reasoning_content`; it does not select a DeepSeek template.

The [upstream template](https://huggingface.co/openai/gpt-oss-20b/blob/6cee5e81ee83917806bbde320786a8fb61efebee/chat_template.jinja) defaults to medium reasoning and maps an initial system or developer message into Harmony's developer section. Use embedded metadata; do not force Qwen tags, `enable_thinking=false`, or `--reasoning off`. Verify actual `/apply-template` output after loading. OpenAI requires Harmony formatting and preserves intermediate native tool-call reasoning/history until a final answer; completed final answers permit dropping prior reasoning. Our current final typed-decision requests can retain their boundary. A later native function-call migration needs correct continuation history. [Harmony guidance](https://developers.openai.com/cookbook/articles/openai-harmony), [implementation checks](https://developers.openai.com/cookbook/articles/gpt-oss/verifying-implementations)

**Budget caveat:** 512 is a budget per reasoning block, not per whole response. The [pinned sampler](https://github.com/ggml-org/llama.cpp/blob/39febd2ad/common/reasoning-budget.cpp#L146) re-arms for each new analysis block. The gpt-oss grammar allows multiple analysis blocks before final. Forcing the analysis terminator therefore does not guarantee the next channel is final. `max_tokens` remains the hard total bound, and a length stop or missing final JSON must remain an explicit failure.

## Proposed minimal smoke launch

This command is a **proposal, not executed by this assessment**. It assumes verified weights at the shown path and port1236 checked free. Low reasoning plus 512 tokens is root's deliberately bounded first transport test, not a quality-qualified configuration or OpenAI's default.

```sh
/Users/manavrakeshku.modi/vision-agent/.visionapp/runtime/llama-b11963/llama-server \
  --model /Users/manavrakeshku.modi/vision-agent/.visionapp/model-qualification/gpt-oss-20b-MXFP4/gpt-oss-20b-MXFP4.gguf \
  --alias gpt-oss-20b-MXFP4-qualification \
  --host 127.0.0.1 --port 1236 --ctx-size 16384 --parallel 1 \
  --gpu-layers all --flash-attn on --batch-size 1024 --ubatch-size 512 \
  --jinja --reasoning on --reasoning-effort low --reasoning-budget 512 \
  --reasoning-format deepseek
```

Use the exact current `response_format` and model messages, `temperature: 0`, `reasoning_effort: "low"`, `extra_body: {"reasoning_budget_tokens": 512}`, and existing total `max_tokens: 1400` for NextAction or `2600` for WorkflowDecision. Body overrides are supported by [pinned server parsing](https://github.com/ggml-org/llama.cpp/blob/39febd2ad/tools/server/server-common.cpp#L1497). Actual preflight must include the same schema and template options as generation. Tokenized prompt + total output allowance + existing margin must fit16,384; never silently drop evidence. Capture finish reason, separate final/reasoning fields and actual usage. Do not infer successful bounded reasoning from CLI acceptance alone.

Then replay frozen observation points without dispatch, checking valid actual IDs, observation use, repeated actions, semantic exclusions and graph validity. Only if those warrant it, run a bounded isolated real investigation and validate actual compiled-preview results against both success and failure references. Preserve allocation, latency and all failed responses. If low/512 truncates or harms reasoning, a separately labelled medium/larger-budget experiment is needed before drawing conclusions about model quality; do not silently change conditions or promote a JSON-only result.
