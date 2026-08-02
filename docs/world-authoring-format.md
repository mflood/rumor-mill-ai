# World-authoring format

Authored worlds are JSON data validated by `rumor_mill.worlds.load_world`. They contain no Python
code and cannot call engine or operational APIs. The current format version is `1`.

## Version 1 sections

| Field | Purpose |
| --- | --- |
| `schema_version` | Selects the exact contract and migration path. Must be `1`. |
| `metadata` | Stable world ID, display title, summary, author, and content rating. |
| `cast` | Characters and optional home-location references. |
| `locations` | Locations and optional parent-location references. |
| `initial_relationships` | Directed relationships between cast members. |
| `truth` | Objective canonical facts and their character/location subjects. |
| `secrets` | Restricted statements, their holders/knowers, and underlying truth. |
| `beat_graph` | Entry beats, dependencies, participants, settings, truths, and revelations. |

Entity IDs are lowercase slugs such as `old-lighthouse`. They are stable authoring identifiers, not
database IDs. Runtime seeding translates them into typed UUIDs while retaining the slug as source
provenance.

The generated JSON Schema is available from Python:

```python
from rumor_mill.worlds import WorldDefinition

schema = WorldDefinition.model_json_schema()
```

See [`tests/fixtures/worlds/minimal.json`](../tests/fixtures/worlds/minimal.json) for a complete small
world.

## Validation errors

Always load files through `load_world(path)`. `WorldLoadError` reports the source filename and a
JSON-style field path for malformed JSON, structural schema failures, duplicate IDs, broken entity
references, self-references, and beat-graph cycles. A representative message is:

```text
world.json:$.beat_graph.beats[0].location_id: unknown location id 'harbor'
```

## Migration strategy

Published world files are immutable with respect to their declared schema version.

1. Add the next schema as new versioned models; do not loosen or reinterpret version 1 in place.
2. Add a pure, deterministic `migrate_vN_to_vN_plus_1` function operating on parsed JSON data.
3. Preserve unknown-version rejection so authors never receive a best-effort load.
4. Chain one-version migrations in the loader only when explicitly requested by a migration command;
   ordinary loading validates the declared version without silently rewriting it.
5. Test each migration with before/after golden fixtures and retain fixtures for every supported
   version.
6. Remove an old reader only in a major product release after all bundled worlds and persisted source
   files have been migrated.

This keeps authored content reproducible and makes every breaking format change reviewable.
