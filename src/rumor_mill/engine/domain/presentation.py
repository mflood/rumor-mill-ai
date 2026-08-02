"""Disposable presentation contracts; never a source of canonical truth."""

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from rumor_mill.engine.domain.base import (
    ClaimId,
    ContractModel,
    EventId,
    Lifecycle,
    PresentationArtifactId,
    Provenance,
    SceneId,
    Visibility,
    _require_aware,
)


class ArtifactKind(StrEnum):
    SCENE_PAGE = "scene_page"
    STORY_CARD = "story_card"
    CHARACTER_UPDATE = "character_update"
    RUMOR_CARD = "rumor_card"


class PresentationArtifact(ContractModel):
    """Rendered content referencing domain records by ID only."""

    schema_version: Literal[1] = 1
    id: PresentationArtifactId
    kind: ArtifactKind
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20_000)
    source_scene_ids: tuple[SceneId, ...] = ()
    source_event_ids: tuple[EventId, ...] = ()
    source_claim_ids: tuple[ClaimId, ...] = ()
    generated_at: datetime
    provenance: Provenance
    visibility: Visibility = Visibility.PUBLIC
    lifecycle: Lifecycle

    @model_validator(mode="after")
    def validate_sources(self) -> Self:
        _require_aware(self.generated_at, "generated_at")
        sources = self.source_scene_ids + self.source_event_ids + self.source_claim_ids
        if not sources:
            raise ValueError("presentation artifact requires at least one source")
        if len(set(sources)) != len(sources):
            raise ValueError("presentation source IDs must be unique")
        return self
