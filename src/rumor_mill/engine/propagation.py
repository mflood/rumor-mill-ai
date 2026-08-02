"""Seeded, traceable rumor propagation without mutation of canonical claims."""

from dataclasses import dataclass
from enum import StrEnum
from random import Random
from uuid import UUID, uuid5

from rumor_mill.engine.domain import CharacterId, ClaimId


class MutationKind(StrEnum):
    NONE = "none"
    OMISSION = "omission"
    EXAGGERATION = "exaggeration"
    REINTERPRETATION = "reinterpretation"


@dataclass(frozen=True, slots=True)
class RumorSeed:
    claim_id: ClaimId
    speaker_id: CharacterId
    statement: str
    salience: float
    secrecy: float

    def __post_init__(self) -> None:
        if not self.statement.strip():
            raise ValueError("rumor statement cannot be empty")
        _probability("salience", self.salience)
        _probability("secrecy", self.secrecy)


@dataclass(frozen=True, slots=True)
class PropagationOpportunity:
    speaker_id: CharacterId
    listener_id: CharacterId
    opportunity: float
    trust: float
    motive: float

    def __post_init__(self) -> None:
        if self.speaker_id == self.listener_id:
            raise ValueError("speaker and listener must differ")
        _probability("opportunity", self.opportunity)
        _probability("trust", self.trust)
        _probability("motive", self.motive)


@dataclass(frozen=True, slots=True)
class Retelling:
    id: UUID
    root_claim_id: ClaimId
    parent_id: UUID | None
    speaker_id: CharacterId
    listener_id: CharacterId
    statement: str
    mutation: MutationKind
    transmission_score: float
    depth: int


@dataclass(frozen=True, slots=True)
class PropagationMetrics:
    attempts: int
    transmissions: int
    loop_suppressions: int
    unique_recipients: int
    max_depth: int
    mutations: dict[MutationKind, int]


@dataclass(frozen=True, slots=True)
class PropagationGraph:
    seed: RumorSeed
    retellings: tuple[Retelling, ...]
    metrics: PropagationMetrics

    @property
    def edges(self) -> tuple[tuple[CharacterId, CharacterId], ...]:
        return tuple((item.speaker_id, item.listener_id) for item in self.retellings)


class RumorPropagation:
    """Evaluates ordered opportunities using a local seeded random stream."""

    _namespace = UUID("a72c98c8-1816-4a68-a152-d71418f1928f")

    def __init__(self, seed: int) -> None:
        self._random = Random(seed)
        self._id_seed = seed

    def simulate(
        self, rumor: RumorSeed, opportunities: tuple[PropagationOpportunity, ...]
    ) -> PropagationGraph:
        heard: dict[CharacterId, Retelling | None] = {rumor.speaker_id: None}
        records: list[Retelling] = []
        suppressions = 0
        attempts = 0

        for candidate in opportunities:
            source = heard.get(candidate.speaker_id)
            if candidate.speaker_id not in heard:
                continue
            attempts += 1
            if candidate.listener_id in heard:
                suppressions += 1
                continue
            score = self.transmission_score(rumor, candidate)
            if self._random.random() >= score:
                continue
            parent_statement = rumor.statement if source is None else source.statement
            mutation = self._choose_mutation(rumor, candidate)
            statement = self._mutate(parent_statement, mutation)
            depth = 1 if source is None else source.depth + 1
            record = Retelling(
                id=uuid5(
                    self._namespace,
                    f"{self._id_seed}:{rumor.claim_id}:{len(records)}:{candidate.listener_id}",
                ),
                root_claim_id=rumor.claim_id,
                parent_id=None if source is None else source.id,
                speaker_id=candidate.speaker_id,
                listener_id=candidate.listener_id,
                statement=statement,
                mutation=mutation,
                transmission_score=score,
                depth=depth,
            )
            records.append(record)
            heard[candidate.listener_id] = record

        mutation_counts = {kind: 0 for kind in MutationKind}
        for record in records:
            mutation_counts[record.mutation] += 1
        return PropagationGraph(
            seed=rumor,
            retellings=tuple(records),
            metrics=PropagationMetrics(
                attempts=attempts,
                transmissions=len(records),
                loop_suppressions=suppressions,
                unique_recipients=max(0, len(heard) - 1),
                max_depth=max((record.depth for record in records), default=0),
                mutations=mutation_counts,
            ),
        )

    @staticmethod
    def transmission_score(rumor: RumorSeed, candidate: PropagationOpportunity) -> float:
        # Secrecy makes disclosure less likely; motive can overcome that reluctance.
        disclosure = (1 - rumor.secrecy) + rumor.secrecy * candidate.motive
        score = (
            candidate.opportunity * candidate.trust * (0.25 + 0.75 * rumor.salience) * disclosure
        )
        return round(min(1.0, max(0.0, score)), 6)

    def _choose_mutation(self, rumor: RumorSeed, candidate: PropagationOpportunity) -> MutationKind:
        mutation_chance = min(0.9, 0.1 + 0.35 * rumor.salience + 0.25 * candidate.motive)
        if self._random.random() >= mutation_chance:
            return MutationKind.NONE
        return self._random.choice(
            (MutationKind.OMISSION, MutationKind.EXAGGERATION, MutationKind.REINTERPRETATION)
        )

    @staticmethod
    def _mutate(statement: str, mutation: MutationKind) -> str:
        words = statement.split()
        if mutation is MutationKind.NONE:
            return statement
        if mutation is MutationKind.OMISSION:
            retained = words[: max(1, (len(words) + 1) // 2)]
            return f"{' '.join(retained)}…"
        if mutation is MutationKind.EXAGGERATION:
            return f"Apparently, {statement.rstrip('.')} — and it is more serious than it sounds."
        return f"It may mean that {statement[0].lower() + statement[1:]}"


def _probability(name: str, value: float) -> None:
    if not 0 <= value <= 1:
        raise ValueError(f"{name} must be between 0 and 1")
