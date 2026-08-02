"""Authored-world contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from rumor_mill.engine.domain.base import (
    CharacterId,
    ContractModel,
    Lifecycle,
    LocationId,
    RelationshipId,
    Visibility,
    _require_aware,
)


class RelationshipKind(StrEnum):
    FAMILY = "family"
    FRIEND = "friend"
    RIVAL = "rival"
    ROMANTIC = "romantic"
    PROFESSIONAL = "professional"
    ACQUAINTANCE = "acquaintance"


class Character(ContractModel):
    schema_version: Literal[1] = 1
    id: CharacterId
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2_000)
    home_location_id: LocationId | None = None
    visibility: Visibility = Visibility.PUBLIC
    lifecycle: Lifecycle


class Location(ContractModel):
    schema_version: Literal[1] = 1
    id: LocationId
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2_000)
    parent_location_id: LocationId | None = None
    visibility: Visibility = Visibility.PUBLIC
    lifecycle: Lifecycle


class Relationship(ContractModel):
    schema_version: Literal[1] = 1
    id: RelationshipId
    source_character_id: CharacterId
    target_character_id: CharacterId
    kind: RelationshipKind
    began_at: datetime
    visibility: Visibility = Visibility.PARTICIPANTS
    lifecycle: Lifecycle

    @model_validator(mode="after")
    def validate_relationship(self) -> Self:
        _require_aware(self.began_at, "began_at")
        if self.source_character_id == self.target_character_id:
            raise ValueError("relationship endpoints must be different characters")
        return self
