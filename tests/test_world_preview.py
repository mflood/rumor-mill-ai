"""Tests for the deployment-free world author preview."""

import json
from pathlib import Path

from rumor_mill.worlds.preview import main, preview_world

STARTER = Path(__file__).parents[1] / "docs" / "worlds" / "starter" / "world.json"


def test_starter_world_previews_event_conversation_and_episode_arc() -> None:
    preview = preview_world(STARTER)

    assert "# The Bell at Dusk" in preview
    assert "The Impossible Bell" in preview
    assert "A Question on the Platform" in preview
    assert "Completed: ask-oren, impossible-bell" in preview
    assert "Unreached during smoke run: none" in preview


def test_preview_cli_writes_markdown_without_database(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    output = tmp_path / "preview.md"

    assert main([str(STARTER), "--output", str(output)]) == 0
    assert "preview written" in capsys.readouterr().out
    assert "The Bell at Dusk" in output.read_text(encoding="utf-8")


def test_preview_cli_prints_markdown(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main([str(STARTER), "--days", "2"]) == 0
    assert "# The Bell at Dusk" in capsys.readouterr().out


def test_preview_cli_reports_continuity_errors(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    payload = json.loads(STARTER.read_text(encoding="utf-8"))
    payload["clues"].append(
        {"id": "orphan", "name": "Orphan", "description": "Never placed or discovered."}
    )
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(payload), encoding="utf-8")

    assert main([str(broken)]) == 1
    assert "orphan clue 'orphan'" in capsys.readouterr().err


def test_preview_cli_reports_schema_errors(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    broken = tmp_path / "broken.json"
    broken.write_text("{}", encoding="utf-8")

    assert main([str(broken)]) == 1
    assert "$.schema_version: Field required" in capsys.readouterr().err
