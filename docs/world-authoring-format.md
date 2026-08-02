# World-authoring guide

Authored worlds are JSON data validated by `rumor_mill.worlds.load_world`. They contain no Python
code and cannot call engine or operational APIs. The current format version is `1`. Start by copying
[`docs/worlds/starter`](worlds/starter/README.md), then edit its `world.json`.

## The authoring model

Separate objective events from what characters think and what the audience sees:

- **Canon** belongs in `truth`. A truth is an objective claim that the simulation may establish; its
  character and location references say what the claim is about, not who knows it.
- **Beliefs and rumors** are runtime subjective state. Author their source as a secret, clue, or beat
  outcome rather than declaring a character belief as canon. A secret says who initially holds and
  knows a restricted claim. Conversations and propagation may later produce conflicting beliefs.
- **Secrets** must remain `engine_only`. `holder_ids` lists everyone allowed to hold the secret at
  the start and `known_by_ids` must be a subset of it. Link each secret to its grounding truth.
- **Relationships** are directed. If two people are friends in both directions, author two records.
  Visibility controls whether the relationship is public, participant-only, or engine-only.
- **Schedules** are recurring presence windows, not scripted scenes. Give private `activity` text a
  spoiler-safe `public_activity`; add travel routes when consecutive routines change location.
- **Clues** are discoverable evidence. Place each clue on a location or have a beat discover it.
  Keep undiscovered clues non-public so presentation copy cannot leak them.
- **Beat graphs** describe required outcomes, not prose scripts. Dependencies control order;
  timing, deadlines, and missed-beat policy preserve progress; variants change presentation without
  changing what a beat establishes or reveals.
- **Disclosure** is explicit. `reveals_secret_ids`, `establishes_truth_ids`, and
  `discovers_clue_ids` are the only authored release gates. `protected_truth_ids` names facts that a
  beat can approach but must not expose.

The engine generates scenes, rumors, conversations, recaps, and episodes from this material. Author
conversation intent in a beat summary and its participants. Author an episode arc as a connected
run of beats. Do not put generated dialogue or episode prose into canonical truth.

## Authoring workflow

1. Copy `docs/worlds/starter` and give the world a unique lowercase slug.
2. Write the smallest cast, locations, and truths that support the premise.
3. Add secrets, relationships, clues, routines, and travel routes.
4. Build an entry beat and a short dependency chain. Confirm every beat can occur without a visitor.
5. Validate and preview locally:

   ```bash
   make preview-world WORLD=docs/worlds/my-world/world.json
   # or write a review artifact with a different deterministic selection seed
   uv run python -m rumor_mill.worlds.preview docs/worlds/my-world/world.json \
     --seed 7 --output artifacts/my-world-preview.md
   ```

The command reads only the JSON file, runs structural/reference and continuity validation, then
prints a deterministic fourteen-day Markdown transcript. It needs no database, model credentials,
server, or production deployment. Different seeds help review eligible branches; they are not a
substitute for testing every recovery path.

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
| `clues` | Discoverable evidence referenced by locations and beats. |
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
test fixture. Use [`docs/worlds/starter/world.json`](worlds/starter/world.json) as the author-facing
template; its companion README maps its event, rumor source, conversation intent, and episode arc.

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

Validation happens in two layers. `load_world` checks JSON syntax, the strict schema, IDs,
references, timing contracts, and graph cycles. The preview command additionally checks continuity:
overlapping or impossible schedules, missing travel routes, orphan clues, disclosure leaks, and
beats unreachable from an entry beat. It exits nonzero and prints every actionable field path when
either layer fails.

## Compatibility contract

- `schema_version` selects an exact reader contract. Version 1 files are never guessed, coerced from
  future versions, or silently rewritten.
- Within a schema version, additive runtime behavior may improve, but the meaning of existing fields
  and IDs remains stable. Authors should treat published entity IDs as permanent save-data keys.
- Adding a required field, changing a field's meaning, removing an accepted value, or changing
  disclosure semantics requires a new schema version and an explicit migration.
- Consumers must reject unsupported versions. A world is compatible only when its declared version
  has a reader and it passes both structural and continuity validation.
- Keep a source world and its preview artifact under version control. Re-run preview after engine or
  authoring changes; seed the runtime only after review succeeds.

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
