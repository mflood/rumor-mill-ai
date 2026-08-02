"""Transactional seed operations expressed through engine ports."""

from rumor_mill.engine.ports import RunRecord, UnitOfWork, WorldRecord


def seed_run(unit_of_work: UnitOfWork, world: WorldRecord, run: RunRecord) -> None:
    """Atomically seed an authored world and its first simulation run."""

    if run.world_id != world.id:
        raise ValueError("run.world_id must match world.id")
    with unit_of_work:
        unit_of_work.worlds.add(world)
        unit_of_work.flush()
        unit_of_work.runs.add(run)
        unit_of_work.commit()
