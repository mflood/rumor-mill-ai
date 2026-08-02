# The Lighthouse: fourteen-day season beat graph

Status: launch canon<br>
Canon owner: authored world<br>
Last revised: 2026-08-02

This graph guides the season toward Elias's rescue and a complete public account without fixing the
route through every conversation. A beat is an outcome the simulation must record, not a mandated
scene script. The [story bible](story-bible.md) controls truth and release gates; the
[locations and routines](locations-and-routines.md) control plausible access and co-location.

## Scheduling contract

- A beat becomes **eligible** only inside its window and after every prerequisite is recorded.
- Its **deadline** is the final normal scheduling day. At the deadline, use the named fallback or
  accelerate the beat into the next plausible simulation scene. Pausing the season clock is reserved
  for unavailable infrastructure or moderation intervention, never for waiting on a visitor.
- **Protected facts** may shape evasion, stakes, and inference but cannot appear as established
  objective truth in that beat. Story-bible release gates override every variant.
- A visitor may choose whom to trust, prompt an investigation, share a discovered fact, or change a
  relationship. The autonomous route beside every beat guarantees that departure or inactivity by
  any one visitor cannot block the season.
- A fallback preserves the parent beat's evidence-chain function. It may reveal less personal detail,
  but it may not delete, fabricate, or release evidence early.

## Graph

| ID | Role | Window / deadline | Outcome and prerequisites | Fallback / missed-beat recovery | Protected facts |
| --- | --- | --- | --- | --- | --- |
| `dark-headland` | Inciting incident | Day 1 / D1 | Publicly establish the blackout, grounding, missing Elias, official log wording, and inquiry. Entry beat. | Accelerate into the first town recap before any investigation scene. | Every cause; Elias's fate; all concealments. |
| `accounts-diverge` | Escalation | D1–2 / D2 | Mara, June, and Nell give incompatible sourced accounts. Requires `dark-headland`. | The inquiry clerk posts contradictions gathered independently from routine interviews. | E08's existence; Nell's changed course; Mara's omission. |
| `water-and-cutout` | Escalation | D2–4 / D3 | E01 and E02 establish water ingress, arcing, and deliberate manual isolation without assigning motive. Requires `accounts-diverge`. | Orin and Tomas inspect the cabinet in a recorded maintenance scene on D4. | Elias pulled the cutout to prevent fire; the removed bypass; Iris's order. |
| `north-path-trace` | Escalation | D2–5 / D4 | E10 proves Elias left by the north path injured; search belief changes from “swept away” to an uncertain route. Requires `dark-headland`. | Searchers find the glove during an autonomous safe-tide sweep. | Tunnel entry and survival; the meaning of “old signal.” |
| `edited-records` | Reversal | D4–6 / D6 | E04/E05 show the loose sheet was replaced and the bound log is incomplete. Requires `water-and-cutout`. | Oblique morning light exposes indentations during Mara's routine archive review. | Who replaced the sheet; Mara's intent; Tomas's hidden lead. |
| `elias-safe-choice` | Reveal | D6–8 / D7 | Evidence or a credible confession establishes that Elias pulled the cutout to stop a fire. Requires `edited-records`. | Mara states the safety sequence in the formal inquiry; relationship damage determines tone, not disclosure. | Tomas removed the bypass; Iris's pressure; Elias alive. |
| `hidden-bypass` | Reveal | D7–9 / D8 | E03 plus E01/E02 establishes Tomas's unauthorized bypass and later removal. Requires `water-and-cutout`; normally follows `edited-records`. | Tomas retrieves the lead to prevent an unsafe accusation against Elias, witnessed and recorded. | Iris's order and fund diversion; Mara's assent; Elias alive. |
| `institutional-pressure` | Reversal | D8–10 / D9 | E06/E07 or Iris's confession establishes diverted funds and her order to continue operation. Requires `accounts-diverge`. | The council must publish requisitions before the next supply allocation; Iris supplies the call entry. | Iris knew the bypass design; she did not. Elias alive. |
| `broken-transmission` | Reveal | D8–10 / D10 | E08 establishes “cut … Elias … old signal” and turns the search toward the signal route. Requires `north-path-trace`. | June releases the cylinder when an autonomous search briefing identifies the old signal hut. | A complete message; Mara ordered Elias out; Elias's exact location. |
| `bell-below` | Reversal | D10–11 / D11 | At least two of E11, E12, E13 support that Elias may be alive beneath Widow's Steps. Requires `broken-transmission`. | Orin supplies E13 and demonstrates E12 at safe low tide; if weather closes the Steps, pause the clock until the next safe tide. | Elias alive as fact; the cistern cap's exact condition. |
| `cistern-rescue` | Climax | D12–13 / D12 | E14: responders locate the cistern and rescue Elias alive. Requires `bell-below`. | An NPC rescue party combines the recorded map, tide, and cable evidence; visitors may join but are never sole rescuers. | None about Elias's fate after physical contact; Tomas's later act remains outside Elias's testimony. |
| `shared-account` | Resolution | D13–14 / D14 | Reconcile all five evidence chains and publicly distinguish safety action, dangerous repair, institutional pressure, later concealments, and Nell's shortcut. Requires `cistern-rescue`, `hidden-bypass`, and `institutional-pressure`. | A D14 public inquiry assembles recorded discoveries and testimony; absent confessions affect relationships and consequences, not objective findings. | No core physical cause or concealment may remain objectively ambiguous. |

## Optional variants and visitor influence

These variants inherit the parent beat's window, prerequisites, deadline, disclosures, and protected
facts. The scheduler chooses only a variant whose condition is already recorded.

| Parent beat | Variant | Condition | Permitted visitor effect | Autonomous equivalent |
| --- | --- | --- | --- | --- |
| `accounts-diverge` | `visitor-takes-a-side` | A visitor questions one witness before the inquiry clerk does. | Shifts trust toward or away from that witness and changes which contradiction surfaces first. | Clerk interviews all three witnesses. |
| `edited-records` | `mara-opens-desk` | Mara trusts a participant enough to grant archive access. | Discovery strengthens Mara's relationship while still recording E04/E05 objectively. | Mara's own routine review exposes the indentation and she logs it. |
| `hidden-bypass` | `authorized-search` | A participant earns lawful access to the net-loft floorboards. | Determines who confronts Tomas and whether he confesses before discovery. | Tomas retrieves the lead in front of a workshop witness. |
| `broken-transmission` | `june-chooses-trust` | A relationship turn makes disclosure safer than control. | Visitor may receive E08 first and choose when to share it that day. | Search briefing makes “old signal” operationally relevant, so June releases it. |
| `bell-below` | `visitor-connects-the-map` | Visitor has learned two of E11–E13. | Visitor can articulate the cistern hypothesis and gain trust. | Orin and the search party make the same inference from recorded evidence. |
| `shared-account` | `restorative-hearing` | Prior choices preserved enough cross-cast trust. | Alters apologies, alliances, and advocated consequences. | Formal inquiry reaches the same factual account with colder relationships. |

## Recovery invariants

1. **Pause:** stop season time only when a safe-tide scene, required service, or moderated interaction
   cannot run. Continue background routines without advancing the story day; resume at the same beat.
2. **Accelerate:** after a deadline, select the next plausible routine involving an authorized NPC
   and stage the required outcome before optional scenes. Do not compress travel or release gates.
3. **Fallback:** record why the preferred opportunity was missed, run the authored fallback, then
   re-evaluate downstream eligibility. A fallback satisfies the same prerequisite edge as its parent.
4. **Catch-up:** when multiple overdue beats are independent, order them by protected-fact gate and
   causal clarity, not visitor arrival. `north-path-trace` may catch up beside `water-and-cutout`, but
   `elias-safe-choice` cannot precede `edited-records`.
5. **End guarantee:** by the end of D11, the scheduler must have `bell-below`; by D12 it must attempt
   `cistern-rescue`; by D14 it must record `shared-account`. Relationship outcomes, blame, and future
   policy remain generative, while Elias's survival and the objective solution do not.
