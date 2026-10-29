# Native model provisioning

Provisioning is a contextual action in the existing capability catalog. It does
not replace the goal composer or introduce a required setup dashboard.

Opening the catalog only reads capability and provisioning option metadata. A
model action opens a concrete, immutable plan for review. The sheet presents the
planned artifacts, download sizes, pinned source URLs and hashes, code/weight
license attribution, local runtime and hardware requirements, and readiness
blockers. Unspecified values remain unspecified.

Only an explicit “Install and test” or installed-model validation approval starts
a job. The native client submits the reviewed plan identity and hash; it does not
submit arbitrary URLs, filesystem paths, commands or model code. Backend validation
remains authoritative if the plan or runtime changed after review.

Job status, phases, progress, errors and validation receipts come from the durable
backend record. Closing a sheet does not cancel or simulate completion. Reopening
queries saved jobs for the model and resumes the actual record. An uncertain start
response is reconciled against that list before another explicit attempt. Retry is
an explicit action, and stale plans require a fresh review.

A successful adapter smoke test establishes current execution readiness for that
installation. It is not project-level accuracy, independent acceptance or quality
promotion. Catalog readiness is refreshed from the engine after a terminal result;
the UI never marks a capability ready locally.

The wire contract is `spec/provisioning.py`. The native client reads
`/provisioning/options`, creates registry-bound review plans with only `model_id`,
and starts jobs with only `plan_id`, `plan_hash`, and `approved`. Saved jobs are
queried by model ID and resumed from their immutable plan. A locally remembered
pending plan also survives an uncertain start response; reopening does not silently
replace it with a new approval.

Native checks exercise scoped license attribution, concrete artifact identity,
blocked and unknown actions, the minimal approval body, partial installation
failure, exact job/plan/model matching, and smoke receipts with no quality claim.
The self-test CLI accepts captured backend JSON with `--provisioning-options`,
`--provisioning-plan`, `--provisioning-job`, and `--provisioning-health`. Decoding a
real receipt remains separate from the inference that generated that receipt.

For a completed job, the sheet reads only its explicit health receipt ID. It
matches the returned model, job, plan hash and no-quality-claim scope before
showing the generated input description, measured execution time and observation
count. Input, installation and execution identity hashes remain inspectable in a
disclosure. Missing or mismatched receipts are unavailable evidence; they neither
erase the historical job result nor establish current catalog readiness.
