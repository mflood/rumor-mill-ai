"""Command-line entry point for narrative evaluations."""

import argparse
import json
from pathlib import Path

from rumor_mill.adapters.providers import create_model_provider
from rumor_mill.config import get_settings
from rumor_mill.evals.models import EvalThresholds, EvaluationMode
from rumor_mill.evals.runner import (
    EvaluationRunner,
    load_cases,
    load_recorded_outputs,
    markdown_report,
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Run Rumor Mill narrative evaluations")
    command.add_argument("dataset", type=Path)
    command.add_argument(
        "--mode", choices=[item.value for item in EvaluationMode], default="fixture"
    )
    command.add_argument("--recorded", type=Path)
    command.add_argument("--model-grade", action="store_true")
    command.add_argument("--max-total-tokens", type=int, default=0)
    command.add_argument("--minimum-model-grade", type=float, default=3.0)
    command.add_argument("--minimum-deterministic-score", type=float, default=1.0)
    command.add_argument("--json-report", type=Path)
    command.add_argument("--markdown-report", type=Path)
    return command


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    mode = EvaluationMode(args.mode)
    needs_provider = mode is EvaluationMode.LIVE or args.model_grade
    provider = create_model_provider(get_settings()) if needs_provider else None
    recorded = load_recorded_outputs(args.recorded) if args.recorded else None
    report = EvaluationRunner(
        provider=provider,
        max_total_tokens=args.max_total_tokens,
        grade_with_model=args.model_grade,
    ).run(
        load_cases(args.dataset),
        mode=mode,
        recorded_outputs=recorded,
        thresholds=EvalThresholds(
            minimum_model_grade=args.minimum_model_grade,
            minimum_deterministic_score=args.minimum_deterministic_score,
        ),
    )
    rendered = markdown_report(report)
    print(rendered, end="")
    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(
            json.dumps(report.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
        )
    if args.markdown_report:
        args.markdown_report.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_report.write_text(rendered, encoding="utf-8")
    return 0 if report.passed else 1


if __name__ == "__main__":  # pragma: no cover - exercised through main
    raise SystemExit(main())
