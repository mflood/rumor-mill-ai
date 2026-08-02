"""Rumor propagation and mutation tests."""

from typing import Any
from uuid import UUID

import pytest

from rumor_mill.engine.propagation import (
    MutationKind,
    PropagationOpportunity,
    RumorPropagation,
    RumorSeed,
)


def uid(value: int) -> Any:
    return UUID(int=value)


def rumor(*, salience: float = 1, secrecy: float = 0) -> RumorSeed:
    return RumorSeed(
        uid(10), uid(1), "Bea hid the brass key beneath the market stall.", salience, secrecy
    )


def chance(source: int, target: int, **values: float) -> PropagationOpportunity:
    return PropagationOpportunity(
        uid(source),
        uid(target),
        values.get("opportunity", 1),
        values.get("trust", 1),
        values.get("motive", 1),
    )


def test_seeded_propagation_is_reproducible_and_traceable() -> None:
    opportunities = (chance(1, 2), chance(2, 3), chance(3, 4))

    first = RumorPropagation(42).simulate(rumor(), opportunities)
    second = RumorPropagation(42).simulate(rumor(), opportunities)

    assert first == second
    assert first.edges == ((uid(1), uid(2)), (uid(2), uid(3)), (uid(3), uid(4)))
    assert first.metrics.transmissions == 3
    assert first.metrics.unique_recipients == 3
    assert first.metrics.max_depth == 3
    assert first.retellings[0].parent_id is None
    assert first.retellings[1].parent_id == first.retellings[0].id
    assert all(item.root_claim_id == rumor().claim_id for item in first.retellings)
    assert rumor().statement == "Bea hid the brass key beneath the market stall."


def test_all_five_factors_affect_transmission_score() -> None:
    engine = RumorPropagation(1)
    baseline = engine.transmission_score(rumor(salience=1, secrecy=0.5), chance(1, 2))

    assert engine.transmission_score(rumor(salience=0, secrecy=0.5), chance(1, 2)) < baseline
    assert (
        engine.transmission_score(rumor(salience=1, secrecy=1), chance(1, 2, motive=0)) < baseline
    )
    assert (
        engine.transmission_score(rumor(salience=1, secrecy=0.5), chance(1, 2, opportunity=0)) == 0
    )
    assert engine.transmission_score(rumor(salience=1, secrecy=0.5), chance(1, 2, trust=0)) == 0
    assert engine.transmission_score(rumor(salience=1, secrecy=1), chance(1, 2, motive=1)) > 0


def test_loop_suppression_stops_recirculation() -> None:
    graph = RumorPropagation(7).simulate(
        rumor(), (chance(1, 2), chance(2, 1), chance(2, 3), chance(3, 2))
    )

    assert graph.edges == ((uid(1), uid(2)), (uid(2), uid(3)))
    assert graph.metrics.attempts == 4
    assert graph.metrics.loop_suppressions == 2


def test_uninformed_speakers_and_failed_transmissions_do_not_spread() -> None:
    graph = RumorPropagation(3).simulate(
        rumor(), (chance(9, 8), chance(1, 2, opportunity=0), chance(2, 3))
    )

    assert graph.retellings == ()
    assert graph.metrics.attempts == 1
    assert graph.metrics.max_depth == 0
    assert graph.metrics.mutations == {kind: 0 for kind in MutationKind}


@pytest.mark.parametrize("kind", list(MutationKind))
def test_controlled_mutations_are_nonempty(kind: MutationKind) -> None:
    value = RumorPropagation._mutate("Ada saw Bea leave quietly.", kind)

    assert value
    if kind is MutationKind.NONE:
        assert value == "Ada saw Bea leave quietly."
    else:
        assert value != "Ada saw Bea leave quietly."


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: rumor(salience=-0.1), "salience"),
        (lambda: rumor(secrecy=1.1), "secrecy"),
        (lambda: chance(1, 1), "differ"),
        (lambda: chance(1, 2, trust=2), "trust"),
    ],
)
def test_inputs_are_validated(factory, message: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError, match=message):
        factory()


def test_empty_statement_is_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        RumorSeed(uid(10), uid(1), " ", 1, 0)
