"""Canonical read model for persisted public Lighthouse recaps."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from rumor_mill.adapters.persistence.models import ArtifactModel
from rumor_mill.engine.recap import DailyRecap, RecapPanel, RecapThread


class PublishedRecapView(BaseModel):
    """Stable presentation boundary shared by Today, Archive, and recommendations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    run_id: UUID
    published_at: datetime
    story_date: date
    headline: str
    dek: str
    panels: tuple[RecapPanel, ...]
    active_threads: tuple[RecapThread, ...]
    suggested_location_ids: tuple[str, ...]
    suggested_character_ids: tuple[str, ...]
    state: str


def as_published_recap(artifact: ArtifactModel) -> PublishedRecapView | None:
    """Validate publication state and project one artifact into the shared read model."""
    if (
        artifact.kind != "daily_recap"
        or artifact.payload.get("visibility", "public") != "public"
        or not artifact.payload.get("canonical", True)
    ):
        return None
    try:
        recap = DailyRecap.model_validate(artifact.payload["recap"])
    except (KeyError, ValueError):
        return None
    return PublishedRecapView(
        id=artifact.id,
        run_id=artifact.run_id,
        published_at=artifact.generated_at,
        story_date=recap.story_date,
        headline=recap.headline,
        dek=recap.dek,
        panels=recap.panels,
        active_threads=recap.active_threads,
        suggested_location_ids=recap.suggested_location_ids,
        suggested_character_ids=recap.suggested_character_ids,
        state=recap.state,
    )


def published_recaps(database: Session, run_id: UUID) -> list[PublishedRecapView]:
    """Return every valid publication in deterministic season order."""
    artifacts = database.scalars(
        select(ArtifactModel).where(
            ArtifactModel.run_id == run_id,
            ArtifactModel.kind == "daily_recap",
        )
    )
    recaps = [view for artifact in artifacts if (view := as_published_recap(artifact))]
    return sorted(recaps, key=lambda item: (item.story_date, str(item.id)))


def latest_published_recap(database: Session, run_id: UUID) -> PublishedRecapView | None:
    """Return the same final publication that Archive exposes in season order."""
    recaps = published_recaps(database, run_id)
    return recaps[-1] if recaps else None
