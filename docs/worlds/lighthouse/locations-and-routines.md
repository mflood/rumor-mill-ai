# The Lighthouse: locations, routines, and encounter opportunities

Status: launch canon<br>
Canon owner: authored world<br>
Last revised: 2026-08-02

This document turns the story bible's geography and cast habits into scene-planning constraints.
A scheduled presence permits an encounter; it does not force one. Private activities and clue access
must never appear in public town-state responses.

## Locations

### Northlight Lighthouse (`northlight`)

- **Purpose:** Operational center of the mystery and Mara's public workplace.
- **Atmosphere:** Wind presses salt against glass; brass, oil, and precise logs resist it.
- **Public copy:** Northlight works again, but its white eye crosses a headland still under inquiry.
- **Access:** Yard and keeper's house by invitation; tower and service room only with Mara or council
  authority. Storm conditions close the north path.
- **Clues:** E01, E02, E04, E05. Exact positions remain private until discovery.

### Harbor Dispatch (`harbor-dispatch`)

- **Purpose:** Public exchange for tides, calls, searches, and manifests.
- **Atmosphere:** A valve radio warms the cramped room beneath clipped notices and a fast clock.
- **Public copy:** Every warning and unanswered call seems to pass through June's narrow office.
- **Access:** Public counter 06:00–18:00; radio desk and recording cabinet are staff-only.
- **Clues:** E08 is on June's person, not discoverable merely by entering dispatch.

### Council Rooms (`council-rooms`)

- **Purpose:** Civic decisions, inquiry hearings, budgets, and contested records.
- **Atmosphere:** Coal heat, damp coats, and orderly folders make scarcity look administrative.
- **Public copy:** The council doors open each morning; the cabinets behind them do not.
- **Access:** Public office 09:00–11:00; records require Iris or recorded authorization.
- **Clues:** E06 and E07; neither becomes public just because the office is open.

### Net Loft and Workshop (`net-loft`)

- **Purpose:** Harbor repair hub where practical work and rumor overlap.
- **Atmosphere:** Tarred rope, iron filings, wet canvas, and a bench crowded with useful scraps.
- **Public copy:** Repairs and rumors travel equally quickly through the net loft.
- **Access:** Workshop 06:30–17:30; loft storage belongs to crews. Floorboards and tool boxes require
  permission or a justified search.
- **Clues:** E03 is engine-only until a valid discovery records access beneath the floorboards.

### The Breakwater Inn (`breakwater-inn`)

- **Purpose:** Neutral public meeting place and source of ambient island opinion.
- **Atmosphere:** Steamed windows, strong coffee, and talk that pauses when the door opens.
- **Public copy:** The inn offers soup, coffee, and six incompatible accounts of the storm.
- **Access:** Public 07:00–22:00; kitchen and guest rooms private.
- **Clues:** None; testimony heard here is sourced speech, not objective evidence.

### Widow's Steps (`widows-steps`)

- **Purpose:** Search frontier joining folklore, physical signals, and the rescue route.
- **Atmosphere:** Broken steps descend through spray toward a bell frame that moves without ringing.
- **Public copy:** A tide warning hangs above the old steps; locals still stop to listen.
- **Access:** Fair weather and safe tide only. The sealed tunnel is never casual access.
- **Clues:** E10 and E12 require their weather/tide conditions; E11 remains inside the tunnel.

### Orin's Cottage (`orin-cottage`)

- **Purpose:** Repair shop, oral-history archive, and eventual source of the survey map.
- **Atmosphere:** Lamp chimneys and copied station pages crowd a room kept brightly lit.
- **Public copy:** Orin repairs lamps here and, if asked precisely, old assumptions.
- **Access:** By invitation; desk papers and maps remain private.
- **Clues:** E13 stays behind a newer map until Orin's disclosure gate is met.

## Recurring public routines

Windows apply on Days 1–14 unless a canonical event changes them. Travel occupies the interval
between locations, so a character cannot be selected at either endpoint while traveling.

| Character | Time | Public location and activity | Exception or protected state |
| --- | --- | --- | --- |
| Mara | 05:30–08:30 | Northlight: dawn reading, lens work, search briefing | First-light searches may move her to the north path |
| Mara | 18:30–21:30 | Northlight: evening watch and station log | Inquiry may summon her to council rooms |
| Elias | All day | No public location before rescue | Tunnel/cistern survival is engine-only through Day 11 |
| Tomas | 06:30–09:00 | Net loft: opens workshop and takes requests | Checking the hidden box is engine-only |
| Tomas | 12:00–13:00 | Net loft: meal and parts notes | Recorded field calls replace this window |
| Iris | 09:00–11:00 | Council rooms: open office | Locked-record work is not public presence |
| Iris | 13:30–15:00 | Harbor seawall: inspection | Severe weather moves this indoors |
| June | 06:00–14:00 | Dispatch: radio watch and notices | E08 never appears in public activity copy |
| June | 17:30–18:00 | Breakwater: end-of-shift walk | Cancelled during active search coordination |
| Nell | 07:00–08:00 | Harbor quay: hull, weather, and tide check | Vessel visits require workable low tide |
| Nell | 15:30–16:30 | Dispatch or inn: manifests and coffee | Salvage work takes priority |
| Orin | 11:30–13:00 | Inn: midday soup | Low tide can move him to Widow's Steps |
| Orin | 14:00–17:00 | Cottage: lamp repair and copying | E13 handling remains private until gated |

## Travel and co-location constraints

| Route | Fair-weather time | Constraints |
| --- | ---: | --- |
| Harbor village ↔ Northlight | 40 min | 60 in heavy rain; closed during storm warning absent a canonical emergency |
| Northlight ↔ Widow's Steps | 15 min | 25 when wet; unavailable around high tide or after closure |
| Widow's Steps ↔ old signal hut | 20 min | Low-tide route; Night 0 damage blocks the ordinary return |
| Dispatch ↔ council rooms | 5 min | Public streets |
| Dispatch ↔ net loft | 4 min | Quay may close during unloading or dangerous swell |
| Net loft ↔ Breakwater Inn | 6 min | Public harbor lane |
| Breakwater Inn ↔ Orin's cottage | 12 min | Add five minutes in rain |

Scene planning must choose one location, allow every participant to arrive after their previous
committed scene, and honor access rules. Coincidental meetings require overlapping public routines
or an explicit travel/appointment event—not teleportation.

## Spoiler-safe town-state rules

- Return only `public` routines; omit participant, private, and `engine_only` entries entirely.
- Use `public_activity` when supplied. Never expose private activity as an explanation.
- “Unavailable” is sufficient for Elias before rescue; do not reveal the tunnel or injury.
- Location clue lists are authoring metadata, not visitor payloads. Clues become public only through
  a recorded discovery and presentation artifact.
- A canonical schedule exception supersedes the recurring plan once runtime overrides exist.
