"""Deterministic narrative checks, kept separate from subjective model grading."""

import re

from rumor_mill.evals.models import EvalCase, RuleFinding


def _contains(text: str, phrase: str) -> bool:
    return phrase.casefold() in text.casefold()


def _finding(rule: str, passed: bool, detail: str, *, critical: bool = False) -> RuleFinding:
    return RuleFinding(rule=rule, passed=passed, detail=detail, critical=critical)


def evaluate_rules(case: EvalCase, candidate: str) -> tuple[RuleFinding, ...]:
    """Run every applicable exact rule for a case."""

    checks: list[RuleFinding] = []
    if case.character_voice_markers:
        matched = [
            marker for marker in case.character_voice_markers if _contains(candidate, marker)
        ]
        checks.append(
            _finding(
                "voice_markers",
                bool(matched),
                f"matched {len(matched)}/{len(case.character_voice_markers)} voice markers",
            )
        )
    if case.grounded_claims:
        missing = [claim for claim in case.grounded_claims if not _contains(candidate, claim)]
        checks.append(
            _finding("belief_grounding", not missing, f"missing grounded claims: {missing}")
        )
    if case.forbidden_secrets:
        leaked = [secret for secret in case.forbidden_secrets if _contains(candidate, secret)]
        checks.append(
            _finding(
                "secret_containment",
                not leaked,
                f"leaked forbidden secrets: {leaked}",
                critical=True,
            )
        )
    if case.canon_facts:
        missing = [fact for fact in case.canon_facts if not _contains(candidate, fact)]
        checks.append(_finding("canon_facts", not missing, f"missing canon facts: {missing}"))
    if case.forbidden_canon_claims:
        conflicts = [claim for claim in case.forbidden_canon_claims if _contains(candidate, claim)]
        checks.append(
            _finding("canon_consistency", not conflicts, f"contradicting claims: {conflicts}")
        )
    if case.required_source_ids:
        cited = set(re.findall(r"\b(?:event|claim|memory):[a-z0-9-]+\b", candidate.casefold()))
        missing = [source for source in case.required_source_ids if source.casefold() not in cited]
        checks.append(_finding("rumor_traceability", not missing, f"missing sources: {missing}"))
    if case.required_plot_developments:
        missing = [
            development
            for development in case.required_plot_developments
            if not _contains(candidate, development)
        ]
        checks.append(_finding("plot_progression", not missing, f"missing developments: {missing}"))
    if not checks:
        checks.append(_finding("nonempty", bool(candidate.strip()), "candidate must not be empty"))
    return tuple(checks)
