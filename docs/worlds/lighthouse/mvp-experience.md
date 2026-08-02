# The Lighthouse MVP experience specification

Status: implementation ready<br>
Owner: product<br>
Last revised: 2026-08-02

## Product promise

The Lighthouse is a mobile-first, living web-toon mystery. A visitor opens Greyhaven at any time,
quickly understands what changed, reads a short sequence of illustrated story panels, explores the
town through its people and places, and leaves knowing the island will continue without them.

The MVP is primarily a reading experience. It uses server-rendered, shareable pages and semantic
HTML; small progressive enhancements may preserve scroll position, reveal optional context, or
submit a choice without turning the product into a client-side application.

This specification governs presentation and visitor interaction. The
[story bible](story-bible.md) remains the source of truth for plot, knowledge, evidence, release
gates, and content boundaries. If a generated or interactive experience conflicts with it, the
story bible wins.

## Experience principles

1. **Enter the story, not a dashboard.** Lead with a strong current scene and one obvious reading
   action. Explain the simulation through use, not setup copy.
2. **Orient before asking.** Always show the current story day, what has changed, and where the
   visitor is before offering a destination or conversation.
3. **Influence attention, never rewrite truth.** Visitors can choose whom to visit, what to ask,
   and which public curiosity to amplify. They cannot choose canon outcomes or speak as a character.
4. **Make absence rewarding.** Returning after hours or days should feel like receiving the next
   issue, not clearing notifications.
5. **Preserve uncertainty honestly.** Label rumor, belief, observation, and established fact through
   wording and provenance; popularity and repetition never turn a rumor into proof.
6. **One-handed and calm.** The primary path works at 320 CSS pixels, with a single-column reading
   order, generous targets, restrained motion, and no time-critical interaction.

## Core content model and hierarchy

Every visitor-facing page uses the following hierarchy:

1. **World context:** Lighthouse title, current story day, and simulation status.
2. **Primary moment:** the current scene, conversation turn, recap, or selected archive episode.
3. **Orientation:** time, place, participants, and whether information is rumor or established.
4. **Primary action:** continue, ask, visit, or read the next episode; only one emphasized action.
5. **Supporting context:** character cards, location notes, provenance, and prior episodes.
6. **Global navigation:** Story, Town, and Archive. "Story" returns to the current reading position.

Persistent chrome must not reveal protected information. The current day is public; clue counts,
secret progress bars, and completion percentages are not.

## Visitor model

The MVP has an anonymous, browser-local visitor identity. It stores only:

- first-visit completion;
- last-seen canonical event or episode;
- last reading position;
- visited locations and conversations;
- questions submitted and public-curiosity choices made;
- accessibility preferences that the browser does not already provide.

Losing local state may reset personal read markers but must not alter the world. Accounts, cross-
device sync, profiles, inventories, achievements, streaks, and visitor-to-visitor interaction are
launch exclusions.

## End-to-end visitor journeys

### 1. First visit

**Intent:** understand the premise and reach the opening scene within one action.

1. `/lighthouse` opens on a full-width opening panel: Northlight dark in the storm, the product
   title, and the premise, "The light went out. Elias Rook is missing. Greyhaven is already choosing
   what to believe."
2. A compact context line says "Day 1 · the story continues while you are away." It avoids a
   product tour and does not expose the objective solution.
3. The primary action, **Enter Greyhaven**, starts Episode 1. A secondary text link, **How this
   works**, opens an inline three-point explanation: the town continues, people know different
   things, and visitor choices guide attention rather than change established events.
4. Episode 1 presents 3–7 vertically stacked panels. Each panel pairs an illustration with concise
   narration or dialogue in document order. The final panel offers **Continue to town**.
5. The town page highlights one recommended next stop and at most two alternatives. Recommendation
   copy explains narrative relevance without claiming that there is a correct route.

**Completion:** Episode 1 has been viewed and the visitor can name the incident, the missing person,
and the fact that people disagree.

### 2. Returning visit

**Intent:** understand what happened during absence in under 30 seconds, then resume.

1. A returning visitor lands on **Since you were away**, provided at least one canonical episode was
   published after their last-seen marker. Otherwise they resume at their saved reading position.
2. The page shows elapsed real time, current story day, number of new episodes, and a spoiler-safe
   recap of at most three developments. Each development links to its originating episode.
3. **Read what changed** opens the earliest unread episode. **Jump to now** marks the intervening
   episodes as seen only after confirmation and opens the current episode; skipped content remains
   available in the archive.
4. Previously visited characters may have a "new since your last visit" marker. The marker describes
   availability, not urgency, and is removed after opening that content.
5. If no story content is new, the visitor sees the current panel and a calm timestamp: "Greyhaven is
   quiet for now." The primary action returns to Town.

**Completion:** the last-seen marker advances only when content is actually viewed or an explicit
skip is confirmed.

### 3. Town exploration

**Intent:** choose a place or person based on story interest, without treating the town as a game map.

1. `/lighthouse/town` lists open locations in a vertical, illustrated route: Northlight, Harbor,
   Council Rooms, Dispatch Office, Inn, and any later unlocked public location.
2. Each location card includes name, walking context, present characters, a one-line current hook,
   and state: **Open**, **Quiet**, or **Unavailable until later**. It never names undiscovered evidence.
3. Selecting a location opens its page with a scene-setting panel, visible characters, public facts,
   and available actions. The primary action is either **Speak with [character]** or **Observe**.
4. Observing may reveal an authored public detail or schedule a future conversational angle. It may
   not search private spaces, acquire evidence, or cause a canon event unless a story beat explicitly
   authorizes that outcome.
5. **Back to town** preserves the visitor's list position. Browser Back must behave equivalently.

**Completion:** the visitor opens a location and views one scene or character conversation.

### 4. Character conversation

**Intent:** question a character while preserving that character's knowledge, motives, and voice.

1. A conversation opens with the character portrait, name, role, location, story day, and a short
   reminder: "They may be mistaken, evasive, or honest about only part of what they know."
2. The visitor chooses one of 2–4 authored question intents, such as **Ask about Elias**, **Ask about
   the official log**, or **Why do you distrust Mara?** Free-text prompting is excluded from launch.
3. Submission is explicit. The selected intent becomes disabled and the response appears as the next
   exchange after server confirmation. A visitor may choose another available intent or leave.
4. The answer must be generated from the character's current memory and belief state, honor story-
   bible release gates, and be stored as a canonical conversation record. A character may lie or
   decline; the interface never stamps an answer "true" or "false."
5. A small **Why am I seeing this?** disclosure identifies the observed or rumored source when that
   provenance is itself visitor-visible. It must not expose hidden reasoning or protected facts.
6. After the daily conversation allowance is exhausted, the character remains readable and says
   when another exchange may become available. No payment, countdown pressure, or retry loophole.

**Completion:** a response is committed once and can be reopened from the current episode or the
character's public conversation history. Refreshing must not create a second response.

### 5. Daily recap

**Intent:** close a story day with a trustworthy, readable account that preserves open questions.

1. When a day closes, `/lighthouse/day/{day}` leads with a 3–5 panel recap of public events in
   chronological order.
2. **What the island knows** lists established public observations with sources. **What people are
   saying** lists up to three active rumors, naming who or where the visitor heard them when public.
3. **Still unresolved** poses questions without ranking suspects or implying that every listed rumor
   is equally credible.
4. **Your path today** lists visited places and conversations. It is private presentation state, not
   a claim that the visitor caused the events.
5. The closing action is **Return when the story continues** when no later episode exists, otherwise
   **Read the next episode**.

**Completion:** the recap is saved as the day's archive entry and remains stable even if later facts
disprove its contemporary rumors. Later annotations may link to corrections; history is not rewritten.

### 6. Episode archive

**Intent:** browse the published story in order, recover skipped content, and share a stable episode.

1. `/lighthouse/archive` groups episodes by story day, newest day first, while listing episodes in
   chronological order within each day.
2. Each entry includes title, day/time, location, a spoiler-safe dek, reading status, and approximate
   reading time. Unpublished episodes do not appear as locked placeholders.
3. Filters are limited to **All**, **Unread**, and character. Results remain server-rendered and
   addressable by URL.
4. Episode pages have stable canonical URLs, Previous/Next links, and a **Back to now** action. Shared
   URLs include enough premise context for a new visitor without forcing onboarding.
5. Archive search, downloads, bookmarks, and user annotations are excluded from launch.

**Completion:** the visitor can locate and read any published episode without changing simulation
state beyond their personal read marker.

## Influence contract

### Visitors can influence

- the order in which they explore already available content;
- which available character they speak with and which authored question intent they submit;
- which of a small set of public questions receives attention in a future scheduled beat;
- their own read markers, skipped-content decision, and accessibility preferences;
- aggregate, non-binding curiosity signals used by the scheduler to choose emphasis or point of view.

### Visitors cannot influence

- objective canon, the Night 0 cause, Elias's survival, evidence identity or location, or the Day 14
  resolution;
- what a character knew before an observed or sourced update;
- information-release gates, required evidence chains, content boundaries, geography, weather, or
  historical technology;
- whether a scheduled canonical event occurs, who is guilty, or the consequences already authored;
- another visitor's experience, any popularity-based vote result, or the truth value of a rumor.

Aggregate curiosity may select among pre-approved perspectives or accelerate an eligible optional
conversation. It may not unlock a protected secret early. If no safe branch exists, the signal is
recorded but has no story effect. The UI describes influence as "what Greyhaven looks toward next,"
never "choose what happens."

## Mobile-first wireframes

Wireframes show information order, not final visual styling. Desktop keeps the reading column at a
comfortable width and may place supporting context beside it; the DOM and focus order remain the
mobile order.

### Current story / returning visit

```text
┌──────────────────────────────┐
│ THE LIGHTHOUSE       Day 4   │
│ Story    Town    Archive     │
├──────────────────────────────┤
│ SINCE YOU WERE AWAY          │
│ 2 new episodes · 18 hours    │
│                              │
│ [illustrated recap panel]    │
│ Tomas closed the net loft.   │
│ Episode 7 · Harbor           │
│                              │
│ [illustrated recap panel]    │
│ June denied hearing a call.  │
│ Episode 8 · Dispatch         │
│                              │
│ [ Read what changed ]        │
│       Jump to now            │
└──────────────────────────────┘
```

### Town and location

```text
┌──────────────────────────────┐
│ ← Story       GREYHAVEN      │
│ Day 4 · Afternoon            │
├──────────────────────────────┤
│ Where will you look?         │
│                              │
│ ┌──────────────────────────┐ │
│ │ [Northlight image]       │ │
│ │ NORTHLIGHT · OPEN        │ │
│ │ Mara is reviewing logs.  │ │
│ │ 40 min from Harbor   ›   │ │
│ └──────────────────────────┘ │
│ ┌──────────────────────────┐ │
│ │ DISPATCH · QUIET         │ │
│ │ June has stepped away.   │ │
│ └──────────────────────────┘ │
│                              │
│ Story    Town    Archive     │
└──────────────────────────────┘
```

### Character conversation

```text
┌──────────────────────────────┐
│ ← Northlight      Day 4      │
├──────────────────────────────┤
│ [portrait] MARA VENN         │
│ Keeper · Service room        │
│ She may be mistaken or evade.│
│                              │
│ “The official log is all I   │
│  can stand behind.”          │
│                              │
│ What do you ask?             │
│ [ Ask about Elias          ] │
│ [ Ask about the log        ] │
│ [ Why was the light dark?  ] │
│                              │
│ Why am I seeing this?        │
└──────────────────────────────┘
```

### Daily recap / archive

```text
┌──────────────────────────────┐
│ THE LIGHTHOUSE       Day 4   │
├──────────────────────────────┤
│ DAY FOUR: CLOSED DOORS       │
│ [recap panels, vertical]     │
│                              │
│ WHAT THE ISLAND KNOWS        │
│ • Scoring marks the cabinet. │
│   Observed at Northlight     │
│                              │
│ WHAT PEOPLE ARE SAYING       │
│ • “Elias fled.” — Harbor     │
│                              │
│ STILL UNRESOLVED             │
│ Who changed the record?      │
│                              │
│ [ Read the next episode ]    │
│ Story    Town    Archive     │
└──────────────────────────────┘
```

## Shared system states

State messages keep the page shell, page title, and recovery navigation visible. They never replace
the whole viewport with a spinner.

| Context | Empty | Loading / pending | Error and recovery |
| --- | --- | --- | --- |
| Current story | "Greyhaven is quiet for now" with last published timestamp and **Explore town** | Existing content stays visible; new navigation uses normal document loading | Show last committed episode, "The latest scene could not be reached," **Try again**, and Archive |
| Since you were away | No new episodes resumes saved position; missing marker offers **Start from Episode 1** or **Go to now** | Skeletons match recap headings and reserve image space; text alternative says "Loading recap" | Do not advance last-seen marker; offer **Read archive** and **Try again** |
| Town | "No one is available here yet" plus open locations | Location card retains name and dimensions; no pulsing map | Preserve last known availability, mark it "May be out of date," and offer refresh |
| Conversation | "[Character] has nothing more to add today" with conversation history | After submit, lock only the selected form, announce "Asking…", and keep the exchange visible | Keep the chosen question, announce failure, allow a safe retry with the same idempotency key; never display a fabricated reply |
| Daily recap | Before day close: "Day {n} is still unfolding" and **Back to story** | Render headings and fixed-ratio panel placeholders | Link to the day's episodes; label recap unavailable rather than inferring one |
| Archive | "No episodes published yet" with premise and **Enter Greyhaven** | Render day headings and stable entry placeholders | Keep any cached entries, say results may be incomplete, and offer retry |
| Illustration | N/A | Reserve aspect ratio to prevent layout shift | Show meaningful alt text and styled text panel; story comprehension must not depend on image recovery |

Mutating requests use a client-generated idempotency key. A timeout never invites a second distinct
conversation request until the server confirms the first request's status.

## Accessibility expectations

The MVP targets WCAG 2.2 AA for all core journeys.

- Use landmarks, a single descriptive `h1`, sequential headings, lists for episode collections, and
  native buttons/links/forms. Reading and focus order follow the visual story order.
- Provide a skip link and visible focus indicators. All actions work by keyboard; no drag, swipe,
  hover, long-press, or map position is required.
- Interactive targets are at least 44 by 44 CSS pixels with adequate spacing. The experience works
  at 320 CSS pixels and at 200% browser zoom without two-dimensional scrolling.
- Text and meaningful controls meet 4.5:1 contrast (3:1 for large text and graphical controls).
  Rumor, fact, read status, location status, and error status are never distinguished by color alone.
- Every story illustration has concise alt text that conveys its narrative contribution. Decorative
  atmosphere uses empty alt text. Dialogue and narration always exist as selectable HTML text, not
  baked into images.
- Captions and transcripts accompany any future audio or motion; audio does not autoplay. The MVP
  does not require audio for any information or action.
- Respect `prefers-reduced-motion`; avoid parallax and flashing. Enhancements must not move focus or
  scroll position unexpectedly, and dynamic status messages use restrained live regions.
- Form errors identify the field, explain recovery in text, and preserve selections. Loading and
  completion announcements do not repeatedly interrupt screen-reader reading.
- Dates and relative times include machine-readable absolute values. Reading-time estimates are
  optional guidance, never a timer.

Accessibility acceptance uses keyboard-only review, VoiceOver/Safari and NVDA/Firefox smoke tests,
automated checks, 200% zoom, reduced motion, and forced-colors/high-contrast review across all six
core journeys and every shared state.

## Measurement and MVP success signals

Analytics use privacy-preserving first-party events and anonymous session identifiers. No dialogue
content, free text, hidden character state, or third-party ad tracking is collected.

| Signal | Definition | MVP success threshold after first 30 days |
| --- | --- | --- |
| Opening activation | New visitors who start Episode 1 / eligible new visitors | At least 65% |
| Opening completion | Episode 1 starters who reach Town / Episode 1 starters | At least 70% |
| Meaningful exploration | Activated visitors who open a location and complete one conversation in the same or a later session | At least 45% |
| Return rate | Activated visitors who return on a different calendar day within 7 days | At least 25% |
| Catch-up success | Returning visitors with new content who open an unread episode or explicitly jump to now | At least 70% |
| Episode completion | Episode starts reaching the final panel / episode starts, excluding immediate reloads | At least 75% |
| Archive recovery | Visitors with unread episodes who use Archive and complete one previously unread episode | At least 20% |
| Choice integrity | Accepted conversation submissions committed exactly once | At least 99.5% |
| Reading reliability | Successful core page responses, excluding planned maintenance | At least 99.5% |
| Accessible task success | Moderated assistive-technology participants completing first visit, return catch-up, and conversation without help | At least 90% |

Guardrails are as important as engagement: fewer than 5% of surveyed activated visitors should
believe their choice can change established truth, and no protected-secret release before its story-
bible gate is acceptable. Product review occurs weekly during launch; thresholds guide iteration
and are not used to manipulate story canon.

## Explicit launch exclusions

- accounts, authentication, profiles, cross-device state, email/push notifications, and social login;
- visitor-written dialogue, open-ended chat, prompt entry, uploads, comments, direct messages, and
  visitor-to-visitor features;
- branching canon, majority voting on outcomes, rewind/reset of the simulation, save slots, and
  personalized generated plot lines;
- subscriptions, purchases, advertising, virtual currency, streaks, leaderboards, achievements, and
  engagement countdowns;
- a draggable geographic map, real-time presence, live multiplayer, WebSockets, native apps, offline
  mode, a rich SPA, or a public client API;
- archive full-text search, downloads, bookmarks, annotations, and localization beyond preparing the
  markup and layouts for future translation;
- audio drama, animated panels, video, haptics, AR/VR, and interactions whose meaning depends on
  motion, sound, or precise pointing;
- user-generated worlds, alternate mysteries, and any world content beyond the authored Lighthouse
  season.

## Launch acceptance checklist

- [ ] First visit, returning visit, town, conversation, recap, and archive meet the journey completion
  definitions at 320 px, desktop width, keyboard-only, and 200% zoom.
- [ ] All page, empty, pending, illustration-failure, request-failure, and retry states have been
  exercised with JavaScript enabled and disabled where the action can degrade gracefully.
- [ ] Conversation retries commit at most one response and never show uncommitted generated content.
- [ ] Read and skip markers advance only after the specified visitor action.
- [ ] Rumor, belief, observation, and established fact are worded and sourced distinctly.
- [ ] A story-bible continuity check confirms that routes, summaries, conversation intents, and
  aggregate-curiosity effects cannot bypass knowledge or information-release gates.
- [ ] Analytics events support every success-signal denominator and numerator without collecting
  dialogue text or protected state.
- [ ] Core pages have stable, meaningful URLs and remain readable as semantic documents without
  client-side JavaScript.
