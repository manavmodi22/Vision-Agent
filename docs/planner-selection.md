# Local planner selection

Qwen3-14B Q4_K_M is the provisional selection for full validation on the reference
Apple M4 Pro / 48 GiB Mac. The startup script uses its official local GGUF while
keeping the application alias `visionapp-planner` and loopback port 1234 stable.
The first complete corrected-runtime suites finished 24/25 initial goals and
19/24 refinements. Two interpretation defects and four refinement request
timeouts remain in those captured results; corrections and separate targeted
retests are pending. Selection remains provisional. None of these scores is
evidence of warehouse detector accuracy.

## Provenance and reproducibility

- Official repository: [Qwen/Qwen3-14B-GGUF](https://huggingface.co/Qwen/Qwen3-14B-GGUF),
  Apache-2.0. Revision `530227a7d994db8eca5ab5ced2fb692b614357fd`.
- File: `Qwen3-14B-Q4_K_M.gguf`, 9,001,752,960 bytes. SHA256
  `500a8806e85ee9c83f3ae08420295592451379b4f8cf2d0f41c15dffeb6b81f0`.
- Default cache: `~/.lmstudio/models/Qwen/Qwen3-14B-GGUF/`. Weights, model card,
  and license were downloaded from that pinned official revision; the GGUF hash
  was independently verified. The app bundle does not include planner weights.
- llama.cpp b11963, context 8192, one slot, thinking off, strict JSON schemas,
  temperature 0. Existing request/operation deadlines were unchanged. Native OCR
  was explicitly available during fixture previews.
- Exact commands, model provenance, resource samples, logs, and results live in
  [`artifacts/stronger-planner`](../artifacts/stronger-planner/). Original Nemotron
  and Cosmos commands were preserved before any temporary shutdown.

The official [Qwen3-8B GGUF](https://huggingface.co/Qwen/Qwen3-8B-GGUF) (5.03 GB)
and [Qwen2.5-14B-Instruct GGUF](https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF)
(8.99 GB) were also reviewed; both use Apache-2.0. Qwen3-8B was downloaded,
verified, and tested. Qwen2.5 was not downloaded or benchmarked.

## Same-source difficult subset

The five refinement cases and four initial briefs were selected because the
existing planner had failed them. All three models used runtime identity
`4f94d391e5238170979135e9425e4212bd43d8e885d6c66f764264433c191ccb`.
These are actual model calls, compiler checks, and fixture previews. Passes
require the requested fields and preservation of unrelated graph fields.

| Model | Refinements | Initial briefs | Total | Refinement p50 / max | Initial p50 / max |
|---|---:|---:|---:|---:|---:|
| Nemotron 3 Nano 4B Q4_K_M | 0/5 | 0/4 | 0/9 | 22.68 / 25.56 s | 15.66 / 17.24 s |
| Qwen3-8B Q4_K_M | 4/5 | 3/4 | 7/9 | 17.49 / 29.35 s | 34.48 / 43.99 s |
| Qwen3-14B Q4_K_M | 5/5 | 3/4 | 8/9 | 11.19 / 22.13 s | 37.44 / 107.14 s |

Timings include failed attempts and actual engine work. Residency differed:
14B subset runs kept the old planner but temporarily unloaded idle Cosmos;
8B runs had all three servers loaded. Therefore these times do not isolate
model-size effects and must not be presented as an intrinsic speed ranking.

Material failures remain:

- 14B's count-duration brief saved `count >= 1` instead of the requested
  `count >= 8`, while repeating 8 in its summary. The preview existed but failed.
- 8B could not convert one frame every two seconds to 0.5 FPS within the allowed
  retries. Its damage brief produced one candidate without the evidence rule
  and another with a different evaluation metric; the test correctly failed.
- Nemotron's five refinements exhausted retries without changing the graph.
  Its four failed initial briefs are retained in `artifacts/custom-goals-final.json`.

The 14B 107.14-second case required a validation retry. Its first response created
three alternatives: 17.68 s prefill + 59.28 s decoding 355 tokens; one alternative
used an inappropriate recall metric for counting. The corrective response took
5.86 s prefill + 21.77 s decoding 148 tokens and returned one correct graph.
Compilation and actual preview together took about 0.25 s. The captured trace
supports a generation/retry cost explanation, not an expensive vision preview.

## Operational feasibility and validation gate

All comparison probes monitored pressure and swapouts, aborting for critical
pressure or over 1 GiB new swapout traffic in 30 seconds. Neither aborted.
14B runs stayed at warning pressure with zero new swapout pages; the three-model
8B runs had roughly 1 GiB additional swapout traffic spread over both suites.
That comparison load is not the intended application configuration.

After stopping the old Nemotron and comparison server, 14B plus Cosmos both
reported healthy and kernel memory pressure stayed normal across a 60-second
load/coexistence observation. Verbose loading
confirmed all 41/41 Qwen layers on the M4 Pro GPU with no auto-fit reduction:
8,161 MiB model + 1,280 MiB KV cache + 150 MiB compute buffers on Metal. This is
a load/coexistence check; sustained simultaneous vision and planner workloads
still need observation. Existing system swap usage is not erased by this check.

The live provisional planner is on 1234; Cosmos remains on 1235; 1236 is closed.
The original Nemotron command is retained for rollback. Human review, evaluation,
and deployment approval remain mandatory regardless of planner choice.

## Complete frozen suites · 2026-10-28

Both suites used Qwen3-14B Q4_K_M at `visionapp-planner`, runtime identity
`c19fac5076701e673f0f6cca843619382dd195d32fdf0bb5dc68f9488346b639`.
Before/after identity and server-command checks matched. They ran sequentially,
with no other model inference scheduled. The GUI was quit early in the initial
suite to remove its duplicate detector residency; Cosmos remained loaded.

| Suite | Complete result | Case p50 / max | Wall time |
|---|---:|---:|---:|
| Initial goals, original 24 plus visible Home crop example | 24/25 | 25.99 / 71.61 s | 772.92 s |
| Conversational refinements | 19/24 | 16.69 / 45.07 s | 492.79 s |

The five refinement failures comprise four request timeouts and one serious
interpretation error. For `unsupported_compound`, the user requested confidence
0.6 and an email whenever a pallet is detected. The model returned a confidence
edit, added **email as a detection class**, added a local count rule, and claimed
an email alert had been added. It asked no question. The interpreter accepted
that decision; the benchmark recognized the mismatch and did not apply it.
Benchmark rejection must not be mistaken for a runtime guarantee against this
request. No email, approval, or recorded operating run occurred.

The other semantic failure was initial `ocr-missing-value`: the unspecified
phrase “expected SKU” became the literal comparison string instead of prompting
for the required value. The saved workflow summary accurately exposed that
wrong value, but the requested task was still not fulfilled.

Refinement timeouts: `confidence_percent`, `compound_rule_target`, `insert_rule`,
and `ambiguous_accuracy`. The frozen source allowed 25 seconds per HTTP request
within a 90-second operation. The compound failure occurred after warm requests,
so this limitation is not exclusively a first-request effect. Timed-out requests
did not reach graph commit. Completed refinement cases include exact/contains
mode checks; initial reading checks in this definition test literal values with
contains semantics and do not establish exact initial matching support.

Both full suites stayed at normal kernel pressure (level 1), with zero new
swapout pages during their respective observations and no resource abort.
Existing system swap remained allocated. This is stronger evidence for sequential
planner/VLM co-residency than the earlier three-model comparison, but does not
measure simultaneous VLM-plus-detector throughput.

Raw reports and complete identity/resource evidence:

- `artifacts/stronger-planner/qwen14-final-initial25.json` and `-evidence.json`.
- `artifacts/stronger-planner/qwen14-final-refinement24.json` and `-evidence.json`.
- Initial failure trace: `.visionapp/qwen14-final-initial25/projects/597cb1cfca6f480b/agent-runs/423bd531d627466bae5a4fe2a6d60dbf.json`.
- Unsupported compound trace: `.visionapp/qwen14-final-refinement24/projects/ab4b48549c2a45cc/builds/ba813fb725bb4fb7bb30c066bb131021.json`.

These full scores remain 24/25 and 19/24. Any corrections and targeted reruns
must be reported separately with their own source identity; they do not turn
these historical results into perfect full-suite scores.
