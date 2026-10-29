# Reading evaluation metrics

Reading pipelines now report character error rate (CER) and word error rate
(WER) alongside the existing exact text-list accuracy. Ground truth still needs
explicit review, and the existing `text_accuracy` target controls pass/fail.
The additional rates do not silently change a user's evaluation gate.

The saved policy strips outer whitespace from each text region, sorts regions
case-sensitively and joins them with newline. Character distance counts Unicode
code points under this policy; word tokens split on whitespace. Internal case,
punctuation and leading zeros remain significant. This follows the established
region-order-independent comparison; it is not a named-field semantic metric.

Rates use total edit distance divided by total reference characters/words over
the evaluation set, rather than averaging per-image percentages. Insertions can
produce rates above 1. Empty references with hallucinated text retain insertion
counts but have no defined rate. Very large mismatching strings exceeding the
edit-work budget produce null aggregate rates and an explicit warning; no text
is truncated to manufacture a score. Exact-match gating remains available.

Each EvaluationResult retains normalization and raw numerator/denominator
counts. Historical results without these measurements keep null rates. Software
tests use a labelled deterministic reader double through the actual graph and
evaluator; they validate aggregation, not OCR model quality.
