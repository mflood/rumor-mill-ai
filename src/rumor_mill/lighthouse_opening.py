"""Deterministic authored opening publication for a Lighthouse season."""

from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from rumor_mill.adapters.persistence.models import ArtifactModel
from rumor_mill.engine.recap import DailyRecap, RecapPanel, RecapThread


def opening_recap_id(run_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"rumor-mill:lighthouse:{run_id}:opening-recap")


def opening_source_id(run_id: UUID, index: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"rumor-mill:lighthouse:{run_id}:opening-panel:{index}")


def opening_recap(run_id: UUID, started_at: datetime) -> DailyRecap:
    """Return the authored Episode 1 content with stable panel source metadata."""
    return DailyRecap(
        story_date=started_at.date(),
        headline="Northlight goes dark.",
        dek=(
            "A storm swallowed the harbor at 9:17. When the clouds broke, the lighthouse "
            "was dark—and its keeper was gone."
        ),
        panels=(
            RecapPanel(
                source_id=opening_source_id(run_id, 1),
                title="The beam vanished mid-sweep",
                body=(
                    "Three boats saw the same sudden darkness. None agree on what moved "
                    "across the lantern room first."
                ),
                location_id="northlight",
                character_id="mara",
            ),
            RecapPanel(
                source_id=opening_source_id(run_id, 2),
                title="A skiff returned empty",
                body=(
                    "Elias Rook's red skiff struck the west pier with one oar missing and "
                    "its lamp still warm."
                ),
                location_id="harbor-dispatch",
                character_id="elias",
            ),
            RecapPanel(
                source_id=opening_source_id(run_id, 3),
                title="A second light beneath the cliff",
                body=(
                    "A second light moved near Widow's Steps before the storm broke. No one "
                    "who saw it will say who stood beside it."
                ),
                location_id="widows-steps",
                character_id=None,
            ),
        ),
        active_threads=(
            RecapThread(text="What crossed the lantern room?", character_id="mara"),
            RecapThread(text="Who was beneath the cliff?", location_id="widows-steps"),
            RecapThread(text="Why was the skiff lamp warm?", character_id="elias"),
        ),
        suggested_location_ids=("northlight", "harbor-dispatch", "widows-steps"),
        suggested_character_ids=("mara", "elias"),
        state="first_day",
    )


def opening_recap_artifact(run_id: UUID, started_at: datetime) -> ArtifactModel:
    recap = opening_recap(run_id, started_at)
    return ArtifactModel(
        id=opening_recap_id(run_id),
        run_id=run_id,
        kind="daily_recap",
        title=recap.headline,
        body=recap.dek,
        generated_at=started_at,
        story_date=recap.story_date,
        source_ids=[str(panel.source_id) for panel in recap.panels],
        payload=recap.artifact_payload(),
    )
