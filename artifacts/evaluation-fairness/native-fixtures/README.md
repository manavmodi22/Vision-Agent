# Software contract fixtures

These four JSON files were captured from real local API routes by `tests/test_evaluation_integration.py::test_positive_fresh_import_reserve_review_acceptance_and_exact_replay`. They exercise fresh import, explicit split/policy configuration, human ground-truth review, one selected-candidate acceptance action and exact cached replay.

The test generates distinct simple PNGs and mocks the inference adapter. `data_origin=real` is an explicit simulated human declaration used to test the positive policy path. The resulting numeric values are **not measured detector accuracy, real-scene independence, or production evidence**. The mock execution identity is labeled `software-test`. No real model call, deployment on user data, or outgoing delivery occurred.

`build-status.json` contains the validation score array and separate acceptance score. `readiness.json` describes an existing captured acceptance result; viewing it does not run inference. The JSONs are native decoder fixtures, not a model benchmark.
