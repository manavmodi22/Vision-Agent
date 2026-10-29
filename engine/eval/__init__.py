"""Ground-truth evaluation; no automatic approval or deployment side effects."""
from __future__ import annotations

from pathlib import Path

from pydantic import JsonValue

from engine.adapters.registry import InferenceAborted
from engine.compiler import compile_pipeline
from engine.eval.hashes import dataset_hash, spec_hash
from engine.eval.metrics import count_errors, match_detections
from engine.eval.reading import NORMALIZATION, error_rate, reading_errors
from engine.eval.recipe import recipe_hash
from engine.eval.scope import detection_scope
from engine.runtime.executor import execute_frame
from engine.runtime.values import ExecutionState
from spec.evaluation import EvaluationProtocol
from spec.models import EvalDataset, EvaluationResult, PipelineSpec


class EvaluationError(ValueError):
    """The supplied evaluation evidence cannot support a valid result."""


def evaluate(spec: PipelineSpec, dataset: EvalDataset, project_root: Path, *,
             protocol: EvaluationProtocol | None = None) -> EvaluationResult:
    recipe_hash()  # Pin loaded scoring/runtime semantics even for diagnostic calls.
    from engine.eval.protocol import (
        attach_evidence,
        begin_evaluation,
        mark_usage,
        reserved_acceptance_paths,
    )
    from engine.evidence_metadata import unique_images
    full_dataset = dataset
    if protocol is not None:
        # Consume acceptance before executing any learned model, including failed attempts.
        dataset = begin_evaluation(project_root, dataset, spec, protocol)
    if not dataset.annotations:
        raise EvaluationError("Evaluation requires a nonempty labeled set")
    if len(dataset.annotations) > 500:
        raise EvaluationError("An evaluation set is limited to 500 reviewed images")
    if any(not annotation.reviewed for annotation in dataset.annotations):
        raise EvaluationError("Every evaluation image must be explicitly reviewed, including empty images")
    if len({(project_root / a.image_path).resolve() for a in dataset.annotations}) != len(dataset.annotations):
        raise EvaluationError("Evaluation images must be unique")
    unique_images(project_root, [row.image_path for row in dataset.annotations])
    if protocol is None:
        reserved = reserved_acceptance_paths(project_root, dataset)
        if any(str((project_root / row.image_path).resolve()) in reserved for row in dataset.annotations):
            raise EvaluationError("Reserved acceptance requires one frozen selected-candidate protocol")
        mark_usage(project_root, [row.image_path for row in dataset.annotations], "diagnostic evaluation")
    compiled = compile_pipeline(spec, project_root)
    if compiled.vlm_identities and any(identity.identity_scope == "server_metadata_only" for identity in compiled.vlm_identities.values()):
        raise EvaluationError("VLM evaluation needs verifiable model weights; this endpoint exposes only metadata. Use a server exposing a local GGUF model path or verified digest.")
    scope = detection_scope(compiled)
    ground_truths = [scope.ground_truth(annotation.detections) for annotation in dataset.annotations]
    if spec.eval.metric in {"precision", "recall"} and not any(ground_truths):
        raise EvaluationError("No labeled positive objects remain for the final detector's selected classes and zones")
    zone_ids = scope.zone_ids
    fingerprint = spec_hash(spec, project_root)
    evidence_hash = dataset_hash(dataset, project_root)
    tp = fp = fn = 0
    errors: list[float] = []
    texts_correct = 0
    reading = any(block.type in {"ocr", "barcode"} for block in spec.blocks)
    expected_characters = expected_words = 0
    character_edits: int | None = 0
    word_edits: int | None = 0
    failures: list[dict[str, JsonValue]] = []
    for annotation, ground_truth in zip(dataset.annotations, ground_truths, strict=True):
        path = (project_root / annotation.image_path).resolve()
        try:
            result = execute_frame(compiled, path, 0, ExecutionState())
        except InferenceAborted as exc:
            raise EvaluationError(str(exc)) from exc
        matches = match_detections(result.detections, ground_truth)
        tp += matches.true_positive
        fp += matches.false_positive
        fn += matches.false_negative
        image_errors = count_errors(result.detections, ground_truth, zone_ids)
        errors.extend(image_errors)
        text_result = reading_errors(annotation.expected_texts, result.texts)
        text_ok = text_result.exact_match
        if reading:
            expected_characters += text_result.expected_characters
            expected_words += text_result.expected_words
            character_edits = (character_edits + text_result.character_edits
                               if character_edits is not None and text_result.character_edits is not None else None)
            word_edits = (word_edits + text_result.word_edits
                          if word_edits is not None and text_result.word_edits is not None else None)
        texts_correct += int(text_ok)
        loss = matches.false_positive + matches.false_negative
        if spec.eval.metric == "text_accuracy":
            loss = int(not text_ok)
        if loss or any(image_errors):
            failures.append({"image_path": str(path), "false_positives": matches.false_positive,
                             "false_negatives": matches.false_negative,
                             "count_error": sum(image_errors) / len(image_errors),
                             "severity": loss + sum(image_errors),
                             "expected_count": len(ground_truth), "observed_count": len(result.detections),
                             "expected_texts": list(annotation.expected_texts), "observed_texts": list(result.texts)})
    precision = tp / (tp + fp) if tp + fp else (1.0 if fn == 0 else 0.0)
    recall = tp / (tp + fn) if tp + fn else 1.0
    mae = sum(errors) / len(errors)
    text_accuracy = texts_correct / len(dataset.annotations)
    metrics = {"precision": precision, "recall": recall, "count_mae": mae, "text_accuracy": text_accuracy}
    value = metrics[spec.eval.metric]
    passed = value <= spec.eval.target if spec.eval.metric == "count_mae" else value >= spec.eval.target
    warnings = list(compiled.warnings)
    cer = error_rate(character_edits, expected_characters) if reading else None
    wer = error_rate(word_edits, expected_words) if reading else None
    if reading and (character_edits is None or word_edits is None):
        warnings.append("An OCR edit-distance comparison exceeded its work limit; affected aggregate error rates are not reported.")
    if reading and ((not expected_characters and character_edits) or (not expected_words and word_edits)):
        warnings.append("OCR insertions occurred with no reference text; error counts are retained, but rates with a zero denominator are not reported.")
    if len(dataset.annotations) < 10:
        warnings.append("Fewer than 10 reviewed images; this is a smoke test, not a representative accuracy estimate.")
    # Detect concurrent edits during evaluation; never issue a score for mixed evidence.
    if evidence_hash != dataset_hash(dataset, project_root) or fingerprint != spec_hash(spec, project_root):
        raise EvaluationError("Evaluation evidence changed while the run was in progress; run it again")
    score = EvaluationResult(precision=precision, recall=recall, count_mae=mae, passed=passed,
        metric=spec.eval.metric, target=spec.eval.target, sample_count=len(dataset.annotations),
        failures=sorted(failures, key=lambda item: float(str(item["severity"])), reverse=True),
        spec_hash=fingerprint, dataset_hash=evidence_hash, text_accuracy=text_accuracy,
        character_error_rate=cer, word_error_rate=wer, text_normalization=NORMALIZATION if reading else None,
        text_error_counts={"expected_characters": expected_characters, "character_edits": character_edits,
                           "expected_words": expected_words, "word_edits": word_edits} if reading else {},
        warnings=warnings)
    if protocol is not None:
        return attach_evidence(project_root, full_dataset, spec, protocol, score)
    score.evidence_scope = "sample"
    score.evidence_reasons = ["Diagnostic image metrics have no frozen acceptance protocol; promotion is not qualified"]
    return score


__all__ = ["evaluate", "spec_hash", "dataset_hash", "EvaluationError"]
