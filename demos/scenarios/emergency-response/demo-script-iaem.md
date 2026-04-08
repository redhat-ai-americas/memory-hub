# IAEM Demo Script — Wildfire Response Scenario

A 10-15 minute presentation outline for delivering the multi-day
wildfire response scenario to an IAEM Annual Conference-style
audience (federal, state, and local emergency managers, IMT
members, cooperator agencies, NGO emergency response leaders, and
emergency response technology vendors).

This is an **outline** with talking points, not a word-for-word
script. The presenter ad-libs the actual language; the script tells
you what to cover, in what order, and which agent fleet milestones
to highlight when.

The presenter is doing live voiceover. Behind the voiceover plays
a recorded session of the agent fleet running on a real cluster,
edited into clips that match the segment structure below. The
presenter plays the role of the entire response team in the
recording — this is a demo necessity, and the script repeatedly
reinforces that in production every agent is operated by a human
practitioner in a real ICS position.

Throughout the script, **footnote markers** like `[^op-period]`
mark the specific MemoryHub feature each statement, segment, or
moment demonstrates. The full feature reference key is at the
bottom of the document, with each footnote linking to the relevant
design doc and GitHub issue.

## Audience and framing

**Who they are**: IAEM attendees are emergency management
decision-makers and practitioners — emergency managers from
federal, state, and local agencies, Incident Management Team
(IMT) members from Type 1 through Type 3 teams, cooperator
agencies (Red Cross, Salvation Army, World Central Kitchen, VOAD
members), defense (DSCA), tribal emergency management, and
emergency response technology vendors. Federal attendees include
FEMA, USFS, BLM, NIFC, and CISA. State and local attendees are
the largest segment.

This audience is **operationally sophisticated** in a way that
sets it apart from the other demo audiences. Emergency managers
have lived through incidents. They have run operational period
handoffs at 04:00 in the morning while exhausted. They have
managed multi-agency coordination with cooperators they had never
worked with before. They have dealt with information failures
that cost time, resources, and sometimes lives. They are also
**deeply skeptical** of vendor pitches that don't understand the
realities of field operations. A demo that uses ICS vocabulary
incorrectly, that proposes autonomous decisions that any IC would
reject, or that oversells what AI can do during an active incident
will lose the room in the first 60 seconds and then become a story
the audience tells each other for the rest of the conference.

The good news: this audience is also **immediately respectful of
anything that genuinely solves the operational period handoff
problem**. The handoff is the universal pain point across every
agency type in the room. A demo that honestly addresses it has
the strongest possible foothold.

**What they need to hear in the first 60 seconds**:

1. This is not another EOC software pitch.[^decision-support-boundary]
2. This is not "AI replaces command staff."[^humans-in-loop]
3. This is not autonomous evacuation orders, autonomous
   resource dispatch, or AI structure triage.[^humans-in-loop]
4. There's a specific incident scenario being shown, with
   real ICS vocabulary, against real frameworks (NIMS, NWCG,
   NFPA).

**What they need to leave with**:

1. The phrase: "MemoryHub holds the context that makes
   incident decisions go well."[^value-prop]
2. A clear understanding of the boundary — MemoryHub sits
   alongside CAD, ROSS, GIS, EOC software, IAP-software, and
   the rest of the existing emergency response stack, doesn't
   compete with any of them.[^decision-support-boundary]
3. The operational period handoff moment as the universally
   recognized pain point that MemoryHub addresses
   directly.[^op-period]
4. The cross-incident fuel behavior recall as the "we've seen
   this before" moment that experienced incident analysts
   will instantly recognize.[^cross-incident]
5. The audit trail and the no-autonomous-decisions framing as
   the credibility check.[^audit][^humans-in-loop]
6. Confidence that this is real software running real agents
   on real infrastructure, with rigorous framing that
   respects the IMT structure and ICS vocabulary.

## Recording strategy

The default delivery is **a recorded session of the harness
running, edited into clips that play behind the live voiceover**
at the conference. Live cluster execution is the backup plan if
conference WiFi is reliable enough to risk it.

This decision shapes every "Harness operator notes" section
below. Each one doubles as a **shot list** for the recording
session — the list of moments that need to be captured and made
visible on screen when that segment plays back.

### How to record the session

1. Capture the harness output as a single long-form recording
   (not multiple takes spliced together). The agent fleet runs
   end to end through the focal period of the incident
   scenario. This is the source material; clips get cut from it
   in post.
2. The recorded session does not need to match the demo's
   13-minute target — it can be 30-60 minutes long if the
   incident plays at realistic pace. Pacing happens at the
   editing stage.
3. Capture every "shot list" item from the per-segment Harness
   operator notes.
4. After the recording session, cut the source material into
   segment-aligned clips. Each clip's runtime should match the
   "Time" column from the time budget table below, with a few
   seconds of padding on either end so the voiceover can lead
   and trail naturally.
5. Voiceover is delivered **live at the conference**, in sync
   with the playback. Do not pre-record the voiceover.

### Visual style for the recording

- Clean structured terminal output (not a UI mockup) so the
  audience sees the real thing — emergency response audiences
  are particularly skeptical of polished demos that hide the
  underlying mechanism
- Role labels prominent and using **real ICS position
  vocabulary** — "IC", "OPS", "PLANS", "RESL", "SITL", "SPRO",
  "LOFR", "PIO", "FBAN", "IMET", "GISS", "UAS PILOT". The
  audience will instantly trust output that uses correct ICS
  vocabulary and instantly distrust output that doesn't.
- `actor_id` and `driver_id` rendered in distinct colors so the
  identity distinction is visible from the back of the
  room[^identity-triple][^driver-id]
- Sensitive-data quarantine notifications must be impossible to
  miss (red, bordered, animated, ideally all
  three)[^data-curation]
- Contradiction markers visually distinct from normal memory
  writes[^contradiction]
- Cross-incident memory references should visually link to the
  prior incident name (e.g., "from the Sage Ridge Fire 2024")
  so the audience understands they're seeing actual
  recall[^cross-incident]
- The operational period handoff moment in Segment 5 is the
  central demo beat — visual styling should make the handoff
  state transfer unmistakable[^op-period]
- Resolution: at minimum 1920x1080, ideally 2560x1440 or
  higher if conference projection supports it
- Terminal font: large enough to read from the back row of a
  conference session room (think 18pt+ at recording
  resolution)

### Emergency-response-specific recording cautions

This is critical for the EM audience and matters more than for
most of the prior scripts:

- **Use real ICS position vocabulary throughout.** "Operations
  Section Chief" not "ops manager." "Resources Unit Leader"
  not "resource tracker." "Incident Meteorologist" not "weather
  person." Get the position titles right or the audience will
  check out.
- **Use obviously fake personal names** for everyone in the
  recording. Cynthia Park, Sergeant Hammond, Bob Martinez,
  Janet Williams, Marcus, Maria Sanchez, James Holloway are
  the synthetic names from the scenario doc. Cross-check that
  none of these match a real well-known wildland fire IC or
  emergency manager before recording.
- **Use obviously fake incident names.** "Meadow Creek Fire,"
  "Sage Ridge Fire," "Pine Hollow Fire" are the synthetic
  names. Cross-check that none of these are real recent
  incidents (especially in California, since the scenario is
  Sierra Nevada).
- **Use obviously fake place names.** "Meadow Creek" the
  community is synthetic. Don't use real California town names.
- **Never use a real after-action report as the source for a
  cross-incident memory** without explicit attribution. The
  Camp Fire wood-deck-failure pattern is publicly documented
  in published after-action reports, so that reference is
  fine — but don't paraphrase or invent details that go
  beyond the public record.
- **Treat structure loss in the demo with operational
  honesty, not drama.** The scenario has three structures
  lost. Mention them as part of the operational picture,
  don't dwell on them, don't make them the emotional climax.
- **Avoid showing any visible imagery of fire, smoke, burned
  structures, or victims.** The recording is structured
  output, not imagery. Imagery introduces emotional weight
  that can make the demo feel exploitative.
- **Never depict jurisdictional disputes or named personal
  conflicts** as part of the recorded output. These are
  shown only as the *quarantined attempt* in the
  sensitive-data moment.

### Live cluster fallback

If WiFi at the conference is observably reliable in the 30
minutes before the talk, live execution becomes Plan A and
recorded clips become Plan B. The decision happens just before
the session starts. **The recorded clips must always be ready
as the default.** Test the playback path on the conference's
actual A/V setup at least 15 minutes before showtime regardless
of which plan is in effect.

The harness used for the live execution path is the same one
that generated the recording — there are no two harnesses to
maintain.

**Critical for the EM audience**: if going live, the demo
cluster must use clearly fake incident data throughout. Any
audience member who recognizes a real incident detail will
assume the demo is showing real operational data and will
either be uncomfortable or call it out publicly. Use synthetic
everything.

## Time budget

Total: 13 minutes (gives you 2-minute cushion against the
15-minute hard cap; can compress to 10 minutes by trimming the
post-event learning capture if running long).

| Segment | Time | What's on screen |
|---|---|---|
| 1. Opening hook and framing | 1:30 | Title slide → incident archetype slide |
| 2. Meet the incident and team | 1:30 | Meadow Creek Fire intro → agent fleet startup |
| 3. Day 2 morning operational period start | 2:00 | Recorded clip: handoff briefing, working memory transfer, day's plan |
| 4. Cross-incident pattern recall and pre-positioning | 3:00 | Recorded clip: weather concern, cross-incident fuel behavior memory, pre-positioning, contradictions |
| 5. The wind shift event (compressed) | 2:00 | Recorded clip: wind shift detection, hypothesis update, evacuation coordination, the killer moment |
| 6. Audit trail and chain of accountability | 1:30 | Recorded clip: audit query showing actor/driver split |
| 7. Operational period handoff and post-event capture | 0:30 | Brief handoff scene, after-event memories |
| 8. Closing pitch | 1:00 | Recap slide → call to action |

Buffer: 30 seconds for transitions and audience reactions.

## Segment 1 — Opening hook and framing (1:30)

### What's on screen

Title slide: **"MemoryHub: the context that makes incident decisions go well."**[^value-prop]

Below the phrase, a small subtitle: *"A demonstration with a
synthetic multi-day wildfire incident."*

### Talking points

**The hook (30 seconds)**: Open with the universally
recognized handoff pain.

> "Every IMT member in this room has had this moment. It's
> 02:00 in the morning. You're the incoming IC on a
> multi-day incident. You're absorbing twelve hours of
> operational state from an outgoing IC who has been awake
> for sixteen hours and is about to fall over. You have the
> IAP document — the formal plan. You have a thirty-minute
> verbal briefing. And you know — you *know* — that half of
> what the outgoing IC understands about this incident is
> not going to make it across that handoff. The story of
> what's been tried, what's working, what's not, the soft
> dynamics with the cooperating agencies, the patterns the
> team has noticed but hasn't written down. Some of it
> transfers. Most of it doesn't. By 06:00 your team is
> working on assumptions that contradict things the previous
> shift already learned the hard way."

**The framing (30 seconds)**: Establish what we're showing
and what we're NOT showing. Address the third rails directly
to clear the air.[^decision-support-boundary][^humans-in-loop]

> "What I'm about to show you is not another EOC software
> pitch. It's not a CAD replacement. It's not a GIS upgrade.
> It's not an IAP generator. And — I want to address this
> up front — it is not autonomous incident management. The
> agent fleet you're about to see does not issue evacuation
> orders. It does not commit crews to assignments. It does
> not triage structures. It does not score people or
> properties by risk. Those decisions belong to the IC, the
> Operations chief, the Structure Protection Specialist,
> and the Sheriff. The agents help the people in those
> positions hold the context they need to make those
> decisions well."
>
> "What you're about to see lives *alongside* everything
> you already use. Your CAD dispatches. Your ROSS orders
> resources. Your GIS visualizes. Your IAP-software builds
> the plan. Your EOC software coordinates across agencies.
> What MemoryHub holds is the working memory of the
> incident — the story the IAP doesn't capture, the
> cross-incident learning that should inform tonight's
> decisions, and the hand-off state that determines whether
> the night shift has the same understanding of the
> incident as the day shift that handed it off."

**The agent disclaimer (30 seconds)**: Get this in early.
Don't let the audience misread the demo as autonomous
operations.[^humans-in-loop]

> "I'll be playing the role of the entire response team
> during this demo. Every agent you see is operated by a
> human practitioner in a real ICS position. The IC agent?
> In production, that's the IC. The Resource Allocation
> agent is the Resources Unit Leader. The Structure Defense
> agent is the Structure Protection Specialist. The Liaison
> agent is the Liaison Officer. The IMET agent is the
> Incident Meteorologist. **Every position you see on
> screen maps to a real ICS position, and every action is
> taken by a human in that position with the agent
> supporting them.** The agents do not make incident
> decisions. They hold the operational and historical
> memory the response team needs to make those decisions
> well."

### Milestones demonstrated

None yet — this is setup. But you've planted four things:

- The phrase[^value-prop]
- The decision-support boundary[^decision-support-boundary]
- The agents-support-humans framing with explicit
  no-autonomous-decisions disclaimer[^humans-in-loop]
- ICS vocabulary credibility (the audience hears "IC,"
  "Resources Unit Leader," "Structure Protection
  Specialist," "Liaison Officer," "Incident Meteorologist"
  and recognizes you know what you're talking about)

### Harness operator notes / shot list

- No harness footage in this segment. Stay on slides.
- Have the recorded clip queued up to begin on the cue at
  the start of Segment 2.

## Segment 2 — Meet the incident and team (1:30)

### What's on screen

Slide: incident archetype. The Meadow Creek Fire basics —
when, where, what, the team composition, the threatened
community, the time pressure event coming that night.

Then transition to the recorded clip showing the agent fleet
registering with MemoryHub.[^identity-triple][^cli-provisioning]

### Talking points

**The incident introduction (45 seconds)**: Make the incident
concrete.

> "The Meadow Creek Fire. A wildland fire in mixed
> timber/chaparral terrain in the western Sierra Nevada
> foothills. Started Day 0 by a downed power line on a
> remote forest road. By Day 1 morning, 250 acres. By Day 1
> evening, 800 acres. The Type 3 IC, a county fire BC, ran
> it on Day 1 and did everything right. By Day 1 evening,
> the incident is escalating. A Type 2 IMT is activated
> and assumes command at 18:00."
>
> "Today, on the screen, you're going to watch the Type 2
> IMT's second operational period. Cynthia Park is the day
> shift IC, taking over from the night shift IC at 06:00.
> The team is preparing for a forecast wind shift event at
> 21:00 tonight that could push the fire toward a small
> mountain community called Meadow Creek — about 280
> permanent residents, mostly older, with several elderly
> and disabled residents who would need transport
> assistance if evacuation becomes necessary."
>
> "The fire is currently 1,100 acres, contained on the west
> and north flanks, active on the south and east. The
> forecast says the wind shift comes at 21:00 with gusts
> to 25 mph from the southwest. The IMET on this incident
> is concerned the local terrain channels wind harder than
> the regional forecast predicts. The team is going to
> spend today preparing for that wind shift. And tonight,
> the wind shift is going to arrive 90 minutes early and
> stronger than forecast — and you're going to watch how
> the team responds."

**Why this scenario (15 seconds)**:

> "Every detail in this demo respects the things that
> matter to IMT members. The ICS positions are real. The
> position vocabulary is correct. The fire behavior
> dynamics are realistic for Sierra foothills chaparral.
> The multi-agency coordination — USFS, CalFire, county,
> Red Cross, Sheriff — reflects how this kind of incident
> actually runs. We're not shortcutting any of the things
> you can't shortcut in real wildland fire."

**Agent fleet startup (30 seconds)**: Cue the recorded clip.
Show the ten agents registering with
MemoryHub.[^identity-triple][^project-scope]

> "On screen now you'll see the response team fleet
> starting up. Each agent is registering with MemoryHub and
> being authenticated. Watch the role names — Satellite
> Imagery, IMET, UAS Pilot, Situation Unit Leader,
> Resources Unit Leader, Operations branch director,
> Structure Protection Specialist, Liaison Officer,
> Incident Commander, Public Information Officer. Ten ICS
> positions. In production, each one is the interface a
> working IMT member uses to chat with the incident's
> shared memory."

### Milestones demonstrated

- **Identity model**[^identity-triple]: ten agents come
  online, each with its own identity. The recorded clip
  shows each agent's `actor_id` as it registers.
- **Project membership**[^project-scope]: all ten agents
  are members of a shared project (`meadow-creek-fire`).
- **Fleet provisioning**[^cli-provisioning]: implicit — the
  fleet was generated from a manifest by the agent
  generation CLI.

### Harness operator notes / shot list

- **Capture**: each agent's `register_session` call landing
  in the harness output, with the role name and `actor_id`
  clearly visible. Hold for 1-2 seconds per agent.
- **Capture**: a confirmation line showing all ten agents
  are members of the `meadow-creek-fire` project.
- The driver_id at this point is set to the demo presenter
  (e.g., `wjackson-iaem-demo`). Make sure it's visible.[^driver-id]

## Segment 3 — Day 2 morning operational period start (2:00)

### What's on screen

Recorded clip showing the operational period handoff at 06:00.
The day shift IC absorbs the night shift IC's working memory.
This is the demo's most universally recognized pain point and
the central value-prop moment.[^op-period]

### Talking points

**The handoff moment (45 seconds)**:[^op-period]

> "06:00. Cynthia Park is taking over as day shift IC. The
> incoming IC briefing is happening at the IC tent. She has
> the IAP document — the formal plan that the Plans section
> built overnight. She has a thirty-minute verbal briefing
> from the night shift IC, who is now sixteen hours into a
> shift. And she has the IC agent — and watch what the IC
> agent surfaces."

**The killer moment 1 — operational period state transfer (1:00)**: This is the demo's central beat. Slow down.[^op-period]

> "Watch the screen. The IC agent is reading a memory the
> night shift IC wrote at 04:30 this morning. Here's what
> it says, in Cynthia's view as she chats with the agent:
>
> 'Night shift handoff notes for Cynthia. Fire activity
> moderated overnight as expected with the inversion.
> Division Z on the east flank is the one to watch — we
> got a partial line in but it's anchored to a road that
> has a switchback the dozer couldn't clear, so there's a
> two-hundred-yard gap we couldn't close. Today's plan in
> the IAP shows a hand crew taking that gap; my
> recommendation is to give that crew the priority air
> support if any spot fires develop in the gap.
>
> The forecast has the wind shift coming at 21:00 — Plans
> built the IAP around that assumption. The IMET is
> concerned the shift could come earlier and stronger than
> the regional forecast says because the local terrain
> channels wind in this drainage. Watch the on-incident
> RAWS station closely after 17:00. If it starts shifting
> before forecast, get evacuation contingencies running
> early.
>
> Strike Team Charlie has been on the line since Day 1
> morning and needs relief by 14:00 today regardless. The
> Red Cross liaison Janet is great but works night shift
> only — her day-shift counterpart is new, named Marcus,
> briefed him at 23:00 last night and he's solid but
> unfamiliar with our incident.'"
>
> "Cynthia reads this in five minutes. And I want you to
> think about what just happened. The IAP gives her the
> formal plan. This memory gives her the *story* of why the
> plan is shaped the way it is, what to watch for, and the
> soft dynamics she needs to manage today. The 200-yard
> dozer gap. The IMET's concern about local terrain. The
> strike team relief deadline. The new Red Cross liaison
> who needs continuity from the previous shift's briefing.
> **None of this fits in the IAP document.** All of it is
> critical for Cynthia to do her job today. And in current
> practice, she would have gotten about half of it through
> a verbal briefing from a tired outgoing IC, and she
> would have been re-deriving the rest of it for the next
> three hours."
>
> "*This* is what we mean by the context that makes incident
> decisions go well. The IAP captured the plan. MemoryHub
> captured the working memory of the incident. Both
> matter."[^value-prop]

**Per-IC preference applied (15 seconds)**:[^tribal-knowledge]

> "And while Cynthia is absorbing the handoff, watch what
> the IC agent does. It's preparing her morning briefing in
> her preferred order — weather first, then fire behavior,
> then resource status, then division reports, then safety,
> then everything else. The agent applied a preference
> memory written about Cynthia from a previous incident
> she ran. She's specifically said she wants weather and
> fire behavior together at the top because if those are
> unusual, everything downstream depends on them. The
> agent is serving her the way she processes information
> best."

### Milestones demonstrated

- **Operational period handoff state
  transfer**[^op-period] (the killer moment for the EM
  audience)
- **Project-scope reads**[^project-scope]
- **Per-IC preference memory**[^tribal-knowledge]
- **Value prop landing**[^value-prop]: the headline phrase
  gets its first strong demonstration here

### Harness operator notes / shot list

- **The handoff memory recall is the most important shot
  in the entire recording for the EM audience.** The IC
  agent's `read_memory` call must be visible, the night
  shift IC's handoff memory must be on screen with the
  full text visible, and the camera needs to hold on it for
  at least 6 seconds — long enough that even the slowest
  reader can absorb the multiple specific items being
  transferred. This is the demo's central beat.
- **Capture**: the IC agent generating Cynthia's morning
  briefing in her preferred order, with the preference
  memory visible alongside.
- The visual styling should make the cross-period reference
  unmistakable — "from night shift IC, 04:30 today" should
  be a clear visual anchor on the memory recall.

## Segment 4 — Cross-incident pattern recall and pre-positioning (3:00)

### What's on screen

The longest segment. Multiple moments compressed into the day's
operational tempo:

- Mid-day pre-positioning for the forecast wind shift
- Cross-incident fuel behavior memory recall
- The contradiction between fire behavior model and field
  observation
- Multi-agency tribal knowledge applied
- A sensitive-data quarantine moment

### Talking points

**Mid-day pre-positioning (30 seconds)**:[^op-period]

> "Skipping ahead to mid-day. The team is in the operational
> tempo of the day. Crews are at their division assignments.
> Resource Allocation is tracking unit positions. Structure
> Defense has begun a pre-emptive assessment of the Meadow
> Creek community structures. Watch what the FBAN — the
> Fire Behavior Analyst — does next."

**The killer moment 2 — cross-incident fuel behavior recall (1:00)**:[^cross-incident]

> "The FBAN is using the Weather agent to model the wind
> shift event expected tonight. And the Weather agent
> surfaces a memory written by an FBAN on a different
> incident the previous summer. Here's what it says:
>
> 'Cross-incident note from the Sage Ridge Fire, August
> 2024. When chamise on south-facing slopes in the 1,800
> to 2,400 foot elevation band burned with single-digit
> relative humidity and afternoon winds in the 20-25 mph
> range, observed rate of spread was 15 to 22 chains per
> hour. Note that the regional forecast that day predicted
> 8 to 12 mph winds; the local RAWS recorded 22 mph
> gusts. The discrepancy between regional forecast and
> local observed wind was the dominant variable in the
> fire's run that afternoon. Lesson for future incidents
> in similar fuel and terrain: trust the on-incident RAWS
> over the regional forecast for spread rate calculations
> on south-facing chamise, especially when humidity is
> below 15%.'"
>
> "The FBAN reads this and adjusts tonight's fire behavior
> projection. The team's contingency planning for the wind
> shift event is now informed by what they learned a year
> ago on a different incident. *And* — listen to this —
> this is the same pattern the night shift IC's handoff
> memory mentioned this morning. Two independent sources,
> a year apart, are telling the team the same thing about
> how this drainage system behaves under wind. The team
> has its picture."

**The contradiction moment (45 seconds)**:[^contradiction]

> "While the FBAN is doing fire behavior modeling, watch
> what happens with a contradiction from the field. The
> FBAN's model at noon projected eight chains per hour
> rate of spread on the east flank for the afternoon. At
> 15:30, the Division Supervisor on the east flank reports
> field observations showing actual spread closer to
> fourteen chains per hour. The Sup's interpretation is
> that the fuel moisture in the chamise is lower than the
> model assumed — there was a hot spell over the weekend
> that wasn't fully captured in the model's inputs."
>
> "The Resources Unit Leader, watching the field reports,
> writes a memory and calls report_contradiction against
> the FBAN's earlier model output. The IC and Operations
> chief read both. The model isn't deleted — it's preserved
> as the team's earlier interpretation, with the field
> observation marked as the operational ground truth for
> the rest of the afternoon. The FBAN investigates the
> discrepancy. The afternoon plan adjusts. Every fire
> behavior analyst in this room knows the dynamic of
> 'model says one thing, field reports another' — and
> knows how politically awkward it can be to push back on
> a model the IMT is treating as authoritative. MemoryHub's
> contradiction detection gives the field observation a
> structural way to surface the discrepancy without it
> being a confrontation."

**Multi-agency tribal knowledge (30 seconds)**:[^tribal-knowledge]

> "And one more piece of this segment. The Liaison Officer
> is preparing for the afternoon multi-agency coordination
> call. The Liaison agent surfaces a memory: 'When working
> with USFS Region 5 strike teams, brief through the strike
> team leader rather than directly to crew members. The
> strike team leader is the chain of command and going
> around them creates friction that slows response. This
> is a consistent pattern across multiple incidents.' The
> Liaison conducts the afternoon coordination through the
> R5 strike team leader. The dynamic that takes new
> Liaison Officers months to learn is available from day
> one."

**The PII quarantine moment (15 seconds)**:[^data-curation]

> "And one quick governance moment from this segment. The
> Evacuation Coordinator agent is preparing contingency
> evacuation plans and starts to write a memory listing
> elderly and disabled residents in the Meadow Creek
> community by name, address, age, and medical condition.
> The curation pipeline catches it. Resident PII at that
> level of detail belongs in the Sheriff's evacuation
> tracking system, where it has appropriate access controls
> and a defined retention policy. It does not belong in
> shared incident memory. The pipeline quarantines and the
> agent rewrites with the operational fact preserved —
> 'special needs requirements exist in the community,
> approximately N residents, follow up through Sheriff's
> system' — and the personal details stripped."

### Milestones demonstrated

- **Cross-incident fuel behavior
  recall**[^cross-incident] (the killer moment 2)
- **Contradiction detection**[^contradiction]: model
  output vs. field observation
- **Multi-agency tribal knowledge**[^tribal-knowledge]
  (the R5 strike team briefing pattern)
- **Sensitive-data quarantine**[^data-curation] catching
  resident PII
- **Audit trail of the quarantined attempt**[^audit]

### Harness operator notes / shot list

- **The cross-incident memory recall is the second most
  important shot in this segment.** The Weather agent's
  `search_memory` call must be visible, the Sage Ridge
  Fire memory text must be on screen with the full lesson
  visible, and the camera needs to hold for at least 5
  seconds.
- **Capture both memories of the model-vs-field
  contradiction**: the FBAN's earlier model output and the
  RESL's contradiction memory. When `report_contradiction`
  is called, the relationship should be visually rendered.
- **Capture**: the R5 strike team tribal knowledge memory
  being read by the Liaison agent.
- **Capture both halves of the resident PII quarantine**:
  the rejected attempt with the named residents visible
  in the rejected text (use obviously fake names),
  visibly marked as quarantined, and the rewritten
  successful version.

## Segment 5 — The wind shift event (compressed) (2:00)

### What's on screen

The wind shift event. Compressed from real time (about 2 hours)
to demo time (2 minutes). Sensor agents detecting the early
wind shift, the IC agent updating the working hypothesis,
evacuation coordination, structure defense pre-positioning,
the killer operational moment.

### Talking points

**The wind shift early arrival (45 seconds)**:[^contradiction][^op-period]

> "19:30. Ninety minutes before the forecast wind shift.
> Watch the Weather agent on screen. The on-incident RAWS
> station MDC-7 just registered a 35 mph gust from the
> southwest. The forecast at 16:00 said winds would shift
> at 21:00 with gusts to 25. The on-incident reading is
> 90 minutes early and 10 mph stronger."
>
> "The Weather agent immediately calls report_contradiction
> against its own earlier reported forecast. And it writes
> a working hypothesis update at project scope: 'Wind shift
> early at 19:30. This is the early/stronger pattern the
> night shift IC warned about in this morning's handoff,
> and the same pattern the Sage Ridge Fire taught us last
> year. Working hypothesis: fire will make a run on the
> east flank within 30 to 60 minutes, threatening the
> eastern edge of the Meadow Creek community. Confidence
> high. Recommend immediate notification to IC for
> evacuation contingency activation.'"
>
> "Cynthia sees this hypothesis update at 19:32. And I want
> you to notice what just happened. The team was prepared
> for this. The night shift IC's handoff memory from this
> morning warned about it. The cross-incident memory from
> the Sage Ridge Fire warned about it. The IMET's local
> microclimate concern flagged it. By the time the wind
> shift actually arrived, the team had already done the
> contingency planning. They had pre-positioned structure
> defense crews. They had pre-coordinated with the
> Sheriff's office on the evacuation contingency. They
> were ready."

**The killer operational moment — coordinated response (1:00)**:[^humans-in-loop][^cross-incident]

> "Watch what happens in the next 30 minutes on screen.
> Cynthia, as the IC, makes the call to recommend
> evacuation. She calls the Sheriff's office at 19:38. The
> Sheriff issues the formal evacuation order at 19:52 —
> **and I want to be very clear here: the evacuation order
> was issued by the Sheriff, not by the agent fleet.** The
> agent fleet supported the decision by surfacing the
> hypothesis, the cross-incident learning, and the
> contingency plans the team had already pre-positioned.
> The Sheriff has the legal authority to issue the order
> and that authority is unambiguous."
>
> "The Operations chief reallocates structure defense
> resources to Meadow Creek. The Liaison Officer
> coordinates with Red Cross — and the Red Cross liaison
> tonight is Marcus, the day-shift counterpart who was
> briefed at 23:00 last night. The Liaison agent surfaces
> the briefing context so Marcus is starting from where
> Janet left off, not from scratch. The PIO drafts the
> public notification using IPAWS. The community
> notification goes out at 20:05. By 21:00 the evacuation
> is in progress."
>
> "And here's the operational payoff that came from the
> morning handoff. The 200-yard dozer gap on the east
> flank that the night shift IC flagged this morning?
> That's where the fire makes its run when the wind
> shifts. The team had positioned resources to address
> exactly that gap. *Because the night shift IC's
> knowledge of the gap survived the operational period
> handoff.* In current practice, that knowledge would
> have been one of the things lost in the verbal briefing.
> Tonight, it was right where it needed to be when the
> wind shifted."

### Milestones demonstrated

- **Self-correcting Weather agent**[^contradiction]:
  forecast vs. real-time data contradiction
- **Cross-incident learning paying off in real
  time**[^cross-incident]: Sage Ridge Fire + handoff memory
  + IMET concern all converging on the right contingency
  planning
- **Operational period handoff state surviving across
  shifts**[^op-period]: the dozer gap knowledge from
  morning handoff applied during evening event
- **Humans in loop**[^humans-in-loop]: explicit framing
  that the Sheriff issued the evacuation order, not the
  agent fleet

### Harness operator notes / shot list

- **Capture the wind shift detection moment**: the Weather
  agent's `report_contradiction` call against its own
  earlier forecast, with both the forecast text and the
  observed reading visible.
- **Capture the hypothesis update memory** with the
  cross-references to the night shift IC's morning warning
  and the Sage Ridge Fire pattern.
- **Capture the coordinated response cascade**: IC notification,
  Sheriff coordination (with explicit text that the
  Sheriff issued the order), Operations reallocation,
  Liaison coordination with Red Cross (with the Marcus
  continuity context visible), PIO notification draft.
- The visual styling should reinforce that the human
  decisions are being made by humans — show the harness
  output recognizing the IC's call, the Sheriff's order,
  and so on as approval-required actions, not
  auto-execution.

## Segment 6 — Audit trail and chain of accountability (1:30)

### What's on screen

The recorded clip shifts to a query mode. Two queries are run,
followed by the chain-of-accountability framing for emergency
management
audiences.[^audit][^driver-id][^role-vs-person]

### Talking points

**The chain-of-accountability hook (45 seconds)**: EM
audiences care about audit for after-action review and for
formal incident investigations. Frame
both.[^audit][^identity-triple][^driver-id]

> "Let me switch from the operational narrative for a
> moment and talk to the IC's, the agency administrators,
> and the after-action review specialists in the room.
> Everything we just walked through — every memory written,
> every memory read, every contradiction reported, every
> quarantine event — is recorded in MemoryHub's audit log.
> Every operation has two identities attached: the *actor*
> (which agent did it) and the *driver* (the human on
> whose behalf it was done)."
>
> "This is your **chain of accountability**. When this
> incident gets a Type 1 close-out review next week — or a
> Serious Accident Investigation a month from now, or a
> formal after-action review for an FLA, or an OIG audit,
> or a state-level review of your agency's response — you
> need to be able to reconstruct who knew what when and
> who made which call. Not 'the IMT made this decision' —
> but 'the day shift IC made this call at 19:38, on the
> basis of these specific memories, having absorbed this
> specific handoff state from the night shift IC at 06:00.'
> MemoryHub gives you that reconstruction by default, not
> as an after-the-fact reconstruction project."

**Query 1 (20 seconds)**:[^role-vs-person][^audit]

> "Watch this. I'm going to ask: 'Show me everything the
> IC role did during the Meadow Creek Fire Day 2
> operational period.' On screen now you're seeing every
> action that role took — across both the night shift IC
> and Cynthia's day shift, because the role spans the
> handoff. Every read, every write, every contradiction
> adjudicated, every memory consulted."

**Query 2 (20 seconds)**:[^driver-id][^audit]

> "Now I'm going to ask a different question: 'Show me
> everything done on behalf of Cynthia Park across the
> entire IMT during this operational period.' Different
> result set. This shows me what Cynthia was driving —
> not just the IC role, but anywhere she touched any other
> agent."

**The point landing (5 seconds)**:

> "Both questions are answerable in seconds. In your
> current after-action process, that's a multi-week
> reconstruction project."

### Milestones demonstrated

- **Audit log with actor/driver
  split**[^audit][^identity-triple]
- **Driver_id queryability**[^driver-id]
- **Role-vs-person identity model**[^role-vs-person]
- **Chain of accountability use case** — the EM-specific
  framing of the compliance hook

### Harness operator notes / shot list

- **Capture both queries running** with their distinct
  result sets visible.
- Result rows must clearly show the `actor_id` and
  `driver_id` columns so the distinction between the two
  queries is visible.[^identity-triple][^driver-id]
- For the recording: queries should produce well-formatted
  output, not raw JSON. A four-column table (timestamp,
  action, actor, driver) is the right shape.

## Segment 7 — Operational period handoff and post-event capture (0:30)

### What's on screen

Brief moment from the operational period handoff at 02:00 on
Day 3, plus the post-event memory capture for future
incidents.[^op-period][^cross-incident]

### Talking points

**Closing the loop (30 seconds)**:[^op-period][^cross-incident]

> "02:00. The night shift command staff arrives. Cynthia
> and her team prepare the handoff briefing. The IC agent
> holds the working memory the day shift carries — the
> three structures lost in Meadow Creek and the team's
> interpretation of why, the Red Cross coordination handoff,
> the Sheriff's six refusal-to-evacuate cases that need
> follow-up, the water utility transmission line status —
> and surfaces it for the night shift. None of this fits in
> the formal IAP update. All of it transfers in the handoff."
>
> "And the next morning, the team writes new memories for
> the rest of this incident and for the next time. The wind
> shift came 90 minutes early in this drainage system, and
> the on-incident RAWS predicted it before the regional
> forecast. This pattern has now been observed on the
> Meadow Creek Fire, the Sage Ridge Fire, and the Pine
> Hollow Fire — three incidents is enough to call it a
> reproducible pattern. The next IMT to work an incident
> in this drainage will inherit this knowledge from the
> first morning briefing. *That* is what institutional
> memory looks like in wildland fire when the agent fleet
> is the surface for it."

### Milestones demonstrated

- **Operational period handoff state transfer at the end of
  the operational period**[^op-period]
- **Explicit cross-incident learning
  capture**[^cross-incident]

### Harness operator notes / shot list

- **Capture**: the handoff memory the day shift writes for
  the night shift, with the specific items visible.
- **Capture**: the post-event lesson memories with the
  cross-incident pattern reference.
- Keep this segment short — closing beat.

## Segment 8 — Closing pitch (1:00)

### What's on screen

Recap slide with the phrase, the boundary, and the bullets
covering what the audience just saw. End slide with contact
info / call to action.

### Talking points

**The phrase, one more time (15 seconds)**:[^value-prop][^decision-support-boundary]

> "MemoryHub holds the context that makes incident
> decisions go well. That phrase is the entire pitch. Your
> CAD dispatches. Your ROSS orders resources. Your GIS
> visualizes. Your IAP-software builds the plan. Your EOC
> software coordinates across agencies. MemoryHub holds
> everything around them — the operational period handoff
> state, the cross-incident learning from prior fires, the
> multi-agency tribal knowledge, and the working memory of
> the incident that doesn't fit in any document."

**What you saw (30 seconds)**: Recap the moments that
mattered most.

> "What you saw in the last twelve minutes:
>
> One. A day shift IC absorbing five pages of working
> operational state from the previous shift in five minutes
> — including the 200-yard dozer gap that turned out to
> matter eleven hours later.[^op-period]
>
> Two. A fire behavior analyst inheriting cross-incident
> learning from a different fire a year ago that informed
> tonight's contingency planning for the same fuel type and
> the same wind shift pattern.[^cross-incident]
>
> Three. A field observation contradicting a model — and
> the contradiction was surfaced structurally, with both
> interpretations preserved.[^contradiction]
>
> Four. A wind shift arriving 90 minutes early — and the
> team was ready, because the morning handoff and the
> cross-incident memory had both warned them.[^op-period][^cross-incident]
>
> Five. An evacuation order issued by the Sheriff, not by
> the agent fleet, with every action attributed to the
> human who took it in the chain of accountability
> audit trail.[^audit][^humans-in-loop]"

**The call to action (15 seconds)**:

> "MemoryHub runs on Red Hat OpenShift AI. It complements
> your existing emergency response stack — CAD, ROSS, GIS,
> IAP-software, EOC software — it doesn't compete with any
> of them.[^decision-support-boundary] We're looking for
> agencies and IMT teams who want to pilot it with their
> own incidents. Come find us at booth [X], or reach out
> at [contact]. Thank you."

### Milestones demonstrated

None new — this is recap.

### Harness operator notes / shot list

- No recorded clip in this segment. Stay on the recap
  slide for the full 30 seconds while the presenter
  delivers the "what you saw" beats. Don't transition too
  fast.

## Demo flow at a glance

For rehearsal purposes, the milestone tie-ins are easier to
scan as a single table:

| Time | Segment | Primary milestone | Secondary milestone | Footnotes |
|---|---|---|---|---|
| 0:00-1:30 | Opening hook & framing | (None — setup) | Phrase, boundary, no autonomous decisions | `[^value-prop]` `[^decision-support-boundary]` `[^humans-in-loop]` |
| 1:30-3:00 | Incident & team intro | Identity model (10 ICS-position agents register) | Project membership | `[^identity-triple]` `[^project-scope]` `[^cli-provisioning]` |
| 3:00-5:00 | Day 2 morning op period start | Operational period handoff state transfer (KILLER MOMENT 1) | Per-IC preference memory | `[^op-period]` `[^tribal-knowledge]` `[^value-prop]` |
| 5:00-8:00 | Cross-incident recall & pre-positioning | Cross-incident fuel behavior recall (KILLER MOMENT 2) | Model-vs-field contradiction, multi-agency tribal knowledge, resident PII quarantine | `[^cross-incident]` `[^contradiction]` `[^tribal-knowledge]` `[^data-curation]` |
| 8:00-10:00 | Wind shift event | Coordinated response with operational period handoff state paying off | Self-correcting Weather agent, humans-in-loop reinforcement | `[^op-period]` `[^cross-incident]` `[^contradiction]` `[^humans-in-loop]` |
| 10:00-11:30 | Audit trail | Driver_id audit query | Role-vs-person + chain of accountability | `[^audit]` `[^driver-id]` `[^role-vs-person]` `[^identity-triple]` |
| 11:30-12:00 | Op period handoff & post-event | Operational period handoff at end of period | Cross-incident learning capture | `[^op-period]` `[^cross-incident]` |
| 12:00-13:00 | Closing pitch | Recap of all milestones | Call to action | (all of the above) |

## Trim plan if running long

If at the 8-minute mark you're noticeably behind, here are the
specific cuts in priority order:

1. **First cut**: trim Segment 7 entirely. Skip the
   end-of-operational-period handoff and post-event capture.
   Save 30 seconds. **Lost milestones**: the second
   demonstration of the operational period handoff. The
   morning handoff demonstration in Segment 3 still lands
   the central concept.
2. **Second cut**: shorten the resident PII quarantine in
   Segment 4 to a single sentence ("the curation pipeline
   also catches things like resident PII trying to get into
   shared memory — we'll talk about that in Q&A"). Save 25
   seconds. **Lost milestones**: `[^data-curation]` is
   reduced to a mention, not a demonstration.
3. **Third cut**: shorten the multi-agency tribal knowledge
   moment (R5 strike team briefing pattern) in Segment 4 to
   a single sentence. Save 20 seconds. **Lost milestones**:
   half of `[^tribal-knowledge]`'s demonstration.
4. **Fourth cut**: drop one of the two audit queries in
   Segment 6 (keep the role-based one, drop the
   human-based one, mention the second briefly in
   narration). Save 30 seconds. **Lost milestones**: half
   of `[^driver-id]`'s demonstration.

Total trimmable: ~1:45. This brings worst-case 13-minute
target down to ~11:15, well inside the 15-minute hard cap.

## Trim plan if running short

If you finish at 11 minutes and want to fill to 13, the easy
extensions are:

1. Spend more time on Segment 3's operational period handoff
   moment. Let the audience really sit with the night shift
   IC's handoff memory and the multiple specific items being
   transferred. This is the moment that lands hardest with
   this audience.
2. Spend more time on Segment 5's wind shift event. Walk
   the audience through the cascade — wind detection,
   hypothesis update, IC notification, Sheriff coordination,
   resource reallocation, evacuation order, public
   notification — slowly enough that the timing impact and
   the human-decision-authority points both land.
3. Add an aside in Segment 6 about how the chain of
   accountability integrates with the formal close-out and
   after-action review processes the audience already runs.
4. Pause for one audience question in the Q&A position
   before closing.

Don't try to add new material on the fly — rehearsed
material delivers better than improvised expansion.

## What you absolutely cannot say

Words and phrases that will lose the room:[^humans-in-loop][^decision-support-boundary]

- "AI predicts structure loss" / "AI predicts evacuation
  needs"
- "Automated evacuation"
- "Autonomous resource dispatch"
- "AI-driven incident management" (vendor cliche)
- "Smart emergency response" (vendor cliche)
- "Replaces command staff" / "reduces the need for IC
  training"
- "Self-managing incident response"
- "AI fire behavior prediction" used as ground truth (the
  audience knows fire behavior models fail)
- "Decision-making AI" (you can say "AI agents that hold the
  team's accumulated experience" — that's not the same
  thing)
- "Prevented loss" (the demo's value is "the team had the
  picture they needed faster," NOT "MemoryHub would have
  saved more structures")
- Confident attribution of any incident decision to the
  agent fleet

If a question in Q&A pushes toward any of these, deflect:

> "Great question. The agents don't make incident decisions
> — your IC, your Operations chief, your Structure
> Protection Specialist, your Sheriff make those decisions.
> What the agents do is make sure those decisions are made
> with the full context the team has built up. Same
> decision authority, better information, and a complete
> chain of accountability for after-action review."

If a question pushes specifically on the structure loss
question:

> "I want to be clear about what MemoryHub does and doesn't
> do here. MemoryHub doesn't predict structure loss and
> wouldn't have prevented those losses. The structures
> were lost because of an early and stronger-than-forecast
> wind shift. What MemoryHub did was give the team a faster
> and better-grounded picture of what was happening, so the
> evacuation went out earlier and more structures were
> defended than would have been otherwise. The
> counterfactual is 'team has the picture faster,' not
> 'no losses ever happen.'"

If a question pushes on the autonomous decision-making
fear:

> "We are very deliberate about this. There are several
> categories of decisions in incident command that should
> never be made autonomously by software — evacuation
> orders, resource commitment, structure triage, public
> notifications. MemoryHub does not make any of those
> decisions. It surfaces the information the IC, the
> Operations chief, the Structure Protection Specialist,
> and the responsible authorities need to make those
> decisions. The audit trail makes every action
> attributable to the specific human who took it. That's
> the structural property, not a marketing claim."

## Open questions for rehearsal

1. **Visual style for the harness output**: same
   recommendation as the prior scripts — clean structured
   terminal output with **real ICS position vocabulary
   throughout**. The audience will instantly trust output
   that uses correct ICS positions and instantly distrust
   output that doesn't.

2. **Synthetic environment details**: the demo references
   the Meadow Creek Fire, Cynthia Park, Sergeant Hammond,
   Bob Martinez, Janet Williams, Marcus, Maria Sanchez,
   James Holloway, the Sage Ridge Fire, the Pine Hollow
   Fire. All synthetic. **Cross-check that none of these
   match real recent California fires or real well-known
   IMT members before recording.**

3. **Booth presence**: the call to action assumes we have a
   physical booth at IAEM. If we don't, the close needs to
   change.

4. **Q&A preparation**: the most likely Q&A questions for
   an EM audience are:
   - "How does this integrate with WebEOC / Veoci / our EOC
     software?"
   - "How does this integrate with our IAP-software?"
   - "What's the data security and access control story?"
   - "How do you prevent the AI from inventing memories or
     hallucinating prior incidents?" (this is a real
     concern — the answer is that retrieval is search and
     recall, not generative)
   - "How does this work for multi-jurisdictional incidents
     where multiple agencies have their own MemoryHub
     deployments?"
   - "What does this cost?"
   - "How long does deployment take?"
   - "Who else is using this?"
   - "Does this integrate with IRWIN?"
   These should have prepared one-line answers.

5. **The "MemoryHub as attack surface" concern**: this will
   come up. EM audiences will recognize that an agent
   memory layer holding incident operational state, prior
   incident learning, and inter-agency tribal knowledge is
   a high-value target. The prepared answer should cover:
   project-scope membership enforcement, audit trail
   integrity, RBAC on read/write, curation pipeline
   preventing PII persistence, and the LlamaStack telemetry
   integration for the audit layer.

6. **The "hallucinated incident" concern**: closely related.
   The answer is that the retrieval layer is search and
   recall, not generative. Any "hallucinated" memory would
   have to have been written by an authenticated actor and
   be in the audit trail.

7. **The structure loss element is operationally honest but
   politically delicate.** The demo script frames this
   carefully — "the team had the picture they needed
   faster" rather than "MemoryHub would have prevented
   losses." Stress-test this framing in rehearsal. If it
   feels off, swap to a scenario where no structures are
   lost (which is also realistic — most successful
   structure defense operations save all structures).

8. **Recording session logistics**: same as the prior
   scripts — block 2-3 hours for the recording session
   including reshoots, plus another 2-3 hours for cut and
   edit.

9. **Live cluster Plan A readiness**: if going live,
   validate end-to-end at least the day before. For EM
   specifically, ensure the demo cluster doesn't visibly
   look like a real operational deployment.

10. **The presenter's wildland fire credibility**: same
    concern as the prior scripts. **Pre-identify a wildland
    fire IC or IMT member as a clinical advisor and have
    them reachable during the demo session.** ICS
    vocabulary mistakes are catastrophic in this audience.

## Feature reference key

Each footnote below maps a moment in the demo to the MemoryHub
feature it demonstrates, the design doc that defines it, and
the GitHub issue (if any) tracking the implementation.

[^value-prop]: **The headline phrase**: "MemoryHub holds
    the context that makes incident decisions go well."
    This is the one-line value prop that anchors the
    emergency response scenario. Same shape as the prior
    four scenarios with one word changed, demonstrating
    platform messaging consistency across five domains.
    *Defined in*:
    `README.md` ("The
    value proposition in one sentence" section).
    *Visible in the demo*: title slide (Segment 1),
    explicit callout in Segment 3 after the killer moment,
    recap slide in Segment 8.

[^decision-support-boundary]: **The decision-support
    boundary positioning**: the explicit framing that
    MemoryHub is *complementary* to the existing
    emergency response stack (CAD, ROSS, GIS,
    IAP-software, EOC software, COP platforms,
    notification systems), not competitive with any of
    them.
    *Defined in*:
    `README.md` ("The
    decision-support boundary" section); reinforced in
    `wildfire-response-meadow-creek.md`
    ("MemoryHub vs. existing emergency response systems"
    section).
    *Visible in the demo*: framing block in Segment 1,
    closing pitch in Segment 8.
    *Not a tracked feature* — this is positioning, not
    code.

[^humans-in-loop]: **Agents-support-humans framing**:
    every agent in the fleet is operated by a human
    practitioner in production, mapping to a real ICS
    position. For emergency response specifically, this
    framing includes explicit rejection of the multiple
    third rails: automated evacuation orders, autonomous
    resource dispatch, AI structure triage, predictive
    harm scoring, and AI-driven incident management. The
    Sheriff issuing the evacuation order — not the agent
    fleet — is the central demonstration of this principle
    in Segment 5.
    *Defined in*: `../README.md` ("AI supports
    humans, it doesn't replace them" section);
    `README.md` ("The
    'humans in production' framing" section); each role
    description in
    `wildfire-response-meadow-creek.md`
    has an "In production" sidebar mapping to a real ICS
    position.
    *Visible in the demo*: agent disclaimer in Segment 1
    (with explicit no-autonomous-decisions disclaimer);
    explicit reinforcement when the Sheriff issues the
    evacuation order in Segment 5; "what you cannot say"
    section is the verbal discipline that keeps this
    framing intact.
    *Not a tracked feature* — this is positioning, not
    code.

[^op-period]: **Operational period handoff state
    transfer**: unique to the emergency response scenario
    among the demos, though parallel concepts exist in
    other domains (clinical shift change, cybersec on-call
    rotation, LEO IC handoff, agriculture family team).
    The operational period concept is structurally
    central to ICS — every 12 hours (or other defined
    period), the entire command staff turns over. The
    formal IAP document captures the plan; MemoryHub
    captures the working memory of what's been tried,
    what's working, what's not, and the soft dynamics
    that shape today's operations.
    *Defined in*:
    `wildfire-response-meadow-creek.md`
    ("Memory touchpoints" — touchpoint 1 is the central
    demonstration). The underlying mechanism (project-scope
    memory + role-as-actor with rotating drivers) is
    documented in `../../../docs/identity-model/data-model.md`.
    *Tracked in*: emerges from project-scope membership
    (#64), schema (#65), tool plumbing (#66). No
    dedicated issue — this is the application-level
    pattern that the underlying features enable.
    *Visible in the demo*: **the killer moment in
    Segment 3** — Cynthia Park absorbing the night shift
    IC's handoff memory at 06:00. Reinforced in Segment 5
    (the dozer gap from morning handoff paying off
    during the wind shift event) and Segment 7
    (the next operational period handoff).

[^cross-incident]: **Cross-incident learning** — the
    "we've seen this before" pattern that recurs across
    every scenario in the platform. In the emergency
    response demo specifically, the central manifestation
    is the Sage Ridge Fire fuel behavior memory — a
    lesson written by an FBAN on a different incident a
    year ago that informs tonight's contingency planning
    on the Meadow Creek Fire.
    *Defined in*:
    `wildfire-response-meadow-creek.md`
    (touchpoints 2, 7).
    *Tracked in*: emerges from project-scope membership
    (#64), schema (#65), tool plumbing (#66). No
    dedicated issue.
    *Visible in the demo*: the killer moment 2 in
    Segment 4 (Sage Ridge Fire fuel behavior recall);
    cross-reference during the wind shift event in
    Segment 5 ("the same pattern observed on Sage Ridge
    Fire and Pine Hollow Fire"); explicit post-event
    learning capture in Segment 7.

[^identity-triple]: **The owner/actor/driver identity
    model**: every memory operation involves three
    distinct identities. `owner_id` (who the memory
    belongs to, determines scope), `actor_id` (which
    agent performed the operation, always derived from
    authenticated identity), `driver_id` (on whose
    behalf, may equal actor_id for autonomous
    operation).
    *Defined in*: `../../../docs/identity-model/data-model.md`
    ("The triple: owner, actor, driver" section).
    *Tracked in*: GitHub issue #65 (schema migration
    adding `actor_id` and `driver_id` columns to
    MemoryNode), #66 (plumbing through tools).
    *Visible in the demo*: agent registration in
    Segment 2, audit trail queries in Segment 6.

[^driver-id]: **Driver_id specifically — the
    on-whose-behalf concept**: identifies the principal
    an agent is acting for. In the emergency response
    scenario, this is used to demonstrate that the IC
    role is driven by different humans across the
    operational period (night shift IC then Cynthia Park),
    with the audit trail capturing each driver
    independently.
    *Defined in*: `../../../docs/identity-model/data-model.md`
    ("Tool API changes" section).
    *Tracked in*: GitHub issues #65, #66.
    *Visible in the demo*: implicit throughout the
    operational period handoff in Segment 3; audit
    query 2 in Segment 6 ("everything done on behalf of
    Cynthia Park").

[^role-vs-person]: **Role-as-actor + person-as-driver
    distinction**: in the emergency response scenario,
    this is the IC operational period handoff pattern.
    The IC role persists across operational periods as a
    stable `actor_id`; the human serving as IC at any
    given moment is a rotating `driver_id`. The role's
    accumulated incident memory survives every shift
    handoff.
    *Defined in*: `../../../docs/identity-model/data-model.md`
    (implicitly, via the actor/driver split). The
    IC operational period handoff is the EM parallel to
    the clinical Charge Nurse handoff, the cybersec
    on-call rotation, the LEO IC shift change, and the
    agriculture family team consultation.
    *Tracked in*: GitHub issues #65, #66.
    *Visible in the demo*: operational period handoff
    moment in Segment 3 is the central demonstration;
    audit query 1 in Segment 6 payoffs the concept by
    showing the IC role's actions spanning both shifts.

[^project-scope]: **Project-scope membership
    enforcement**: agents are members of specific
    projects (in the demo, `meadow-creek-fire`).
    Project-scope memories are readable/writable only
    by members. For multi-agency incidents, this is how
    the team's shared memory stays bounded to the
    incident participants and doesn't bleed across
    unrelated incidents or agencies.
    *Defined in*: `../../../docs/identity-model/authorization.md`
    ("Project membership enforcement (critical path)"
    section).
    *Tracked in*: GitHub issue #64 (the critical-path
    implementation work).
    *Visible in the demo*: agent registration in
    Segment 2; every project-scope memory write/read in
    Segments 3-7 implicitly demonstrates the
    enforcement.

[^tribal-knowledge]: **Practitioner tribal knowledge
    memory category**: practices a team or agency has
    developed that aren't formal SOP but are how the team
    actually works. In the emergency response scenario,
    examples include Cynthia Park's morning briefing
    order preference, the R5 strike team briefing
    pattern, and the night shift IC's interpretive
    notes about the dozer gap and the local microclimate.
    *Defined in*:
    `README.md` ("What
    MemoryHub holds in this scenario");
    `wildfire-response-meadow-creek.md`
    (touchpoints 1, 3, 6).
    *Tracked in*: not a discrete feature — emerges from
    `write_memory` + scope/owner conventions. Category
    positioning, not separate code.
    *Visible in the demo*: per-IC preference applied in
    Segment 3; R5 strike team briefing pattern applied
    in Segment 4.

[^contradiction]: **Contradiction detection** via the
    `report_contradiction` tool. In the emergency
    response scenario, two specific demonstrations:
    (1) the Fire Behavior Analyst's model output
    contradicted by Division Sup field observation, and
    (2) the Weather agent self-correcting when its
    earlier forecast is contradicted by on-incident
    RAWS data during the wind shift event.
    *Defined in*:
    `wildfire-response-meadow-creek.md`
    ("Contradiction moments" section). The
    `report_contradiction` tool already exists in the MCP
    server.
    *Tracked in*: existing tool.
    *Visible in the demo*: model-vs-field contradiction
    in Segment 4; wind shift forecast contradiction in
    Segment 5.

[^data-curation]: **Sensitive-data curation pipeline**:
    when an agent attempts to write a memory containing
    sensitive data (resident PII, source
    identification, inter-agency political dynamics,
    individual-level information that doesn't belong in
    shared incident memory), the curation pipeline
    catches the attempted write and quarantines it
    before persistence. The agent then reformulates the
    memory to preserve operational meaning without the
    sensitive details. The pipeline itself is the same
    code as the healthcare PHI pipeline, the cybersec
    credential pipeline, the LEO third-party
    identification pipeline, and the agriculture
    yield/lease pipeline, but the *patterns* are
    domain-specific. The emergency response patterns
    (resident PII, inter-agency political dynamics,
    source identification) are not yet built — they
    would be a future issue, separate from #68
    (healthcare PHI patterns).
    *Defined in*:
    `wildfire-response-meadow-creek.md`
    ("Sensitive-data moments" section).
    *Tracked in*: pipeline stub via #68 for healthcare;
    emergency response patterns are a future issue (not
    yet filed).
    *Visible in the demo*: resident PII quarantine in
    Segment 4 (Evacuation Coordinator agent attempts to
    write named residents).

[^audit]: **Audit log**: every memory operation is
    captured by `audit.record_event(...)` with both
    `actor_id` and `driver_id` recorded. For the demo,
    the persistence layer is a stub that writes
    structured log lines; future work will route through
    LlamaStack telemetry. For emergency response
    specifically, the audit log running on the
    operation's own infrastructure is the chain of
    accountability for after-action reviews and formal
    incident investigations.
    *Defined in*: `../../../docs/identity-model/authorization.md`
    ("Audit logging — stub now, persistence later"
    section).
    *Tracked in*: GitHub issue #67 (audit logging stub
    interface), #70 (persistent audit log via
    LlamaStack telemetry).
    *Visible in the demo*: quarantine attempts visible
    in audit in Segment 4; audit queries are the
    centerpiece of Segment 6.

[^cli-provisioning]: **Agent generation CLI**: a static
    code-gen tool that takes a fleet manifest YAML and
    produces Kubernetes Secrets, the users ConfigMap,
    and the harness manifest needed to deploy and
    identify the demo's agent fleet. The CLI is the
    source of the ten emergency response agents seen in
    the demo.
    *Defined in*: `../../../docs/identity-model/cli-requirements.md`
    (the full requirements doc for the CLI).
    *Tracked in*: GitHub issue #69 (build agent
    generation CLI for demo fleet provisioning).
    *Visible in the demo*: implicit in the agent fleet
    startup in Segment 2. Worth a one-liner mention if
    there's time and the audience is operationally
    curious ("the fleet you see was provisioned from a
    single YAML manifest — your IMT's specific position
    structure is configured the same way").
