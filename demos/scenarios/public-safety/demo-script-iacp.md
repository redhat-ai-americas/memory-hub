# IACP Demo Script — Multi-Sensor Fugitive Search Scenario

A 10-15 minute presentation outline for delivering the multi-sensor
fugitive search scenario to an IACP-style audience (chiefs of police,
sheriffs, federal agency leadership, corporate security executives,
public safety vendors, and international policing leaders).

This is an **outline** with talking points, not a word-for-word script.
The presenter ad-libs the actual language; the script tells you what
to cover, in what order, and which agent fleet milestones to highlight
when.

The presenter is doing live voiceover. Behind the voiceover plays a
recorded session of the agent fleet running on a real cluster, edited
into clips that match the segment structure below. The presenter
plays the role of the entire response team in the recording — this
is a demo necessity, and the script repeatedly reinforces that in
production every agent is operated by a working practitioner.

Throughout the script, **footnote markers** like `[^cross-incident]`
mark the specific MemoryHub feature each statement, segment, or
moment demonstrates. The full feature reference key is at the bottom
of the document, with each footnote linking to the relevant design
doc and GitHub issue.

## Audience and framing

**Who they are**: IACP attendees are public safety
decision-makers and influencers. Police chiefs and sheriffs are the
buyers. Crime analysts, incident commanders, real-time crime center
operators, and tactical commanders are the users. Federal agency
leadership (FBI, US Marshals, ATF, DEA) is in the room. Vendors and
integrators are the partners. International policing leaders attend
in significant numbers.

This audience is operationally sophisticated. They have CAD. They
have RMS. They have GIS. Some have real-time crime centers. Some
have license plate reader networks. They've spent millions on it.
They are also **politically careful** — they have to defend their
tech investments to city councils, mayors, the public, the media,
and (often) federal oversight. Any pitch that sounds like
surveillance escalation, bias amplification, or "AI replaces
officers" will not just lose the room — it will become a story
they have to defend in a meeting next week.

The good news: this audience has **real, unmet needs around
multi-source coordination**, search efficiency, and institutional
memory across staff turnover. Every chief in the room has lost
operational continuity to a shift change. Every IC has had units
re-tasked to an area they already cleared. Every analyst has had
the experience of "this reminds me of something but I can't find
it in time." MemoryHub addresses real pain. The pitch just has to
not trip over the political third rails on the way there.

**What they need to hear in the first 60 seconds**:

1. This is not another CAD or RMS pitch.[^decision-support-boundary]
2. This is not predictive policing.[^humans-in-loop]
3. This is not autonomous threat assessment, facial recognition,
   or automated suspect identification.[^humans-in-loop]
4. There's a specific operational scenario being shown (not a
   generic abstraction).

**What they need to leave with**:

1. The phrase: "MemoryHub holds the context that makes tactical
   decisions go well."[^value-prop]
2. A clear understanding of the boundary — MemoryHub sits
   alongside CAD, RMS, GIS, and the rest of the existing LEO
   stack, doesn't compete with any of them.[^decision-support-boundary]
3. The negative-findings discipline as the most operationally
   recognizable demonstration of value.[^cross-incident]
4. The cross-incident pattern recognition moment as the "we've
   seen this before" demonstration that experienced
   investigators will instantly recognize.[^cross-incident]
5. The audit trail moment as the **chain of accountability**
   compliance hook — every action attributed to the human who
   took it.[^audit][^driver-id]
6. Confidence that this is real software with rigorous framing,
   not vaporware and not vendor hype.

## Recording strategy

The default delivery is **a recorded session of the harness running,
edited into clips that play behind the live voiceover** at the
conference. Live cluster execution is the backup plan if conference
WiFi is reliable enough to risk it.

This decision shapes every "Harness operator notes" section below.
Each one doubles as a **shot list** for the recording session — the
list of moments that need to be captured and made visible on screen
when that segment plays back.

### How to record the session

1. Capture the harness output as a single long-form recording (not
   multiple takes spliced together). The agent fleet runs end to
   end through the full search scenario in real time. This is the
   source material; clips get cut from it in post.
2. The recorded session does not need to match the demo's 13-minute
   target — it can be 30-60 minutes long if the search runs at
   realistic pace. Pacing happens at the editing stage.
3. Capture every "shot list" item from the per-segment Harness
   operator notes. If something on the shot list isn't visible in
   the recording, that segment's clip won't work.
4. After the recording session, cut the source material into
   segment-aligned clips. Each clip's runtime should match the
   "Time" column from the time budget table below, with a few
   seconds of padding on either end so the voiceover can lead and
   trail naturally.
5. Voiceover is delivered **live at the conference**, in sync with
   the playback. Do not pre-record the voiceover — the presenter
   needs to be able to ad-lib, respond to audience cues, and
   adjust pacing in real time.

### Visual style for the recording

- Clean structured terminal output (not a UI mockup) so the
  audience sees the real thing — LEO audiences are particularly
  sensitive to demo polish that hides what's really happening
- Role labels prominent — "Pattern Analyst" not "agent-5"
- `actor_id` and `driver_id` rendered in distinct colors so the
  identity distinction is visible from the back of the
  room[^identity-triple][^driver-id]
- Sensitive-data quarantine notifications must be impossible to
  miss (red, bordered, animated, ideally all
  three)[^data-curation]
- Contradiction markers visually distinct from normal memory
  writes[^contradiction]
- Cross-incident memory references should visually link to the
  prior incident ID (e.g., "from PS-2024-031") so the audience
  understands they're seeing actual recall, not generic
  output[^cross-incident]
- Resolution: at minimum 1920x1080, ideally 2560x1440 or higher
  if conference projection supports it
- Terminal font: large enough to read from the back row of a
  conference session room (think 18pt+ at recording resolution)

### LEO-audience-specific recording cautions

This is critical for the LEO audience and applies more strictly
than for clinical or cybersec demos:

- **Use obviously fake names** for everyone — the subject, the
  officers, the analysts, the IC, every supporting character. If
  the names sound too real, audience members will assume the
  demo is based on a real case and ask which one. Use names like
  "Daniel Voss," "Sergeant Hammond," "Detective Morales" that
  sound plausible but are unmistakably synthetic.
- **Use obviously fake jurisdictions** — not your home city, not
  the conference city, not any major city in the news. The
  scenario doc uses "Riverside District" and references generic
  "neighboring city PD" and "county sheriff" — keep it that
  generic.
- **Use obviously fake plate numbers, addresses, and phone
  numbers**. Any audience member who recognizes a real plate
  format is going to wonder if the demo is showing real data.
  Use formats that are clearly invented (e.g., plate "DEMO-001"
  or "7BVJ391" — anything that doesn't look like a real
  state-issued plate from a recognizable jurisdiction).
- **Do not show real LPR networks, real camera vendor branding,
  or real RTCC interfaces**. Even unintentional brand placement
  will create the impression that MemoryHub is endorsing or
  competing with specific vendors. Use generic terminal output
  throughout.

### Live cluster fallback

If WiFi at the conference is observably reliable in the 30
minutes before the talk, live execution becomes Plan A and
recorded clips become Plan B. The decision happens just before
the session starts. **The recorded clips must always be ready as
the default**, not as a last-minute scramble. Test the playback
path on the conference's actual A/V setup at least 15 minutes
before showtime regardless of which plan is in effect.

The harness used for the live execution path is the same one
that generated the recording — there are no two harnesses to
maintain. Switching from recorded to live means starting the
same harness, pointed at a real cluster with the agent fleet
preloaded, instead of playing back the saved video.

**Critical**: if going live, do not connect to anything that
looks like a real LEO operational environment over conference
WiFi. The audience will assume your demo cluster is a real
operational deployment and any visible details (network
topology, hostname conventions, jurisdictional references) will
become a liability. Use a clearly fake environment with
synthetic data and obviously-made-up everything.

## Time budget

Total: 13 minutes (gives you 2-minute cushion against the 15-minute
hard cap; can compress to 10 minutes by trimming Phases 5-6
walkthrough if running long).

| Segment | Time | What's on screen |
|---|---|---|
| 1. Opening hook and framing | 1:30 | Title slide → search archetype slide |
| 2. Meet the search and team | 1:30 | Voss case intro → agent fleet startup |
| 3. Initial canvass & "we've seen this before" | 2:00 | Recorded clip: hypothesis formation, cross-incident pattern recognition |
| 4. Lead development & shift handoff | 3:00 | Recorded clip: parallel investigation, IC shift change, LPR vs tip contradiction, agent-operational memory |
| 5. Convergence with negative findings discipline | 2:00 | Recorded clip: doorbell hit, multi-source convergence, the killer moment |
| 6. Audit trail and chain of accountability | 1:30 | Recorded clip: audit query showing actor/driver split |
| 7. Apprehension & post-incident learning | 0:30 | Brief apprehension scene, after-action memories written |
| 8. Closing pitch | 1:00 | Recap slide → call to action |

Buffer: 30 seconds for transitions and audience reactions.

## Segment 1 — Opening hook and framing (1:30)

### What's on screen

Title slide: **"MemoryHub: the context that makes tactical decisions go well."**[^value-prop]

Below the phrase, a small subtitle: *"A demonstration with a
synthetic multi-jurisdictional fugitive search."*

### Talking points

**The hook (30 seconds)**: Open with a relatable LEO operational
moment.

> "Every incident commander in this room has had this moment.
> You're running a search, your team is stretched across multiple
> shifts and multiple agencies, and ninety minutes into your shift
> you find out that your officers were re-tasked to an area you
> already cleared at 02:30 in the morning. The negative finding
> from the previous shift never made it through the handoff. Now
> you're playing catch-up while your subject is doing whatever
> they're doing in the background. Sometimes you recover the lost
> ground. Sometimes you don't. When you don't, the public safety
> consequence is real."

**The framing (30 seconds)**: Establish what we're showing and what
we're NOT showing. Address the third rails directly to clear the
air.[^decision-support-boundary]

> "What I'm about to show you is not another CAD platform. It's
> not a new RMS. It's not a GIS upgrade. And I want to be very
> clear up front about three things it is also *not*. It is not
> predictive policing. It is not facial recognition. It is not
> autonomous threat assessment. Those phrases are burned for
> good reasons, and I am not interested in re-burning them."
>
> "What you're about to see lives *alongside* everything you
> already use. Your CAD is dispatching units. Your GIS is
> plotting their location. Your RMS is holding the case file.
> What MemoryHub holds is the operational picture across time
> and across sources — the team's current best hypothesis, the
> negative findings that prevent re-tasking, the cross-incident
> patterns from prior similar searches, the soft tribal knowledge
> your senior commanders carry, and the fleet's own operational
> learning."

**The agent disclaimer (30 seconds)**: Get this in early. Don't let
the audience misread the demo as autonomous tactical
decision-making.[^humans-in-loop]

> "I'll be playing the role of the entire response team during
> this demo. Every agent you see is operated by a human
> practitioner in production. The Camera Network agent? In
> production, that's your CCTV operator in your real-time crime
> center. The Pattern Analyst agent is your crime analyst. The
> Tip Line Triage agent is your tip line analyst. The Incident
> Commander agent is the IC running the search. **These agents
> help your people; they don't replace them. They do not make
> tactical decisions. They do not assess threats. They do not
> identify suspects.** Your officers and analysts make every
> decision. The agents hold the operational memory those
> decisions need to be made well."

### Milestones demonstrated

None yet — this is setup. But you've planted four things:

- The phrase[^value-prop]
- The decision-support boundary[^decision-support-boundary]
- The agents-support-humans framing[^humans-in-loop]
- Explicit rejection of the LEO third rails (predictive
  policing, facial recognition, autonomous threat
  assessment)[^humans-in-loop]

### Harness operator notes / shot list

- No harness footage in this segment. Stay on slides.
- Have the recorded clip queued up to begin on the cue at the
  start of Segment 2.

## Segment 2 — Meet the search and team (1:30)

### What's on screen

Slide: search archetype. The Voss case basics — when, where, what
happened, what's known, what's not known, the time pressure.

Then transition to the recorded clip showing the agent fleet
registering with MemoryHub.[^identity-triple][^cli-provisioning]

### Talking points

**The search introduction (45 seconds)**: Make the search concrete,
not abstract.

> "01:14 in the morning. A non-fatal shooting at a nightclub in
> the Riverside District. Two victims with gunshot wounds, both
> transported in stable condition. Witnesses identify the
> suspect by sight and security camera footage captures a clear
> view of his face. He's a 28-year-old local man named Daniel
> Voss. A state warrant is issued at 03:00 AM. Your active
> multi-agency search begins at 03:30."
>
> "What you know: he was on foot when he left the scene. He has
> a maroon Camry registered to him, but the LPR network hasn't
> seen it since 01:38, suggesting he abandoned it within thirty
> minutes. He has family in the area — a brother in the next
> county, an ex-girlfriend in town, a cousin two counties over.
> What you don't know: where he is now, whether he's still on
> foot, whether he has a different vehicle, whether he's
> changed clothes. He's potentially armed and is being treated
> as such."
>
> "Over the next six hours, your multi-agency response team is
> going to coordinate a search across two jurisdictions, multiple
> sensor sources, and at least one shift change. Today, on
> screen, you're going to watch how that team uses shared memory
> to do that coordination. Ten roles, working in parallel,
> sharing what they know, learning from what your agencies have
> learned in past searches."

**Why this scenario (15 seconds)**:

> "I want to point out one thing about this scenario before we
> start. The subject has been positively identified by humans
> *before* the agent fleet ever activates. Witnesses identified
> him. A judge issued a warrant. The agents' job is *locating*
> him, not *identifying* him. This is a deliberate framing
> choice — it keeps the demo clear of the most politically
> loaded territory in this space."

**Agent fleet startup (30 seconds)**: Cue the recorded clip. Show
the ten agents registering with MemoryHub.[^identity-triple][^project-scope]

> "On screen now you'll see the response team fleet starting up.
> Each agent is registering with MemoryHub and being
> authenticated. Watch the role names — Camera Network, License
> Plate Reader, Drone Operations, Tip Line Triage, Pattern
> Analyst, Geographic Analyst, Multi-Agency Liaison, Incident
> Commander, Resource Dispatcher, Public Information. Ten
> roles. In production, each one is the interface a working
> practitioner uses to chat with the operation's accumulated
> shared memory."

### Milestones demonstrated

- **Identity model**[^identity-triple]: ten agents come online,
  each with its own identity. The recorded clip shows each
  agent's `actor_id` as it registers.
- **Project membership**[^project-scope]: all ten agents are
  members of a shared project (`voss-search-2024`). The audit
  trail will hang off this project membership later.
- **Fleet provisioning**[^cli-provisioning]: implicit — the fleet
  was generated from a manifest by the agent generation CLI.

### Harness operator notes / shot list

- **Capture**: each agent's `register_session` call landing in
  the harness output, with the role name and `actor_id` clearly
  visible. Hold for 1-2 seconds per agent so the audience can
  read the role names.
- **Capture**: a confirmation line showing all ten agents are
  members of the `voss-search-2024` project.
- The driver_id at this point is set to the demo presenter
  (e.g., `wjackson-iacp-demo-1`). Make sure it's visible in the
  registration output — it will be referenced later in the
  audit trail segment.[^driver-id]

## Segment 3 — Initial canvass & "we've seen this before" (2:00)

### What's on screen

Recorded clip showing the initial response, hypothesis formation,
and the cross-incident pattern recognition moment that shapes the
team's geographic analysis.[^cross-incident]

### Talking points

**Initial canvass (30 seconds)**:

> "It's 04:30 AM. The team is forty minutes into the active
> search. The Camera Network agent has been reviewing
> retrospective footage from cameras near the nightclub and
> along plausible escape routes. LPR is checking for any hits
> on the subject's vehicle. The Tip Line Triage agent is
> standing up to take calls from the public after the BOLO
> goes out. And in parallel, watch what's happening in the
> Pattern Analyst's chair."

**The killer moment 1 (1:00)**: Slow down. Make it land.[^cross-incident]

> "The Pattern Analyst agent is forming the team's initial
> geographic hypothesis. It's searching shared memory for
> prior searches with similar subject profiles. Watch what
> it surfaces."
>
> "A memory written fourteen months ago after PS-2024-031, a
> multi-jurisdictional search in Marshall County. Here's
> what it says: 'Subject profile — male, late 20s, local,
> prior contact with the system, fled on foot from a
> non-domestic violent incident, vehicle abandoned within
> thirty minutes, no known affiliation with organized
> criminal networks. Subject in that search was found
> eighteen hours later in a detached outbuilding behind an
> extended family member's residence, 6.2 miles from the
> initial scene. Lesson for similar profiles — prioritize
> known extended family addresses in geographic analysis,
> especially outbuildings rather than primary residences
> where surveillance is more obvious.'"
>
> "The Pattern Analyst weights this pattern. The Geographic
> Analyst, reading the same memory, surfaces the cousin's
> residence in the neighboring jurisdiction as a
> high-probability shelter location at 04:45 AM — *nearly
> four hours* before the subject is observed there."
>
> "Now I want you to think about what just happened. Your
> agency has institutional memory of a search you ran
> fourteen months ago. In current practice, that memory is
> in a postmortem report nobody has read since the day it
> was filed, in the head of the analyst who wrote it (who
> may have transferred or retired), and in a debrief
> presentation slide deck no one can find. Tonight, at
> 04:45 AM, your Pattern Analyst is using that memory to
> shape today's geographic priorities. *That* is what we
> mean by the context that makes tactical decisions go
> well."[^value-prop]

**The tribal knowledge moment (30 seconds)**:[^tribal-knowledge]

> "While the Pattern Analyst is doing its work, watch what
> happens at the Tip Line Triage agent. Tips are starting to
> come in after the BOLO went public at 04:30. The agent is
> applying a filter — and that filter comes from a memory
> written three months ago: 'When IC Sergeant Hammond is
> running a search, she prefers tip line items pre-scored
> for credibility before they hit her queue. She does not
> want low-credibility items unless three or more
> independent reports converge on the same location. This
> is a personal preference based on her experience that
> high-volume tip queues drown the IC's attention.'"
>
> "Sergeant Hammond is the IC tonight. The Tip Line agent
> applies her preferred filter automatically. This kind of
> soft preference walks out the door when Hammond rotates
> off the IC role or retires. Here, it's persistent."

### Milestones demonstrated

- **Cross-incident pattern recognition**[^cross-incident] (the
  killer moment 1)
- **Project-scope reads**[^project-scope] (Pattern Analyst
  reading the team's shared memory)
- **Tribal knowledge memory**[^tribal-knowledge] (the IC
  preference filter)
- **Value prop landing**[^value-prop]: the headline phrase gets
  its first strong demonstration here

### Harness operator notes / shot list

- **The cross-incident memory recall is the most important
  shot in this segment.** The Pattern Analyst agent's
  `search_memory` call must be visible, the PS-2024-031 memory
  text must be on screen, and the camera needs to hold on it
  for at least 4 seconds — long enough that even the slowest
  reader can take it in.
- **Capture**: the Geographic Analyst surfacing the cousin's
  residence as a high-priority location, with timestamp
  visible. The audience needs to see "the agent identified
  this location at 04:45 — four hours before the subject was
  observed there."
- **Capture**: the IC preference memory being read by the Tip
  Line Triage agent.
- The visual styling should make the prior search reference
  ("PS-2024-031") clickable-looking, even if it's just text —
  the audience should understand "this is a real recall of a
  real prior search."[^cross-incident]

## Segment 4 — Lead development & shift handoff (3:00)

### What's on screen

The longest segment. Multiple moments compressed into a fast-paced
walkthrough of the lead development phase. Key beats:

- Tips flowing in, multi-source canvassing
- The IC shift change at 06:00 AM (different person taking over
  the same role)[^role-vs-person][^driver-id]
- LPR-vs-tip-caller location contradiction[^contradiction]
- A second contradiction between Pattern Analyst and Geographic
  Analyst[^contradiction]
- The Drone agent applying agent-operational memory (the
  cold-weather thermal hit rule)[^operational-memory]
- A sensitive-data quarantine moment (innocent third-party
  identification)[^data-curation]

### Talking points

**Lead development (30 seconds)**:

> "Skipping ahead to 05:30 AM. Tips are flowing in. The Camera
> Network agent is canvassing in real time. LPR is checking
> vehicles. The Drone agent is searching open terrain. The
> Pattern Analyst has formed an initial hypothesis and the
> team is testing it against incoming evidence. And the
> Riverside neighborhood — our most promising area in the
> first hour — has just been fully cleared by the Camera
> Network agent. No match. Negative finding written to shared
> memory at 05:30."

**The shift handoff moment (1:00)**: This is where you make the
role-vs-person distinction land for an LEO
audience.[^role-vs-person][^driver-id][^audit]

> "Here's something that's going to happen at 06:00 AM, when
> Sergeant Hammond's shift ends and Sergeant Chen takes over
> as IC. Watch the Incident Commander agent right now."
>
> "The IC *role* persists across the shift change. Same actor
> identity, same accumulated memory of the search so far.
> What changes is the *driver* — the human on whose behalf
> the agent is now acting. At 05:59, the IC agent is being
> driven by Sergeant Hammond. At 06:01, the IC agent is being
> driven by Sergeant Chen. The agent's `driver_id` updates.
> Same role, different human."
>
> "And here's why this matters for an active search. Sergeant
> Chen, at 06:01, has the complete operational picture
> Hammond built up overnight — the working hypothesis, the
> reasoning behind it, the negative findings (including the
> Riverside clear), the contradiction between the LPR hit and
> the tip caller, every piece of evidence that came in and
> was acted on. Without any handoff loss. The shift changed.
> The institutional memory of the search did not."
>
> "And now think about what happens at 06:30, when Chen needs
> to make a decision about whether to re-task the Bravo team.
> The negative finding from Hammond's shift — Riverside
> cleared, full coverage of exits — is right there. Chen
> doesn't re-task to Riverside. Bravo gets sent where it can
> do good. **That** is the negative findings discipline. It's
> the single biggest pain point in active searches and
> MemoryHub turns it into a structural fix."

**The contradiction moment (45 seconds)**:[^contradiction]

> "Earlier in the shift, around 06:00, the LPR agent wrote
> this memory: 'LPR hit at 05:58 on the subject's known
> plate, maroon Camry, at the intersection of Highway 14
> and Rural Route 7, eastbound. Confirmed plate match.'"
>
> "About ten minutes later, the Tip Line Triage agent wrote
> a contradicting memory: 'Tip caller at 06:08 reports a
> male matching the subject description on foot at the bus
> station downtown, four miles from the LPR hit location.
> Caller has previously called in two credible tips. The
> tip and the LPR hit are physically inconsistent — the
> subject can't be in both places at the same time. Either
> someone else is driving the Camry or the foot sighting is
> mistaken identity.'"
>
> "Tip Line calls `report_contradiction`. MemoryHub surfaces
> the conflict. The IC reads both memories and adjudicates.
> Decision: dispatch ground units to confirm the bus
> station sighting (higher likelihood given the working
> hypothesis the subject is on foot), while flagging the
> LPR hit as possible vehicle theft or unauthorized use.
> Both interpretations preserved in memory. The LPR hit
> turns out to be a cousin's husband driving the Camry —
> unrelated to the subject's location. The bus station
> sighting turns out to be misidentification. But the
> adjudication directed the higher-priority investigation
> first."

**Agent-operational memory and sensitive-data quarantine (45 seconds)**:[^operational-memory][^data-curation]

> "Two quick things to point out before we move on. First,
> watch the Drone agent. It just got a thermal hit at 06:15
> in a wooded park area. And instead of flagging it as
> 'probable subject,' it flagged it as 'thermal signature
> pending confirmation.' Why? Because it's reading a memory
> it wrote *to itself* after a prior operation: 'When
> running thermal coverage of wooded terrain in cold
> weather, deer signatures consistently look like seated
> humans on the first pass. Rule: in cold-weather wooded
> terrain, require either a second visual confirmation pass
> or a ground team check-in before flagging a thermal hit
> as probable subject.' The Drone agent applied its own
> learned rule. The IC was not pulled away from the working
> hypothesis to investigate a likely deer."
>
> "Second — and this is a governance moment — the Camera
> Network agent just attempted to write a memory containing
> the name, plate, and home address of an *uninvolved*
> woman whose car happened to be in the search area. Her
> car matched a generic description in the BOLO. Ground
> units cleared her in 90 seconds. But the Camera Network
> agent's memory write would have persisted her identifying
> details into our shared operational memory just because
> her car was in the wrong place. The curation pipeline
> caught it. Her name and address are not in shared memory.
> The investigative fact — that we checked, that it wasn't
> the subject — is preserved. The uninvolved person's
> identifying details are not."

### Milestones demonstrated

- **Driver_id distinction across shift handoff**[^driver-id]:
  same role, different humans across IC handoff. The role
  persists; the audit trail captures who was driving when.
- **Role-vs-person identity model**[^role-vs-person]: actor (the
  IC role) is stable across the shift change; driver (the
  human IC on shift) changes per session.
- **Negative findings discipline**[^cross-incident]: the
  Riverside clear from the prior shift survives the handoff
  and prevents wasted re-tasking.
- **Project-scope reads**[^project-scope]: agents reading from
  the shared search memory.
- **Contradiction detection**[^contradiction]: report_contradiction
  in action over an LPR-vs-tip-caller conflict.
- **Agent-operational memory**[^operational-memory]: the Drone
  agent applying its own self-written operational lesson.
- **Sensitive-data quarantine**[^data-curation] on innocent
  third-party identification.
- **Audit trail of the quarantined attempt**[^audit].

### Harness operator notes / shot list

- **The shift change moment must be visually obvious in the
  recording.** Show the `driver_id` value changing from
  Hammond's session to Chen's session in the harness output
  while the `actor_id` (the IC role identity) stays constant.
  If the harness doesn't natively highlight this, add a
  callout in post-production editing.
- **Capture**: the Riverside negative finding being read by
  the new IC and influencing the re-tasking decision. The
  audience needs to see the linkage between the prior shift's
  finding and the current shift's decision.
- **Capture both memories of the LPR-vs-tip
  contradiction**: LPR's hit memory and Tip Line's
  contradicting memory. When `report_contradiction` is
  called, the relationship between the two memories should be
  visually rendered. Side-by-side display preferred.
- **Capture**: the Drone agent's thermal hit being flagged as
  "pending confirmation" with the agent-operational memory
  visible nearby.
- **Capture both halves of the third-party PHI moment**: the
  rejected attempt with the uninvolved woman's identifying
  details visibly marked as quarantined, and the rewritten
  successful version that preserves only the operational fact.

## Segment 5 — Convergence with negative findings discipline (2:00)

### What's on screen

The second killer moment. A doorbell camera detection at 06:42
triggers multi-source convergence. The negative findings from
the prior shift have freed resources that get pre-positioned at
the convergence location. Tactical assets are in place when the
detection happens, allowing rapid response.

### Talking points

**The killer moment 2 (1:15)**:[^cross-incident][^narrative-context]

> "06:42 AM. Watch what happens on screen. A doorbell camera
> in a residential neighborhood registers what looks like the
> subject — male matching the description, walking
> northbound on Maple Street. The Camera Network agent
> surfaces the hit at project scope."
>
> "Now in current practice, here's what would happen with that
> hit. It would land in someone's queue. An analyst would see
> it. The analyst would have to decide: is this the subject?
> Is this someone else who happens to look like him? What's
> the context? Where is this in relation to the working
> hypothesis? It would take ten or fifteen minutes to figure
> out, and by then the subject — if it is him — has moved on."
>
> "Watch what happens here instead. The Pattern Analyst agent
> reads the doorbell hit and immediately writes a linking
> memory: 'Doorbell hit at 06:42 on Maple Street is consistent
> with the subject heading northbound from his last known
> position at the abandoned vehicle location. Walking pace
> and direction match. If continued on this trajectory, he
> reaches the vicinity of his cousin's residence — already
> identified as a high-priority location at 04:45 — within
> the next 45 to 60 minutes.'"
>
> "The hit and the four-hour-old hypothesis link in *seconds*,
> not minutes. The Geographic Analyst confirms the route is
> walkable. The Multi-Agency Liaison confirms the surveillance
> is in place at the cousin's residence in the neighboring
> jurisdiction. The Resource Dispatcher pre-positions tactical
> assets near the area."
>
> "And here's the operational payoff — the resources being
> pre-positioned are *available* because the negative findings
> discipline freed them. The Riverside neighborhood was
> cleared at 05:30. Bravo team didn't get re-tasked there
> after the shift change. They're available now, when the
> convergence is happening, and they get pre-positioned in
> minutes instead of being recalled from a wild goose chase."
>
> "*This* is what the context that makes tactical decisions go
> well looks like in practice. Three things came together —
> the four-hour-old hypothesis, the negative findings
> discipline, and the multi-source convergence — because the
> memory layer was holding all of it."[^value-prop]

**The credential-style data quarantine moment (15 seconds)**:[^data-curation]

> "And one quick governance moment — the Tip Line agent just
> attempted to write a memory referencing a confidential
> informant by name and CI number. The curation pipeline
> caught it instantly. Source identification in operational
> memory is a tradecraft violation. The CI's identity is
> managed through normal handling procedures, where it
> belongs. The operational fact — that the tip was
> high-credibility from an established source — is
> preserved. The source's identity is not."

**Tactical assets in place (30 seconds)**:[^humans-in-loop]

> "By 07:30 AM, the working hypothesis has updated to high
> confidence. The cousin's residence is under surveillance.
> A tactical team is staged nearby. The Drone agent has
> overflight in support. And — I want to emphasize this — no
> agent has made a tactical decision. The IC made the call to
> pre-position the team. The tactical commander made the call
> on the approach. The dispatcher made the call on which
> units to commit. The agents held the operational picture
> that informed every one of those decisions, but the
> decisions were made by humans."

### Milestones demonstrated

- **Multi-source convergence linking new evidence to prior
  hypothesis**[^cross-incident] (the killer moment 2)
- **Negative findings discipline payoff**[^cross-incident]: the
  Riverside clear freed resources for the convergence
- **Sensitive-data curation**[^data-curation] catching source
  identification
- **Audit trail of the curation event**[^audit]
- **Agents-support-humans framing**[^humans-in-loop]: explicit
  reinforcement that tactical decisions remain with humans

### Harness operator notes / shot list

- **The convergence moment is the most important shot in the
  entire recording for the LEO audience.** The Pattern
  Analyst agent's linking memory must be visible, the
  reference back to the four-hour-old hypothesis must be
  clear, and the audience needs to see the cascade —
  Geographic Analyst confirming, Liaison confirming, Resource
  Dispatcher pre-positioning. Hold on each step long enough
  that the cascade is legible.
- **Capture**: the doorbell hit being received by the Camera
  Network agent.
- **Capture both halves of the CI quarantine**: the rejected
  attempt with the CI name and number visible in the rejected
  text (use obviously fake values), visibly marked as
  quarantined, and the rewritten successful version.
- The visual styling should reinforce that human decisions
  are happening — show the harness output recognizing that
  the IC, tactical commander, and dispatcher are making
  approval-required decisions, not auto-execution.

## Segment 6 — Audit trail and chain of accountability (1:30)

### What's on screen

The recorded clip shifts to a query mode. Two queries are run:

1. "Show me everything the IC role did during the Voss search,
   with attribution to which sergeant was on duty."
2. "Show me everything done on behalf of Sergeant Hammond
   across all roles during this search."

The two queries return different result sets, both correctly
attributed.[^audit][^driver-id][^role-vs-person]

### Talking points

**The chain-of-accountability hook (45 seconds)**: LEO audiences
care about audit for two reasons: internal accountability and
public accountability. Frame
both.[^audit][^identity-triple][^driver-id]

> "Let me switch from the search narrative for a moment and
> talk to the chiefs and sheriffs in the room. Everything we
> just walked through — every memory written, every memory
> read, every contradiction reported, every quarantine event
> — is recorded in MemoryHub's audit log. Every operation has
> two identities attached: the *actor* (which agent did it)
> and the *driver* (the human on whose behalf it was done)."
>
> "This is your **chain of accountability**. When this search
> gets a debrief next week — or when there's a public
> records request, or a use-of-force review, or a court
> proceeding — you need to be able to reconstruct who made
> which call and why. Not 'the SOC made this call' — sorry,
> 'the response team made this call' — but 'the IC role made
> this call at 06:42, on the basis of these memories, while
> being driven by Sergeant Chen.' MemoryHub gives you that
> reconstruction by default, not as an after-the-fact manual
> exercise."
>
> "And for those of you thinking about bias mitigation: this
> is what makes bias mitigation tractable. When every action
> is attributed to a human, you can review patterns of human
> decision-making. You can see exactly who made which call
> and why. The audit trail is the bias mitigation story —
> not because it prevents bias, but because it makes bias
> visible and reviewable."

**Query 1 (20 seconds)**:[^role-vs-person][^audit]

> "Watch this. I'm going to ask: 'Show me everything the IC
> role did during the Voss search.' On screen now you're
> seeing every action that role took — across both Sergeant
> Hammond's shift and Sergeant Chen's shift, because the
> role spans the boundary. Every read, every write, every
> contradiction adjudicated, every memory consulted."

**Query 2 (20 seconds)**:[^driver-id][^audit]

> "Now I'm going to ask a different question: 'Show me
> everything done on behalf of Sergeant Hammond across the
> entire response team during this search.' Different result
> set. This shows me what Hammond was driving — not just the
> IC role, but any other role she touched while she was on
> duty."

**The point landing (5 seconds)**:

> "Both questions are answerable in seconds. In your current
> debrief process, that's a multi-day project of correlating
> CAD entries, RMS notes, dispatch logs, and half-remembered
> shift handoff conversations."

### Milestones demonstrated

- **Audit log with actor/driver split**[^audit][^identity-triple]
- **Driver_id queryability**[^driver-id] — both directions (by
  role, by human-on-whose-behalf)
- **Role-vs-person identity model in
  action**[^role-vs-person]
- **Chain of accountability use case** — the LEO-specific
  framing of the compliance hook
- **Bias mitigation framing**: every action is attributed to a
  human and is reviewable

### Harness operator notes / shot list

- **Capture both queries running** with their distinct result
  sets visible. This is one of the few segments where the
  on-screen content is dense — the audience needs to see
  actual rows of audit data, not just a summary.
- Result rows must clearly show the `actor_id` and `driver_id`
  columns so the distinction between the two queries is
  visible.[^identity-triple][^driver-id]
- For the recording: ensure the queries are pre-baked and
  produce well-formatted output, not raw JSON dumps. A
  four-column table (timestamp, action, actor, driver) is
  the right shape.
- **If running live as Plan A**: the two queries must be in a
  prepared script that the presenter triggers with a single
  keystroke each, so there's no typing latency on stage.

## Segment 7 — Apprehension and post-incident learning (0:30)

### What's on screen

A brief moment from the apprehension and the next-day after-action
review. The team writes new memories explicitly for future
operations.[^cross-incident][^narrative-context]

### Talking points

**Closing the loop (30 seconds)**:[^cross-incident][^narrative-context][^humans-in-loop]

> "08:47 AM. The tactical team approaches the cousin's
> residence. The subject is observed entering the detached
> garage at 08:43. Tactical entry. Subject arrested without
> incident at 08:47. The firearm is recovered. End of search.
> Let me be very clear about what happened in those final
> minutes: a tactical commander made the approach decision,
> a tactical team executed the entry, and the arrest was
> made by officers. Nothing on this slide was decided by an
> agent."
>
> "The next day, the team holds the after-action review. And
> here's what's different from your current debrief process —
> the lessons learned aren't just going into a report nobody
> will read. They're being written to MemoryHub directly, by
> the IC and the Pattern Analyst, as memories that the
> response team will read during the next similar search.
> 'Doorbell camera networks were the inflection point in
> this search, not LPR hits — weight residential doorbell
> coverage higher in similar future searches.' 'The
> negative findings discipline freed resources at exactly
> the right moment — keep that discipline.' The lessons
> from today will shape tomorrow's search."

### Milestones demonstrated

- **Explicit cross-incident learning capture**[^cross-incident]
  via post-incident memory writes
- **Narrative context category**[^narrative-context]: lessons
  written as narrative, not as structured rules
- **Humans-in-loop reinforcement**[^humans-in-loop]: explicit
  closing reinforcement that tactical decisions and arrest
  authority remain with humans

### Harness operator notes / shot list

- **Capture**: the IC agent and Pattern Analyst writing the
  lesson memories. Hold for 2 seconds each so the audience
  can read the lesson text.
- This segment is the closing beat of the substantive demo.
  Keep it short but make sure the lesson memories are
  readable on screen.

## Segment 8 — Closing pitch (1:00)

### What's on screen

Recap slide with the phrase, the boundary, and the bullets covering
what the audience just saw. End slide with contact info / call to
action.

### Talking points

**The phrase, one more time (15 seconds)**:[^value-prop][^decision-support-boundary]

> "MemoryHub holds the context that makes tactical decisions
> go well. That phrase is the entire pitch. Your CAD
> dispatches the units. Your GIS plots their location. Your
> RMS holds the case file. MemoryHub holds everything around
> them — the operational hypothesis your team is working
> from, the negative findings that prevent wasted re-tasking,
> the cross-incident patterns from prior similar operations,
> and the soft tribal knowledge your senior commanders carry."

**What you saw (30 seconds)**: Recap the moments that mattered
most.

> "What you saw in the last twelve minutes:
>
> One. The Pattern Analyst surfaced a memory from a search
> fourteen months ago and used it to identify a high-priority
> location four hours before the subject was observed
> there.[^cross-incident]
>
> Two. The IC role's complete operational picture survived a
> 06:00 AM shift change, with the audit trail capturing both
> sergeants' decisions independently.[^role-vs-person][^driver-id]
>
> Three. The negative findings discipline kept resources from
> being re-tasked to an already-cleared area, and those
> resources were available when the convergence happened
> three hours later.[^cross-incident]
>
> Four. A multi-source convergence — a doorbell hit, a
> four-hour-old hypothesis, a pre-staged tactical team —
> happened in seconds because the memory layer was holding
> all of it.[^cross-incident][^value-prop]
>
> Five. An audit trail that answers both 'what did this role
> do?' and 'what was done on behalf of this sergeant?' in
> seconds — your chain of accountability for debriefs,
> public records requests, and reviews."[^audit]

**The call to action (15 seconds)**:

> "MemoryHub runs on Red Hat OpenShift AI. It complements
> your existing operational stack — CAD, RMS, GIS, LPR — it
> doesn't compete with any of them.[^decision-support-boundary]
> We're looking for agencies and integrators who want to
> pilot it with their own search and incident operations.
> Come find us at booth [X], or reach out at [contact].
> Thank you."

### Milestones demonstrated

None new — this is recap.

### Harness operator notes / shot list

- No recorded clip in this segment. Stay on the recap slide
  for the full 30 seconds while the presenter delivers the
  "what you saw" beats. Don't transition too fast.

## Demo flow at a glance

For rehearsal purposes, the milestone tie-ins are easier to scan as
a single table:

| Time | Segment | Primary milestone | Secondary milestone | Footnotes |
|---|---|---|---|---|
| 0:00-1:30 | Opening hook & framing | (None — setup) | Phrase, decision-support boundary, no third rails | `[^value-prop]` `[^decision-support-boundary]` `[^humans-in-loop]` |
| 1:30-3:00 | Search & team intro | Identity model (10 agents register) | Project membership, fleet provisioning | `[^identity-triple]` `[^project-scope]` `[^cli-provisioning]` |
| 3:00-5:00 | Initial canvass & "we've seen this before" | Cross-incident pattern recognition (KILLER MOMENT 1) | Tribal knowledge | `[^cross-incident]` `[^tribal-knowledge]` `[^value-prop]` |
| 5:00-8:00 | Lead development & shift handoff | Driver_id distinction + negative findings discipline | Contradiction detection, agent-operational memory, third-party data quarantine | `[^role-vs-person]` `[^driver-id]` `[^contradiction]` `[^operational-memory]` `[^data-curation]` `[^cross-incident]` |
| 8:00-10:00 | Convergence | Multi-source convergence linking to prior hypothesis (KILLER MOMENT 2) | Negative findings payoff, source identification quarantine | `[^cross-incident]` `[^narrative-context]` `[^data-curation]` `[^value-prop]` `[^humans-in-loop]` |
| 10:00-11:30 | Audit trail | Driver_id audit query | Role-vs-person + chain of accountability | `[^audit]` `[^driver-id]` `[^role-vs-person]` `[^identity-triple]` |
| 11:30-12:00 | Apprehension & post-incident | Explicit cross-incident learning capture | Humans-in-loop reinforcement | `[^cross-incident]` `[^narrative-context]` `[^humans-in-loop]` |
| 12:00-13:00 | Closing pitch | Recap of all milestones | Call to action | (all of the above) |

## Trim plan if running long

If at the 8-minute mark you're noticeably behind, here are the
specific cuts in priority order:

1. **First cut**: trim Segment 7 entirely. Skip the post-incident
   learning capture moment. Save 30 seconds. **Lost milestones**:
   the explicit "writing memories for the next search" demo. The
   general `[^cross-incident]` concept stays demonstrated in
   Segments 3 and 5.
2. **Second cut**: shorten the agent-operational memory mention
   in Segment 4 to a single sentence ("the Drone agent also
   filters known false positives based on its own learned
   patterns — we'll talk about that in Q&A"). Save 25 seconds.
   **Lost milestones**: `[^operational-memory]` is reduced to a
   mention, not a demonstration.
3. **Third cut**: drop the third-party PHI quarantine moment in
   Segment 4. Keep the source identification quarantine in
   Segment 5. Save 20 seconds. **Lost milestones**: one of two
   `[^data-curation]` demonstrations.
4. **Fourth cut**: drop one of the two audit queries in Segment 6
   (keep the role-based one, drop the human-based one, mention
   the second briefly in narration). Save 30 seconds. **Lost
   milestones**: half of `[^driver-id]`'s demonstration. Keep
   query 1 (which still demonstrates `[^role-vs-person]`) and
   describe query 2 verbally without running it.

Total trimmable: ~1:45. This brings worst-case 13-minute target
down to ~11:15, well inside the 15-minute hard cap.

## Trim plan if running short

If you finish at 11 minutes and want to fill to 13, the easy
extensions are:

1. Spend more time on Segment 3's "we've seen this before" moment.
   Let the audience really sit with the PS-2024-031 memory and
   what it would mean for their own agency.
2. Spend more time on Segment 5's convergence moment. Walk the
   audience through the cascade — doorbell hit, hypothesis link,
   geographic confirmation, liaison confirmation, pre-positioning
   — slowly enough that the timing impact lands.
3. Add an aside in Segment 6 about how the chain of accountability
   integrates with their existing debrief processes and public
   records request workflows.
4. Pause for one audience question in the Q&A position before
   closing.

Don't try to add new material on the fly — rehearsed material
delivers better than improvised expansion.

## What you absolutely cannot say

Words and phrases that will lose the room (and potentially become
a story the audience has to defend in a meeting next
week):[^humans-in-loop][^decision-support-boundary]

- "Predictive policing" (any usage, any framing)
- "Facial recognition" (avoid prominently even if the technology
  exists)
- "Autonomous threat detection" / "AI threat assessment"
- "AI identifies the suspect" — the agents *locate*; humans
  *identify*
- "Automated tactical decision-making"
- "Replaces officers" or "fewer officers needed"
- "Reduces human oversight" / "removes the human in the loop"
- "Surveillance" used positively (the audience knows the word
  is loaded)
- "Profile" used as a verb ("the agent profiles suspects") — use
  "search the team's prior incident memory for similar profiles"
  instead
- "AI policing" / "smart policing" (vendor cliches that signal
  hype)
- "Catches criminals before they act" (this is the predictive
  policing third rail in different words)
- Confident attribution of a *suspect's* identity (the audience
  will recognize false confidence as a tell)
- "Bias-free AI" (oversells; the bias mitigation is the audit
  trail, not the AI)

If a question in Q&A pushes toward any of these, deflect:

> "Great question. The agents don't make tactical or
> identification decisions — your officers and analysts do.
> What the agents do is make sure your officers are making
> those decisions with the full context the team has built up.
> Same decision authority, better information, and a complete
> audit trail of who made every call."

If a question gets specifically political (predictive policing,
civil liberties, bias), the deflection is:

> "I want to be straightforward about this. MemoryHub doesn't
> make predictions about individuals. It doesn't identify
> suspects. It doesn't do facial recognition. It holds the
> operational memory your team is already building informally
> — the working hypothesis on a search, the lessons learned
> from a prior incident, the soft preferences of an IC. Every
> action in that memory is attributed to a specific human.
> The audit trail is the accountability story. We're not
> trying to be a different kind of policing — we're trying to
> make the kind of policing your agencies already do work
> better."

## Open questions for rehearsal

1. **Visual style for the harness output**: same recommendation
   as the prior scripts — clean structured terminal output,
   distinct colors for `actor_id` vs `driver_id`, obvious
   quarantine notifications. For LEO specifically, the visual
   style should *not* look like an existing CAD or RMS
   interface — the audience will instantly compare it to
   whatever they already use, and we'll lose. Stay
   terminal-style.

2. **Synthetic environment details**: the demo references
   Daniel Voss, the Riverside District nightclub, Sergeant
   Hammond, Sergeant Chen, the cousin's residence, Marshall
   County. All synthetic. The recording must use
   obviously-fake values throughout so no audience member can
   mistake them for real production references or real cases.
   Cross-check the names against current news to make sure
   they don't accidentally match a real ongoing case.

3. **Booth presence**: the call to action assumes we have a
   physical booth at IACP. If we don't, the close needs to
   change.

4. **Q&A preparation**: the most likely Q&A questions for an
   IACP audience are:
   - "How does this integrate with our CAD / RMS / GIS?"
   - "What's the security and access control story for the
     memory layer itself?" (LEO audiences will worry about a
     new attack surface, especially one holding investigative
     memory)
   - "How is this different from a fusion center platform?"
   - "What about agencies that share information across
     jurisdictions — how does the project membership work
     across agencies?"
   - "How do you prevent bias from entering the memory?"
     (this is a real concern — the answer is that the audit
     trail makes every action attributable to a human, who is
     the source of any bias, and human oversight is the
     mitigation)
   - "How do you prevent the AI from inventing memories?"
     (the retrieval layer is search and recall, not
     generative — it only surfaces memories that were
     actually written by an authenticated actor, all in the
     audit trail)
   - "What does this cost?"
   - "How long does deployment take?"
   - "Who else is using this?"
   These should have prepared one-line answers.

5. **The "MemoryHub as attack surface" concern**: this is
   going to come up. LEO audiences will instantly recognize
   that an agent memory layer holding operational hypotheses,
   prior search lessons, and tribal knowledge is itself a
   high-value target. The prepared answer should cover:
   project-scope membership enforcement, audit trail
   integrity, RBAC on read/write, curation pipeline preventing
   third-party identification persistence, and the eventual
   LlamaStack telemetry integration for the audit layer.
   Pre-write a paragraph for this.

6. **The "what about civil liberties" concern**: this will come
   up at IACP either from an audience member or in the press
   coverage afterward. The pre-written answer needs to be
   clear, calm, and operationally grounded. Key points: (a)
   the agents don't identify suspects, (b) every action is
   attributed to a human in the audit trail, (c) MemoryHub
   isn't a new kind of policing, it's a memory layer for the
   policing your agencies already do, (d) the audit trail is
   the accountability and bias mitigation story.

7. **The "hallucinated incident" concern**: closely related to
   the cybersec script's version. LEO audiences are sensitive
   to LLMs making things up. The answer is: the retrieval
   layer is search and recall, not generative. Any
   "hallucinated" memory would have to have been written by an
   authenticated actor and be in the audit trail. Pre-write a
   one-liner.

8. **Recording session logistics**: when does the recording
   session happen? Who runs the harness? Where is it
   captured? Same as the prior scripts — the recording session
   is its own production task and needs its own scheduling and
   rehearsal time. Suggest blocking 2-3 hours for the
   recording session including reshoots, plus another 2-3
   hours for cut and edit.

9. **Live cluster Plan A readiness**: if going live, the
   cluster must be reachable, the agent fleet preloaded, the
   queries pre-baked, and a 1-keystroke trigger for each
   segment ready. Validate end-to-end at least the day before.

10. **The presenter's LEO credibility**: same concern as the
    clinical and cybersec scripts. If Wes (or whoever
    delivers this) is asked an operational question they
    can't answer, the right response is "I'm a technologist,
    not an operator — let me get our LEO advisor on that
    one." Pre-identify who that LEO advisor is and have them
    reachable during the demo session.

## Feature reference key

Each footnote below maps a moment in the demo to the MemoryHub
feature it demonstrates, the design doc that defines it, and the
GitHub issue (if any) tracking the implementation.

[^value-prop]: **The headline phrase**: "MemoryHub holds the
    context that makes tactical decisions go well." This is the
    one-line value prop that anchors the LEO scenario. It's not
    a feature — it's the framing that makes the features
    legible to a public safety audience. The phrase is the same
    shape as the clinical and cybersecurity versions with one
    word changed ("clinical" / "security" / "tactical"),
    demonstrating platform messaging consistency across
    domains.
    *Defined in*: `README.md`
    ("The value proposition in one sentence" section).
    *Visible in the demo*: title slide (Segment 1), explicit
    callout in Segments 3 and 5 after the killer moments,
    recap slide in Segment 8.

[^decision-support-boundary]: **The decision-support boundary
    positioning**: the explicit framing that MemoryHub is
    *complementary* to the existing LEO operational stack
    (CAD, RMS, GIS, LPR databases, real-time crime centers,
    fusion centers), not competitive with any of them. Public
    safety has a fragmented set of operational tools rather
    than a single dominant decision-support paradigm, but the
    boundary still matters — every audience member has
    investments in the existing tools.
    *Defined in*: `README.md`
    ("The decision-support boundary" section); reinforced in
    `fugitive-search-daniel-voss.md`
    ("MemoryHub vs. existing LEO systems" section).
    *Visible in the demo*: framing block in Segment 1, closing
    pitch in Segment 8.
    *Not a tracked feature* — this is positioning, not code.

[^humans-in-loop]: **Agents-support-humans framing**: every
    agent in the fleet is operated by a human practitioner in
    production. The demo presenter plays the role of the
    entire response team as a demo necessity, not as a product
    claim about autonomous tactical decisions. For LEO
    audiences specifically, this framing also includes
    explicit rejection of the LEO third rails: predictive
    policing, facial recognition, autonomous threat
    assessment, and automated suspect identification.
    *Defined in*: `../README.md` ("AI supports
    humans, it doesn't replace them" section);
    `README.md` ("The 'humans in
    production' framing" section); each role description in
    `fugitive-search-daniel-voss.md`
    has an "In production" sidebar.
    *Visible in the demo*: agent disclaimer in Segment 1,
    explicit reinforcement at apprehension in Segment 5,
    closing reinforcement in Segment 7; "what you cannot say"
    section is the verbal discipline that keeps this framing
    intact.
    *Not a tracked feature* — this is positioning, not code.

[^identity-triple]: **The owner/actor/driver identity model**:
    every memory operation involves three distinct identities.
    `owner_id` (who the memory belongs to, determines scope),
    `actor_id` (which agent performed the operation, always
    derived from authenticated identity), `driver_id` (on
    whose behalf, may equal actor_id for autonomous operation).
    *Defined in*: `../../../docs/identity-model/data-model.md` ("The
    triple: owner, actor, driver" section). Maps to RFC 8693
    token exchange semantics and FHIR Provenance (the FHIR
    mapping is healthcare-specific but the underlying model
    is domain-agnostic).
    *Tracked in*: GitHub issue #65 (schema migration adding
    `actor_id` and `driver_id` columns to MemoryNode), #66
    (plumbing through tools).
    *Visible in the demo*: agent registration in Segment 2
    (each agent's `actor_id` shown), audit trail queries in
    Segment 6 (both columns visible in result rows).

[^driver-id]: **Driver_id specifically — the on-whose-behalf
    concept**: identifies the principal an agent is acting
    for. Equals `actor_id` for fully autonomous operation;
    differs when the agent is being driven by a human
    practitioner on that human's behalf. Captured per-session
    (via `register_session(default_driver_id=...)`) or
    per-request (override parameter).
    *Defined in*: `../../../docs/identity-model/data-model.md` ("Tool
    API changes" section).
    *Tracked in*: GitHub issues #65, #66.
    *Visible in the demo*: shift handoff moment in Segment 4
    (driver changes from Hammond to Chen while actor stays
    constant), audit query 2 in Segment 6 ("everything done
    on behalf of Sergeant Hammond").

[^role-vs-person]: **Role-as-actor + person-as-driver
    distinction**: in LEO specifically, this is the IC shift
    handoff and on-call rotation pattern. A role like
    "Incident Commander" persists across shift handoffs as a
    stable `actor_id`; the human currently in the role is a
    rotating `driver_id`. The role's accumulated operational
    picture survives every handoff, and the audit trail
    captures both "what does the IC role know about this
    search?" and "who was IC at the time of this decision?"
    as separately answerable questions.
    *Defined in*: `../../../docs/identity-model/data-model.md`
    (implicitly, via the actor/driver split); the IC shift
    handoff is the LEO parallel to the clinical Charge Nurse
    handoff and the cybersec on-call rotation.
    *Tracked in*: GitHub issues #65, #66.
    *Visible in the demo*: IC shift handoff moment in Segment 4
    is the central demonstration; audit query 1 in Segment 6
    payoffs the concept by showing the role's actions
    spanning both shifts.

[^project-scope]: **Project-scope membership enforcement**:
    agents are members of specific projects (in the demo,
    `voss-search-2024`). Project-scope memories are
    readable/writable only by members. For multi-agency
    operations, this is how the team's shared memory stays
    bounded to the participants of the specific search and
    doesn't bleed across unrelated investigations.
    *Defined in*: `../../../docs/identity-model/authorization.md`
    ("Project membership enforcement (critical path)"
    section).
    *Tracked in*: GitHub issue #64 (the critical-path
    implementation work).
    *Visible in the demo*: agent registration in Segment 2
    (project membership confirmed); every project-scope
    memory write/read in Segments 3-7 implicitly demonstrates
    the enforcement.

[^cross-incident]: **Cross-incident learning** — the central
    value-prop demonstration for the public safety scenario,
    with three distinct manifestations:
    (1) **Pattern recognition**: when the Pattern Analyst
    agent surfaces the PS-2024-031 memory in Segment 3,
    allowing the team to recognize a similar profile from a
    prior search and prioritize the cousin's residence four
    hours before the subject is observed there.
    (2) **Negative findings discipline**: when the Riverside
    clear from the previous shift in Segment 4 prevents
    re-tasking after the IC handoff, freeing resources that
    are available later.
    (3) **Multi-source convergence**: when the doorbell hit
    at 06:42 in Segment 5 links to the four-hour-old working
    hypothesis in seconds, enabling rapid pre-positioning of
    tactical assets.
    All three are forms of "what we've already learned that's
    relevant now," and they all live in the same memory
    category.
    *Defined in*: `README.md`
    ("What MemoryHub holds in this scenario");
    `fugitive-search-daniel-voss.md`
    (touchpoints 1-3, 6-7).
    *Tracked in*: emerges from project-scope membership (#64),
    schema (#65), tool plumbing (#66). No dedicated issue —
    this is the application-level pattern that the underlying
    features enable.
    *Visible in the demo*: the killer moments in Segments 3
    and 5; negative findings persistence in Segment 4;
    explicit post-incident learning capture in Segment 7.

[^narrative-context]: **Narrative context memory category**:
    the soft, unstructured operational knowledge that doesn't
    fit in CAD entries, RMS records, or GIS attributes. The
    working hypothesis in narrative form, the rationale for
    geographic prioritization, the team's interpretation of
    incoming evidence, the post-incident lessons in
    practitioner language.
    *Defined in*: `README.md`
    ("What MemoryHub holds in this scenario" — first and
    second bullets);
    `fugitive-search-daniel-voss.md`
    (multiple touchpoints).
    *Tracked in*: not a discrete feature — emerges from
    generic `write_memory` + project-scope. The *category* is
    a positioning choice; the implementation is just memory
    storage.
    *Visible in the demo*: the working hypothesis throughout
    Segments 2-5; post-incident lesson capture in Segment 7.

[^tribal-knowledge]: **Practitioner tribal knowledge memory
    category**: the practices an agency or team has developed
    that aren't formal SOP but are how the team actually
    works. The "IC Sergeant Hammond's tip queue preference"
    in this scenario is the canonical example. This kind of
    knowledge lives in senior practitioners' heads and walks
    out the door when they retire — a real attrition pain
    point in LEO agencies, where experienced commanders are
    increasingly hard to retain.
    *Defined in*: `README.md`
    ("What MemoryHub holds in this scenario" — fifth
    bullet);
    `fugitive-search-daniel-voss.md`
    (touchpoint 4).
    *Tracked in*: not a discrete feature — same emergence as
    narrative context. Category positioning, not separate
    code.
    *Visible in the demo*: the IC preference filter being
    applied by the Tip Line Triage agent in Segment 3.

[^contradiction]: **Contradiction detection** via the
    `report_contradiction` tool. When one agent's evidence
    conflicts with another's, an agent surfaces the conflict
    explicitly. Both memories are preserved; the
    contradiction relationship is queryable; the IC uses the
    surfaced conflict to make an explicit adjudication
    decision rather than letting one view silently win. In
    LEO specifically, the most natural contradiction surfaces
    are sensor disagreements (LPR hit vs. tip caller
    location) and analyst disagreements (Pattern Analyst's
    behavioral hypothesis vs. Geographic Analyst's physical
    constraint check).
    *Defined in*: `fugitive-search-daniel-voss.md`
    ("Contradiction moments" section). The
    `report_contradiction` tool already exists in the MCP
    server; this is reuse, not new feature work.
    *Tracked in*: existing tool. Demo scenario validation
    needed before this lands cleanly.
    *Visible in the demo*: LPR-vs-tip contradiction in
    Segment 4.

[^operational-memory]: **Agent-operational memory category**:
    the agent fleet writes memories about *itself* —
    operational lessons it has learned about how it works.
    No human writes these; no human reads them directly.
    They're the AI fleet's self-correction layer. In LEO,
    examples include false-positive filters the fleet has
    derived from prior operations (the Drone agent's
    cold-weather thermal-deer rule).
    *Defined in*: `README.md`
    ("What MemoryHub holds in this scenario" — sixth
    bullet);
    `fugitive-search-daniel-voss.md`
    (touchpoint 5).
    *Tracked in*: not a discrete feature — emerges from
    `write_memory` + scope/owner conventions. The *category*
    is novel positioning.
    *Visible in the demo*: brief mention in Segment 4 (the
    Drone agent's cold-weather thermal rule applied
    automatically based on a self-written prior memory).
    Most novel demo moment, but at risk of confusing the
    audience — frame carefully.

[^data-curation]: **Sensitive-data curation pipeline**: when
    an agent attempts to write a memory containing sensitive
    data (uninvolved third-party identifying information,
    confidential informant identities, source/method exposure,
    civilian PII), the curation pipeline catches the
    attempted write and quarantines it before persistence.
    The agent then reformulates the memory to preserve
    operational meaning without the sensitive details. Note:
    the pipeline itself is the same code as the healthcare
    PHI/PII pipeline and the cybersec credential pipeline,
    but the *patterns* are domain-specific. The LEO patterns
    (third-party identification, CI exposure, source/method
    redaction) are not yet built — they would be a future
    issue, separate from #68 (healthcare PHI patterns).
    *Defined in*:
    `fugitive-search-daniel-voss.md`
    ("Sensitive-data moments" section). The underlying
    pipeline is documented in
    `../clinical/demo-plan.md`.
    *Tracked in*: pipeline stub via #68 for healthcare; LEO
    patterns are a future issue (not yet filed).
    *Visible in the demo*: third-party identification
    quarantine in Segment 4 (Camera Network attempts to write
    an uninvolved woman's details); CI source quarantine in
    Segment 5 (Tip Line attempts to write a CI by name and
    handler).

[^audit]: **Audit log**: every memory operation (write, read,
    update, delete, contradiction report, quarantine) is
    captured by `audit.record_event(...)` with both
    `actor_id` and `driver_id` recorded. For the demo, the
    persistence layer is a stub that writes structured log
    lines; future work will route through LlamaStack
    telemetry (which RHOAI ships natively as a Tech Preview,
    avoiding the need to build a custom audit log).
    *Defined in*: `../../../docs/identity-model/authorization.md`
    ("Audit logging — stub now, persistence later" section).
    *Tracked in*: GitHub issue #67 (audit logging stub
    interface), #70 (persistent audit log via LlamaStack
    telemetry).
    *Visible in the demo*: quarantine attempts visible in
    audit in Segments 4 and 5; audit queries are the
    centerpiece of Segment 6.

[^cli-provisioning]: **Agent generation CLI**: a static
    code-gen tool that takes a fleet manifest YAML and
    produces Kubernetes Secrets, the users ConfigMap, and
    the harness manifest needed to deploy and identify the
    demo's agent fleet. The CLI is the source of the ten LEO
    agents seen in the demo.
    *Defined in*: `../../../docs/identity-model/cli-requirements.md`
    (the full requirements doc for the CLI).
    *Tracked in*: GitHub issue #69 (build agent generation
    CLI for demo fleet provisioning).
    *Visible in the demo*: implicit in the agent fleet
    startup in Segment 2. Not directly demoed, but the
    existence of the fleet depends on it. Worth a one-liner
    mention if there's time and the audience is operationally
    curious ("the fleet you see was provisioned from a
    single YAML manifest, the same way you'd provision a
    response team for a new mutual aid arrangement").
