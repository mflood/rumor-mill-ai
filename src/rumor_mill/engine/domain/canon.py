"""Immutable canonical story records."""

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from rumor_mill.engine.domain.base import (
    CharacterId,
    ContractModel,
    EventId,
    Lifecycle,
    LocationId,
    Provenance,
    SceneId,
    Visibility,
    _require_aware,
)


class Event(ContractModel):
    """An objective occurrence in canon; corrections create a successor record."""

    schema_version: Literal[1] = 1
    id: EventId
    occurred_at: datetime
    summary: str = Field(min_length=1, max_length=2_000)
    participant_ids: tuple[CharacterId, ...] = ()
    location_id: LocationId | None = None
    provenance: Provenance
    visibility: Visibility = Visibility.PUBLIC
    lifecycle: Lifecycle

    @model_validator(mode="after")
    def validate_event(self) -> Self:
        _require_aware(self.occurred_at, "occurred_at")
        if len(set(self.participant_ids)) != len(self.participant_ids):
            raise ValueError("participant_ids must be unique")
        return self


class Scene(ContractModel):
    """A canonical grouping and ordering of events."""

    schema_version: Literal[1] = 1
    id: SceneId
    title: str = Field(min_length=1, max_length=200)
    event_ids: tuple[EventId, ...] = Field(min_length=1)
    starts_at: datetime
    ends_at: datetime
    location_id: LocationId | None = None
    provenance: Provenance
    visibility: Visibility = Visibility.PUBLIC
    lifecycle: Lifecycle

    @model_validator(mode="after")
    def validate_scene(self) -> Self:
        _require_aware(self.starts_at, "starts_at")
        _require_aware(self.ends_at, "ends_at")
        if self.ends_at < self.starts_at:
            raise ValueError("ends_at cannot be before starts_at")
        if len(set(self.event_ids)) != len(self.event_ids):
            raise ValueError("event_ids must be unique")
        return self
