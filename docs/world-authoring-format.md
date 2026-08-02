# World-authoring format

Authored worlds are JSON data validated by `rumor_mill.worlds.load_world`. They contain no Python
code and cannot call engine or operational APIs. The current format version is `1`.

## Version 1 sections

| Field | Purpose |
| --- | --- |
| `schema_version` | Selects the exact contract and migration path. Must be `1`. |
| `metadata` | Stable world ID, display title, summary, author, and content rating. |
| `cast` | Characters and optional home-location references. |
| `locations` | Places, presentation copy, access rules, and clue stewardship. |
| `initial_relationships` | Directed relationships between cast members. |
| `truth` | Objective canonical facts and their character/location subjects. |
| `secrets` | Restricted statements, their holders/knowers, and underlying truth. |
| `beat_graph` | Timed story beats, dependencies, recovery paths, participants, settings, truths, and revelations. |
| `routines` | Recurring fourteen-day presence windows and spoiler-safe public explanations. |
| `travel_routes` | Timed geography edges and traversal constraints. |

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

### Beat contracts

Every beat has a role and a fourteen-day execution window (`earliest_day` through `latest_day`). An
optional `deadline_day` marks when the scheduler should begin recovery rather than continuing to
wait for an ideal scene. `depends_on` contains hard prerequisites; a beat cannot fire until all are
recorded. `fallback_beat_ids` names authored substitutes when `missed_beat_policy` is `fallback`.
The other policies let the season clock pause or let the scheduler accelerate the beat into the next
eligible scene.

`protected_truth_ids` are facts that the beat may build toward but must not disclose. Variants can
change setting, speaker, or presentation when their written condition holds, but inherit the parent
beat's timing, disclosures, and protections. `participation` may be `visitor-influenced`, allowing a
visitor to affect discovery order or relationships; there is deliberately no visitor-required mode.
Every beat must remain executable by the simulation without a particular visitor.

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
