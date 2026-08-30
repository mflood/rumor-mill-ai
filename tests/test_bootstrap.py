"""Production Lighthouse bootstrap integration coverage."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from rumor_mill.adapters.persistence.models import (
    ArtifactModel,
    Base,
    RunModel,
    VisitorModel,
    WorldModel,
)
from rumor_mill.bootstrap import LIGHTHOUSE_PATH, bootstrap_lighthouse, main
from rumor_mill.engine.recap import DailyRecap
from rumor_mill.lighthouse_opening import opening_recap_id

pytestmark = pytest.mark.integration


def prepared_database(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'bootstrap.sqlite'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return url


def test_empty_database_bootstraps_one_wall_clock_lighthouse_season(tmp_path: Path) -> None:
    url = prepared_database(tmp_path)

    result = bootstrap_lighthouse(url)

    assert result.created_world is True
    assert result.created_run is True
    with Session(create_engine(url)) as database:
        assert database.scalar(select(func.count()).select_from(WorldModel)) == 1
        assert database.scalar(select(func.count()).select_from(RunModel)) == 1
        run = database.get(RunModel, result.run_id)
        assert run is not None and run.status == "running" and run.clock_mode == "wall"
        artifact = database.get(ArtifactModel, opening_recap_id(result.run_id))
        assert artifact is not None
        assert artifact.story_date == run.started_at.date()
        assert artifact.payload["visibility"] == "public"
        recap = DailyRecap.model_validate(artifact.payload["recap"])
        assert recap.headline == "Northlight goes dark."
        assert len(recap.panels) == 3
        # Regression test for P0-5: the opening recap must not attribute an observation
        # to a character (Iris) who holds no supporting claim about it and denies it
        # when asked directly in conversation.
        cliff_panel = next(
            panel for panel in recap.panels if panel.title == "A second light beneath the cliff"
        )
        assert cliff_panel.character_id is None
        assert "Iris" not in cliff_panel.body
        assert "iris" not in recap.suggested_character_ids


def test_repeat_bootstrap_selects_live_season_without_changing_state(tmp_path: Path) -> None:
    url = prepared_database(tmp_path)
    first = bootstrap_lighthouse(url)
    with Session(create_engine(url)) as database:
        database.add(
            VisitorModel(
                token_hash="a" * 64,
                last_seen_at=database.get(RunModel, first.run_id).started_at,  # type: ignore[union-attr]
                expires_at=database.get(RunModel, first.run_id).started_at,  # type: ignore[union-attr]
                active_run_id=first.run_id,
            )
        )
        database.commit()

    second = bootstrap_lighthouse(url)

    assert second.run_id == first.run_id
    assert second.created_world is False and second.created_run is False
    assert first.definition_updated is False and second.definition_updated is False
    with Session(create_engine(url)) as database:
        assert database.scalar(select(func.count()).select_from(VisitorModel)) == 1
        assert database.scalar(select(func.count()).select_from(RunModel)) == 1
        assert (
            database.scalar(
                select(func.count())
                .select_from(ArtifactModel)
                .where(ArtifactModel.kind == "daily_recap")
            )
            == 1
        )


def test_repeat_bootstrap_syncs_a_stale_stored_world_definition(tmp_path: Path) -> None:
    """Regression test: a redeploy must sync authored content changes into an existing world.

    Without this, a fix to docs/worlds/lighthouse/world.json (e.g. a routine-coverage fix)
    has zero effect in production once the world has been seeded once, since bootstrap only
    ever created a WorldModel row and never touched an existing one's definition.
    """
    url = prepared_database(tmp_path)
    first = bootstrap_lighthouse(url)
    assert first.definition_updated is False

    with Session(create_engine(url)) as database:
        world = database.get(WorldModel, first.world_id)
        assert world is not None
        stale = dict(world.definition)
        stale["routines"] = []  # simulate an older, pre-fix authored definition
        world.definition = stale
        database.commit()

    second = bootstrap_lighthouse(url)

    assert second.definition_updated is True
    assert second.world_id == first.world_id
    assert second.run_id == first.run_id
    with Session(create_engine(url)) as database:
        world = database.get(WorldModel, first.world_id)
        assert world is not None
        assert world.definition["routines"]


def test_repeat_bootstrap_syncs_a_stale_opening_recap(tmp_path: Path) -> None:
    """Regression test: a redeploy must sync authored opening-recap changes too.

    Without this, a content fix to lighthouse_opening.py (e.g. #97's fix removing an
    unsupported witness attribution) has zero effect on an already-bootstrapped run's
    already-published day-1 dispatch, since bootstrap only ever created the opening
    recap artifact once and never touched an existing one's content.
    """
    url = prepared_database(tmp_path)
    first = bootstrap_lighthouse(url)
    assert first.opening_recap_updated is False

    with Session(create_engine(url)) as database:
        artifact = database.get(ArtifactModel, opening_recap_id(first.run_id))
        assert artifact is not None
        stale_payload = dict(artifact.payload)
        stale_payload["recap"] = {**stale_payload["recap"], "headline": "An older headline."}
        artifact.title = "An older headline."
        artifact.payload = stale_payload
        database.commit()

    second = bootstrap_lighthouse(url)

    assert second.opening_recap_updated is True
    assert second.run_id == first.run_id
    with Session(create_engine(url)) as database:
        artifact = database.get(ArtifactModel, opening_recap_id(first.run_id))
        assert artifact is not None
        assert artifact.title == "Northlight goes dark."


def test_repeat_bootstrap_tolerates_an_opening_recap_with_a_drifted_id(tmp_path: Path) -> None:
    """Regression test: recognize an existing opening recap by its natural key.

    A production run's opening-recap artifact id no longer matched what
    opening_recap_id() computes today (its derivation drifted across a code
    change), so the id-based existence check missed it and re-bootstrapping
    tried to INSERT a second row, violating the (run_id, kind, story_date)
    unique constraint. Recognizing the row by that same natural key instead
    of the artifact's primary key must survive an id mismatch like this.
    """
    url = prepared_database(tmp_path)
    first = bootstrap_lighthouse(url)
    with Session(create_engine(url)) as database:
        artifact = database.get(ArtifactModel, opening_recap_id(first.run_id))
        assert artifact is not None
        drifted = ArtifactModel(
            id=uuid4(),
            run_id=artifact.run_id,
            kind=artifact.kind,
            title=artifact.title,
            body=artifact.body,
            generated_at=artifact.generated_at,
            story_date=artifact.story_date,
            source_ids=artifact.source_ids,
            payload=artifact.payload,
        )
        database.delete(artifact)
        database.flush()
        database.add(drifted)
        database.commit()

    second = bootstrap_lighthouse(url)

    assert second.run_id == first.run_id
    assert second.created_run is False
    with Session(create_engine(url)) as database:
        assert (
            database.scalar(
                select(func.count())
                .select_from(ArtifactModel)
                .where(ArtifactModel.kind == "daily_recap")
            )
            == 1
        )


def test_failed_validation_leaves_prepared_database_untouched(tmp_path: Path) -> None:
    url = prepared_database(tmp_path)
    payload = json.loads(LIGHTHOUSE_PATH.read_text(encoding="utf-8"))
    payload["clues"].append({"id": "orphan", "name": "Orphan", "description": "Unused"})
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="continuity validation failed"):
        bootstrap_lighthouse(url, invalid)

    with Session(create_engine(url)) as database:
        assert database.scalar(select(func.count()).select_from(WorldModel)) == 0


def test_bootstrap_cli_reports_selected_ids(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    url = prepared_database(tmp_path)

    assert main(["--database-url", url]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["world_id"] and output["run_id"]
    assert output["created_world"] is True
