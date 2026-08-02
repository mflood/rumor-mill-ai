"""Production Lighthouse bootstrap integration coverage."""

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from rumor_mill.adapters.persistence.models import Base, RunModel, VisitorModel, WorldModel
from rumor_mill.bootstrap import LIGHTHOUSE_PATH, bootstrap_lighthouse, main

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
    with Session(create_engine(url)) as database:
        assert database.scalar(select(func.count()).select_from(VisitorModel)) == 1
        assert database.scalar(select(func.count()).select_from(RunModel)) == 1


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
