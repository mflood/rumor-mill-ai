"""Typed contracts for reproducible narrative evaluations."""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

NonEmptyText = Annotated[str, Field(min_length=1, max_length=20_000)]


class EvalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvalCategory(StrEnum):
    VOICE_FIDELITY = "voice_fidelity"
    BELIEF_GROUNDING = "belief_grounding"
    SECRET_CONTAINMENT = "secret_containment"
    CANON_CONSISTENCY = "canon_consistency"
    RUMOR_TRACEABILITY = "rumor_traceability"
    PLOT_PROGRESSION = "plot_progression"


class EvaluationMode(StrEnum):
    FIXTURE = "fixture"
    RECORDED = "recorded"
    LIVE = "live"


class EvalCase(EvalModel):
    id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]*$")]
    category: EvalCategory
    prompt: NonEmptyText
    candidate: NonEmptyText
    character_voice_markers: tuple[NonEmptyText, ...] = ()
    grounded_claims: tuple[NonEmptyText, ...] = ()
    forbidden_secrets: tuple[NonEmptyText, ...] = ()
    canon_facts: tuple[NonEmptyText, ...] = ()
    forbidden_canon_claims: tuple[NonEmptyText, ...] = ()
    required_source_ids: tuple[NonEmptyText, ...] = ()
    prior_plot_state: tuple[NonEmptyText, ...] = ()
    required_plot_developments: tuple[NonEmptyText, ...] = ()


class RuleFinding(EvalModel):
    rule: str
    passed: bool
    critical: bool = False
    detail: str


class RubricGrade(EvalModel):
    voice_fidelity: int = Field(ge=1, le=5)
    coherence: int = Field(ge=1, le=5)
    engagement: int = Field(ge=1, le=5)
    rationale: Annotated[str, Field(min_length=1, max_length=1_000)]

    @property
    def average(self) -> float:
        return (self.voice_fidelity + self.coherence + self.engagement) / 3


class CaseResult(EvalModel):
    case_id: str
    category: EvalCategory
    candidate: str
    findings: tuple[RuleFinding, ...]
    grade: RubricGrade | None = None

    @property
    def deterministic_score(self) -> float:
        return sum(item.passed for item in self.findings) / len(self.findings)


class EvalThresholds(EvalModel):
    minimum_deterministic_score: float = Field(default=1.0, ge=0, le=1)
    minimum_model_grade: float = Field(default=3.0, ge=1, le=5)
    fail_on_critical: bool = True


class EvalReport(EvalModel):
    dataset_version: int = Field(ge=1)
    mode: EvaluationMode
    results: tuple[CaseResult, ...] = Field(min_length=1)
    thresholds: EvalThresholds
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    passed: bool

    @model_validator(mode="after")
    def validate_passed(self) -> Self:
        expected = all(
            result.deterministic_score >= self.thresholds.minimum_deterministic_score
            and (
                result.grade is None or result.grade.average >= self.thresholds.minimum_model_grade
            )
            and not (
                self.thresholds.fail_on_critical
                and any(item.critical and not item.passed for item in result.findings)
            )
            for result in self.results
        )
        if self.passed != expected:
            raise ValueError("passed does not match results and thresholds")
        return self
