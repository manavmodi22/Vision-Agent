from pathlib import Path

from evals.run_benchmark import load_cases, template_benchmark


def test_all_24_authored_patterns_compile_and_have_honest_provenance(tmp_path: Path) -> None:
    report = template_benchmark(tmp_path)
    assert len(load_cases()) == len(report.cases) == 24
    assert {case.use_case for case in load_cases()} == {"pallets", "damage", "labels"}
    assert all(case.spec_valid and case.expected_pattern for case in report.cases)
    assert all(case.eval_metric_reached is None for case in report.cases)
    assert report.mode == "template-regression"
    assert report.model is None
    assert "not LLM" in report.provenance
