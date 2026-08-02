# Starter world: The Bell at Dusk

This tiny world is meant to be copied. It contains two characters, one location, one directed
relationship, one canonical event, one secret that can become a rumor, one clue, one routine, and a
two-beat episode arc.

The first beat is the opening event. A visitor can influence its presentation and discover the clue.
The second beat is the intended conversation: Mara asks Oren about the bell. Together the two beats
form the starter episode outline; the runtime turns completed beats into scenes, conversations,
recaps, and published episodes.

From the repository root:

```bash
uv run python -m rumor_mill.worlds.preview docs/worlds/starter/world.json
```

Copy this directory, change `metadata.id`, and keep every ID stable after publication. See the
[world-authoring guide](../../world-authoring-format.md) before adding more locations or branches.
