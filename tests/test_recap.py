"""Daily recap selection and disclosure boundaries."""

from datetime import UTC, date, datetime
from uuid import UUID

from rumor_mill.engine.recap import RecapSource, RecapThread, build_daily_recap

NOW = datetime(2026, 8, 2, 20, tzinfo=UTC)


def source(number: int, *, visibility: str = "public", importance: int = 1) -> RecapSource:
    return RecapSource(
        id=UUID(int=number),
        kind="story_card",
        title=f"Dispatch {number}",
        body=f"Public account {number}",
        generated_at=NOW,
        visibility=visibility,
        importance=importance,
        location_id="harbor",
        character_id="mara",
        active_thread="Why did the light fail?",
    )


def test_recap_ranks_consequential_public_sources_and_deduplicates_cues() -> None:
    recap = build_daily_recap(date(2026, 8, 2), [source(1), source(2, importance=5)])

    assert recap.headline == "Dispatch 2"
    assert [panel.source_id for panel in recap.panels] == [UUID(int=2), UUID(int=1)]
    assert recap.active_threads == (
        RecapThread(text="Why did the light fail?", character_id="mara", location_id="harbor"),
    )
    assert recap.suggested_location_ids == ("harbor",)


def test_recap_never_includes_nonpublic_presentation_sources() -> None:
    recap = build_daily_recap(
        date(2026, 8, 2), [source(1), source(2, visibility="engine_only", importance=5)]
    )

    assert len(recap.panels) == 1
    assert UUID(int=2) not in {panel.source_id for panel in recap.panels}


def test_quiet_day_has_a_useful_empty_state() -> None:
    recap = build_daily_recap(date(2026, 8, 2), [])

    assert recap.state == "quiet_day"
    assert recap.panels == ()
    assert "still moving" in recap.dek
