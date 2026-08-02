"""Narrative quality evaluation tests."""

import json
from pathlib import Path
from typing import Any

import pytest

from rumor_mill.adapters.providers import DeterministicFakeProvider
from rumor_mill.evals.__main__ import main
from rumor_mill.evals.models import (
    EvalCase,
    EvalCategory,
    EvalReport,
    EvalThresholds,
    EvaluationMode,
    RubricGrade,
)
from rumor_mill.evals.rules import evaluate_rules
from rumor_mill.evals.runner import (
    EvaluationRunner,
    TokenBudgetExceededError,
    load_cases,
    load_recorded_outputs,
    markdown_report,
)

ROOT = Path(__file__).parents[1]
DATASET = ROOT / "evals/lighthouse-v1.json"


def case(**changes: Any) -> EvalCase:
    values: dict[str, Any] = {
        "id": "test-case",
        "category": EvalCategory.CANON_CONSISTENCY,
        "prompt": "Continue the story.",
        "candidate": "Ada saw the lamp. claim:lamp event:outage",
        "character_voice_markers": ("Ada",),
        "grounded_claims": ("saw the lamp",),
        "forbidden_secrets": ("hidden key",),
        "canon_facts": ("the lamp",),
        "forbidden_canon_claims": ("never saw the lamp",),
        "required_source_ids": ("claim:lamp", "event:outage"),
        "required_plot_developments": ("Ada saw",),
    }
    values.update(changes)
    return EvalCase(**values)


def test_versioned_dataset_covers_every_required_category() -> None:
    dataset = load_cases(DATASET)

    assert dataset.version == 1
    assert {item.category for item in dataset.cases} == set(EvalCategory)
    report = EvaluationRunner().run(dataset)
    assert report.passed
    assert all(result.deterministic_score == 1 for result in report.results)


def test_deterministic_rules_report_every_failure_and_critical_leaks() -> None:
    findings = evaluate_rules(
        case(candidate="The hidden key means she never saw the lamp."),
        "The hidden key means she never saw the lamp.",
    )

    assert {finding.rule for finding in findings} == {
        "voice_markers",
        "belief_grounding",
        "secret_containment",
        "canon_facts",
        "canon_consistency",
        "rumor_traceability",
        "plot_progression",
    }
    assert not all(finding.passed for finding in findings)
    assert next(item for item in findings if item.rule == "secret_containment").critical
    assert (
        evaluate_rules(
            case(
                candidate="anything",
                character_voice_markers=(),
                grounded_claims=(),
                forbidden_secrets=(),
                canon_facts=(),
                forbidden_canon_claims=(),
                required_source_ids=(),
                required_plot_developments=(),
            ),
            "anything",
        )[0].rule
        == "nonempty"
    )


def test_recorded_mode_loads_outputs_and_rejects_bad_or_missing_data(tmp_path: Path) -> None:
    dataset = load_cases(DATASET)
    outputs = {item.id: item.candidate for item in dataset.cases}
    path = tmp_path / "recorded.json"
    path.write_text(json.dumps(outputs), encoding="utf-8")

    report = EvaluationRunner().run(
        dataset,
        mode=EvaluationMode.RECORDED,
        recorded_outputs=load_recorded_outputs(path),
    )

    assert report.passed
    with pytest.raises(ValueError, match="requires recorded outputs"):
        EvaluationRunner().run(dataset, mode=EvaluationMode.RECORDED)
    with pytest.raises(ValueError, match="missing case"):
        EvaluationRunner().run(dataset, mode=EvaluationMode.RECORDED, recorded_outputs={})
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        load_recorded_outputs(path)


def test_live_generation_and_model_grading_are_typed_and_budgeted() -> None:
    selected = case(
        candidate="unused",
        character_voice_markers=(),
        grounded_claims=(),
        forbidden_secrets=("hidden key",),
        canon_facts=(),
        forbidden_canon_claims=(),
        required_source_ids=(),
        required_plot_developments=(),
    )
    from rumor_mill.evals.runner import Dataset

    dataset = Dataset(version=1, cases=(selected,))
    responses: dict[str, dict[str, Any]] = {
        "narrative_eval_candidate:test-case": {"candidate": "A safe continuation."},
        "narrative_eval_grade:test-case": {
            "voice_fidelity": 4,
            "coherence": 5,
            "engagement": 3,
            "rationale": "Coherent and restrained.",
        },
    }
    runner = EvaluationRunner(
        provider=DeterministicFakeProvider(responses),
        grade_with_model=True,
        max_total_tokens=1000,
    )

    report = runner.run(dataset, mode=EvaluationMode.LIVE)

    assert report.passed
    assert report.input_tokens > 0 and report.output_tokens > 0
    assert report.results[0].grade == RubricGrade(
        voice_fidelity=4,
        coherence=5,
        engagement=3,
        rationale="Coherent and restrained.",
    )
    assert report.results[0].grade.average == 4
    with pytest.raises(TokenBudgetExceededError, match="budget exceeded"):
        EvaluationRunner(provider=DeterministicFakeProvider(responses), max_total_tokens=1).run(
            dataset, mode=EvaluationMode.LIVE
        )


def test_runner_validation_and_unexpected_provider_models() -> None:
    dataset = load_cases(DATASET)
    with pytest.raises(ValueError, match="cannot be negative"):
        EvaluationRunner(max_total_tokens=-1)
    with pytest.raises(ValueError, match="provider is required"):
        EvaluationRunner(grade_with_model=True)
    with pytest.raises(ValueError, match="live mode requires"):
        EvaluationRunner().run(dataset, mode=EvaluationMode.LIVE)

    class WrongProvider:
        def generate(self, request):  # type: ignore[no-untyped-def]
            from rumor_mill.engine.ports import GenerationResult, Usage

            return GenerationResult(
                data=RubricGrade(
                    voice_fidelity=3, coherence=3, engagement=3, rationale="Wrong shape."
                ),
                usage=Usage(0, 0, 0),
                provider="wrong",
                model="wrong",
                request_id="wrong",
            )

        def stream(self, request):  # type: ignore[no-untyped-def]
            return iter(())

    from rumor_mill.evals.runner import Dataset

    with pytest.raises(TypeError, match="unexpected candidate"):
        EvaluationRunner(provider=WrongProvider()).run(
            Dataset(version=1, cases=(case(),)), mode=EvaluationMode.LIVE
        )

    class WrongGrader(WrongProvider):
        calls = 0

        def generate(self, request):  # type: ignore[no-untyped-def]
            from rumor_mill.engine.ports import GenerationResult, Usage
            from rumor_mill.evals.runner import CandidateOutput

            self.calls += 1
            data = (
                CandidateOutput(candidate="A valid candidate.")
                if self.calls == 1
                else CandidateOutput(candidate="Wrong grade shape.")
            )
            return GenerationResult(
                data=data,
                usage=Usage(0, 0, 0),
                provider="wrong",
                model="wrong",
                request_id="wrong",
            )

    with pytest.raises(TypeError, match="unexpected rubric"):
        EvaluationRunner(provider=WrongGrader(), grade_with_model=True).run(
            Dataset(version=1, cases=(case(),)), mode=EvaluationMode.LIVE
        )


def test_thresholds_critical_failure_report_and_model_grade_failure() -> None:
    from rumor_mill.evals.runner import Dataset

    leaking = case(
        candidate="The hidden key is here.",
        character_voice_markers=(),
        grounded_claims=(),
        canon_facts=(),
        forbidden_canon_claims=(),
        required_source_ids=(),
        required_plot_developments=(),
    )
    report = EvaluationRunner().run(
        Dataset(version=1, cases=(leaking,)),
        thresholds=EvalThresholds(minimum_deterministic_score=0, fail_on_critical=True),
    )

    assert not report.passed
    rendered = markdown_report(report)
    assert "FAIL" in rendered and "secret_containment" in rendered
    with pytest.raises(ValueError, match="passed does not match"):
        EvalReport(
            dataset_version=1,
            mode=EvaluationMode.FIXTURE,
            results=report.results,
            thresholds=report.thresholds,
            passed=True,
        )


def test_cli_writes_ci_reports_and_returns_failure_status(tmp_path: Path) -> None:
    json_report = tmp_path / "nested/report.json"
    markdown = tmp_path / "nested/report.md"
    assert (
        main(
            [
                str(DATASET),
                "--json-report",
                str(json_report),
                "--markdown-report",
                str(markdown),
            ]
        )
        == 0
    )
    assert json.loads(json_report.read_text())["passed"] is True
    assert "PASS" in markdown.read_text()

    dataset = json.loads(DATASET.read_text())
    dataset["cases"][2]["candidate"] = "Elias disabled the beacon."
    failing = tmp_path / "failing.json"
    failing.write_text(json.dumps(dataset), encoding="utf-8")
    assert main([str(failing)]) == 1
