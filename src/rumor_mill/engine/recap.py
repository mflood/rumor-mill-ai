"""Build spoiler-safe daily recaps from public presentation artifacts."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from rumor_mill.engine.domain import ArtifactKind

PUBLIC_RECAP_SOURCE_KINDS = tuple(
    kind.value for kind in ArtifactKind if kind is not ArtifactKind.DAILY_RECAP
)


class RecapSource(BaseModel):
    """A presentation-layer candidate; hidden domain records are never accepted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    kind: str
    title: str
    body: str
    generated_at: datetime
    visibility: str = "public"
    importance: int = Field(default=1, ge=0, le=5)
    location_id: str | None = None
    character_id: str | None = None
    active_thread: str | None = None


class RecapPanel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: UUID
    title: str
    body: str
    location_id: str | None = None
    character_id: str | None = None


class RecapThread(BaseModel):
    """An unresolved public thread, linked to whoever or wherever can advance it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    character_id: str | None = None
    location_id: str | None = None


class DailyRecap(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    story_date: date
    headline: str
    dek: str
    panels: tuple[RecapPanel, ...]
    active_threads: tuple[RecapThread, ...]
    suggested_location_ids: tuple[str, ...]
    suggested_character_ids: tuple[str, ...]
    state: str

    def artifact_payload(self) -> dict[str, Any]:
        return {
            "visibility": "public",
            "canonical": True,
            "recap": self.model_dump(mode="json"),
        }


def build_daily_recap(story_date: date, sources: list[RecapSource]) -> DailyRecap:
    """Rank public presentation hooks without consulting canon, beliefs, or memories."""
    public = [item for item in sources if item.visibility == "public"]
    public.sort(key=lambda item: (item.importance, item.generated_at), reverse=True)
    selected = public[:4]
    panels = tuple(
        RecapPanel(
            source_id=item.id,
            title=item.title,
            body=item.body,
            location_id=item.location_id,
            character_id=item.character_id,
        )
        for item in selected
    )
    threads_by_text: dict[str, RecapThread] = {}
    for item in selected:
        if item.active_thread and item.active_thread not in threads_by_text:
            threads_by_text[item.active_thread] = RecapThread(
                text=item.active_thread,
                character_id=item.character_id,
                location_id=item.location_id,
            )
    threads = tuple(threads_by_text.values())
    locations = tuple(dict.fromkeys(item.location_id for item in selected if item.location_id))
    characters = tuple(dict.fromkeys(item.character_id for item in selected if item.character_id))
    if not panels:
        return DailyRecap(
            story_date=story_date,
            headline="Greyhaven holds its breath",
            dek="No public dispatches were filed today. The town is still moving beyond view.",
            panels=(),
            active_threads=(),
            suggested_location_ids=(),
            suggested_character_ids=(),
            state="quiet_day",
        )
    dispatch_word = "dispatch" if len(panels) == 1 else "dispatches"
    return DailyRecap(
        story_date=story_date,
        headline=selected[0].title,
        dek=f"{len(panels)} public {dispatch_word} from Greyhaven today.",
        panels=panels,
        active_threads=threads,
        suggested_location_ids=locations,
        suggested_character_ids=characters,
        state="first_day" if not threads else "active",
    )
