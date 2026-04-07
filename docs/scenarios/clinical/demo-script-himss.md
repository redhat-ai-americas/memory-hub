# HIMSS Demo Script — Stroke Rehab Scenario

A 10-15 minute presentation outline for delivering the stroke rehab
scenario to a HIMSS-style audience (healthcare CIOs, CMIOs, clinical
informatics leaders, hospital IT, healthcare technology vendors).

This is an **outline** with talking points, not a word-for-word script.
The presenter ad-libs the actual language; the script tells you what
to cover, in what order, and which agent fleet milestones to highlight
when.

The presenter is doing live voiceover. Behind the voiceover plays a
recorded session of the agent fleet running on a real cluster, edited
into clips that match the segment structure below. The presenter plays
the role of the entire care team in the recording — this is a demo
necessity, and the script repeatedly reinforces that in production
every agent is operated by a human clinician.

Throughout the script, **footnote markers** like `[^cross-encounter]`
mark the specific MemoryHub feature each statement, segment, or
moment demonstrates. The full feature reference key is at the bottom
of the document, with each footnote linking to the relevant design
doc and GitHub issue.

## Audience and framing

**Who they are**: HIMSS attendees are healthcare IT decision-makers
and influencers. They have CDS deployed (or are buying it), they have
EHR (almost certainly Epic or Cerner), they understand HL7 and FHIR,
and they spend serious money on healthcare information systems. They
are deeply skeptical of "AI replaces clinicians" pitches. They are
also exhausted by "AI in healthcare" hype that doesn't differentiate
itself from the last hundred AI-in-healthcare pitches they've heard.

**What they need to hear in the first 60 seconds**:

1. This is not another CDS pitch.[^cds-boundary]
2. This is not "AI replaces clinicians."[^humans-in-loop]
3. This is something they don't already have in their stack.
4. There's a specific clinical workflow being shown (not a generic
   abstraction).

**What they need to leave with**:

1. The phrase: "MemoryHub holds the context that makes clinical
   decisions go well."[^value-prop]
2. A clear understanding of the CDS boundary — MemoryHub sits
   alongside CDS, doesn't compete with it.[^cds-boundary]
3. The cross-encounter narrative continuity moment as the most
   memorable demonstration of value.[^cross-encounter]
4. The audit-trail-with-driver-id moment as the compliance
   hook.[^audit][^driver-id]
5. Confidence that this is real software running real agents on
   real infrastructure, not a vaporware mockup.

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
   end through the full scenario in real time. This is the source
   material; clips get cut from it in post.
2. The recorded session does not need to match the demo's 13-minute
   target — it can be 30 minutes long if the agent fleet runs
   slowly. Pacing happens at the editing stage.
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
   needs to be able to ad-lib, respond to audience cues, and adjust
   pacing in real time.

### Visual style for the recording

- Clean structured terminal output (not a UI mockup) so the audience
  sees the real thing
- Role labels prominent — "Inpatient Nurse" not "agent-7"
- `actor_id` and `driver_id` rendered in distinct colors so the
  identity distinction is visible from the back of the
  room[^identity-triple][^driver-id]
- PHI quarantine notifications must be impossible to miss (red,
  bordered, animated, ideally all three)[^phi-curation]
- Contradiction markers visually distinct from normal memory
  writes[^contradiction]
- Resolution: at minimum 1920x1080, ideally 2560x1440 or higher if
  conference projection supports it
- Terminal font: large enough to read from the back row of a
  conference session room (think 18pt+ at recording resolution)

### Live cluster fallback

If WiFi at the conference is observably reliable in the 30 minutes
before the talk, live execution becomes Plan A and recorded clips
become Plan B. The decision happens just before the session starts.
**The recorded clips must always be ready as the default**, not as a
last-minute scramble. Test the playback path on the conference's
actual A/V setup at least 15 minutes before showtime regardless of
which plan is in effect.

The harness used for the live execution path is the same one that
generated the recording — there are no two harnesses to maintain.
Switching from recorded to live means starting the same harness,
pointed at a real cluster with the agent fleet preloaded, instead of
playing back the saved video.

## Time budget

Total: 13 minutes (gives you 2-minute cushion against the 15-minute
hard cap; can compress to 10 minutes by trimming Phase 5/6 walkthrough
if running long).

| Segment | Time | What's on screen |
|---|---|---|
| 1. Opening hook and framing | 1:30 | Title slide → patient archetype slide |
| 2. Meet the patient and team | 1:30 | Marcus Reeves intro → agent fleet startup |
| 3. Phases 1-2: acute hospital → VA admission | 2:00 | Recorded clip: agents registering, transfer handoff, goals memory |
| 4. Phase 3: inpatient rehab + shift change resilience | 3:00 | Recorded clip: daily rounds, cane contradiction, tribal knowledge memory |
| 5. Phases 4-5: discharge and outpatient continuity | 2:00 | Recorded clip: cross-care-setting handoff, the killer demo moment |
| 6. The audit trail and driver_id moment | 1:30 | Recorded clip: audit query showing actor/driver split |
| 7. Phase 6 + plateau contradiction | 0:30 | Brief PCP scene, contradiction-resolved moment |
| 8. Closing pitch | 1:00 | Recap slide → call to action |

Buffer: 30 seconds for transitions and audience reactions.

## Segment 1 — Opening hook and framing (1:30)

### What's on screen

Title slide: **"MemoryHub: the context that makes clinical decisions go well."**[^value-prop]

Below the phrase, a small subtitle: *"A demonstration with the
VA/DoD Stroke Rehabilitation Clinical Practice Guideline."*

### Talking points

**The hook (30 seconds)**: Open with a relatable handoff problem.
Something like:

> "Every nurse, every therapist, every case manager in this room has
> had this moment. You're picking up a patient from a colleague who
> is exhausted at the end of a shift. There's a structured handoff
> sheet, there's the chart, and there's everything *else* — the
> things your colleague learned about this patient that aren't in
> the chart and won't fit on the handoff sheet. Sometimes you get
> those things in the hallway conversation. Sometimes you don't.
> When you don't, the patient pays for it."

**The framing (30 seconds)**: Establish what we're showing and what
we're NOT showing.[^cds-boundary]

> "What I'm about to show you is not another clinical decision
> support system. Your CDS makes the clinical recommendations —
> drug interactions, dosing, evidence-based alerts — and it's
> doing its job. What you're about to see lives *alongside* your
> CDS. It holds what CDS doesn't: the soft narrative context, the
> team's tribal knowledge, the cross-handoff continuity, the
> things that determine whether the right clinical decision lands
> well or poorly."

**The agent disclaimer (30 seconds)**: Get this in early. Don't let
the audience misread the demo.[^humans-in-loop]

> "I'll be playing the role of the entire care team during this
> demo. Every agent you see is operated by a human clinician in
> production. The Inpatient Nurse agent? In production, that's
> the inpatient nurse on shift, chatting with her team's shared
> memory the way she'd consult an experienced colleague. The PT
> agent is a working PT. The case manager agent is a working
> case manager. **These agents help clinicians; they don't replace
> them.** When you see me typing, picture the clinician you know
> would be doing that job in your hospital."

### Milestones demonstrated

None yet — this is setup. But you've planted three things:

- The phrase[^value-prop]
- The CDS boundary[^cds-boundary]
- The agents-support-humans framing[^humans-in-loop]

### Harness operator notes / shot list

- No harness footage in this segment. Stay on slides.
- Have the recorded clip queued up to begin on the cue at the
  start of Segment 2.

## Segment 2 — Meet the patient and team (1:30)

### What's on screen

Slide: Marcus Reeves patient archetype, with photo placeholder, age,
key history, and his stated goals listed prominently.

Then transition to the recorded clip showing the agent fleet
registering with MemoryHub.[^identity-triple][^cli-provisioning]

### Talking points

**Patient introduction (45 seconds)**: Make Marcus a person, not a
case study.

> "This is Marcus Reeves. He's 64. He's a retired postal worker
> and a Vietnam-era Marine. He lives at home with his wife in a
> one-story house. In his retirement he coaches his grandson's
> little league team in the spring and does woodworking in his
> garage workshop the rest of the year. This morning, his wife
> finds him slumped in his chair at breakfast with slurred speech
> and unable to lift his right arm. She calls 911."
>
> "Over the next several months, Marcus is going to pass through
> four different care settings: a community hospital ED, a VA
> inpatient rehabilitation unit, outpatient therapy, and back to
> his primary care doctor for long-term management. He's going to
> see roughly ten different clinical roles. And his goals — coach
> little league again, drive again, walk independently with a cane
> — are going to require all of those people to actually
> understand what *Marcus* wants, not just what 'a stroke patient'
> typically wants."

**Why this scenario (15 seconds)**:

> "Everything I'm about to show you is built around the VA/DoD
> Stroke Rehabilitation Clinical Practice Guideline, version 5,
> published in 2024. We're not making up clinical practice. We're
> showing how a real care team coordinated around a real guideline
> can use shared memory to actually deliver on the patient's
> goals."

**Agent fleet startup (30 seconds)**: Cue the recorded clip. Show
the ten agents registering with MemoryHub.[^identity-triple][^project-scope]

> "On screen now you'll see the agent fleet starting up. Each
> agent is registering with MemoryHub and being authenticated.
> Watch the role names — Acute Care Hospitalist, VA Physiatrist,
> Inpatient Nurse, PT, OT, SLP, Behavioral Health, Pharmacist,
> Case Manager, Primary Care Provider. Ten roles. In production,
> each one is the interface a working clinician uses to chat with
> the team's shared memory."

### Milestones demonstrated

- **Identity model**[^identity-triple]: ten agents come online,
  each with its own identity. The recorded clip shows each agent's
  `actor_id` as it registers.
- **Project membership**[^project-scope]: all ten agents are
  members of a shared project (`marcus-reeves-rehab`). The audit
  trail will hang off this project membership later.
- **Fleet provisioning**[^cli-provisioning]: implicit — the fleet
  was generated from a manifest by the agent generation CLI.

### Harness operator notes / shot list

- **Capture**: each agent's `register_session` call landing in the
  harness output, with the role name and `actor_id` clearly
  visible. Hold for 1-2 seconds per agent so the audience can read
  the role names.
- **Capture**: a confirmation line showing all ten agents are
  members of the `marcus-reeves-rehab` project.
- The driver_id at this point is set to the demo presenter (e.g.,
  `wjackson-himss-demo-1`). Make sure it's visible in the
  registration output — it will be referenced later in the audit
  trail segment.[^driver-id]

## Segment 3 — Phases 1-2: acute hospital → VA admission (2:00)

### What's on screen

Recorded clip advancing through Phase 1 (community hospital) and
Phase 2 (VA admission). Specific moments to make visible:

- Acute Care Hospitalist agent writing the transfer summary
  memory[^cross-system]
- VA Physiatrist and Case Manager activating on patient arrival
- Case Manager writing the patient-stated goals
  memory[^narrative-context][^provenance]
- The PHI quarantine moment when the goals memory leaks
  identifiers[^phi-curation]

### Talking points

**The handoff that doesn't usually work (30 seconds)**:[^cross-system]

> "Here we are at the community hospital. The hospitalist has
> stabilized Marcus and is preparing to transfer him to the VA
> medical center for inpatient rehab. You all know what this
> handoff usually looks like in real life — a discharge summary
> in HL7, maybe a phone call between case managers if you're
> lucky, and a *lot* of context that just doesn't make the
> trip."
>
> "What's happening on screen right now: the Acute Care
> Hospitalist agent is writing a memory that the receiving VA
> team will read at admission. It's not replacing the discharge
> summary — that's still in the EHR, that still moves through
> your interface engine. This memory holds what *won't* fit in
> the discharge summary."

**The patient goals moment (45 seconds)**: This is where the demo
starts to land emotionally.[^narrative-context][^provenance]

> "Now we're at the VA. Marcus has been admitted, and the case
> manager is having the goals conversation with Marcus and his
> wife. Watch what's happening on screen — the Case Manager
> agent is capturing the patient's stated goals in his own
> words, with a provenance branch citing the admission
> conversation."
>
> "Notice the goals: walk with a cane, drive again, coach little
> league. Now I want you to think about your structured EHR
> goal fields for a stroke patient. They probably look like
> 'mobility: independent ambulation with assistive device' and
> 'self-care: independent in ADLs.' Those structured fields are
> *correct*, but they don't tell the next clinician on shift
> *why*. They don't carry the meaning. The PT who reads only
> the structured field plans gait training that's clinically
> appropriate but generic. The PT who reads this *memory* knows
> to frame the gait drills around walking to the pitcher's
> mound."

**The PHI moment (45 seconds)**: This is where you show governance
working.[^phi-curation][^audit]

> "Now watch this. The agent is about to try writing the goals
> memory exactly as the patient said it. He said 'I want to
> drive my grandson Tyler to little league practice in
> Manassas.' The agent picks up that language and tries to
> persist it."
>
> "MemoryHub catches it. Patient first name + grandson's first
> name + city — that's a quasi-identifier triple. The curation
> pipeline quarantines the memory before it's persisted. You're
> seeing the quarantine notification on screen now. The agent
> reformulates the memory to preserve the *meaning* — patient
> wants to return to driving family members to recreational
> activities, identifies coaching his grandson's youth sports
> team as a key motivator — without the identifying details."
>
> "The clinical content is preserved. The re-identification risk
> is removed. And — this is critical — the original quarantined
> attempt is in the audit trail. Your compliance officer can
> reconstruct exactly what was attempted, when, and what
> happened."

### Milestones demonstrated

- **Cross-system handoff via memory**[^cross-system] (acute hospital
  → VA)
- **Project-scope writes**[^project-scope] (Case Manager writes to
  the shared patient project)
- **PHI quarantine** with curation pipeline[^phi-curation]
- **Audit trail of the quarantined attempt**[^audit]
- **Provenance branches**[^provenance] (the goals memory has a
  branch citing the conversation source)
- **Patient narrative context category**[^narrative-context] (the
  goals memory is a narrative-context memory, distinct from
  structured EHR goal fields)

### Harness operator notes / shot list

- **Capture**: the Acute Care Hospitalist's `write_memory` call
  with the transfer summary visible.
- **Capture**: the Case Manager's `write_memory` call for the
  patient goals, with the `provenance` branch visible alongside.
  Pause briefly so the audience can read the goal text.
- **Capture both halves of the PHI moment**: (1) the rejected
  attempt with the original "Marcus + Tyler + Manassas" text,
  visibly marked as quarantined, and (2) the rewritten,
  successful version. Side-by-side framing if possible.
- The quarantine notification needs to be visually obvious from
  the back of the room — red border, animation, both. This is
  one of the most important visual moments in the entire demo.
- **Capture**: a brief audit log entry showing the quarantined
  attempt and the rewrite, both attributed to the same actor.

## Segment 4 — Phase 3: inpatient rehab + shift change resilience (3:00)

### What's on screen

The longest segment. Multiple moments compressed into a fast-paced
walkthrough of the inpatient rehab phase. Key beats:

- Daily rounds — multiple agents reading and writing
- The Charge Nurse role passing across shifts (different drivers,
  same actor)[^role-vs-person][^driver-id]
- A tribal knowledge memory being read (Dr. Patel's SSRI
  preference)[^tribal-knowledge]
- A patient-narrative memory being written (the call light
  observation)[^narrative-context]
- The PT-vs-OT cane contradiction[^contradiction]
- Brief mention of Behavioral Health being consulted in week 2

### Talking points

**Daily rhythm (30 seconds)**:

> "Skipping ahead a few days. Marcus is in the daily rhythm of
> inpatient rehab. PT in the morning, OT in the afternoon, SLP
> session for both the aphasia work and the dysphagia work,
> nursing care across the 24-hour shift cycle. What you're seeing
> on screen is the agent fleet during a typical day — agents
> reading and writing to the shared memory as the team learns
> more about Marcus and what works for him."

**The shift change moment (1:00)**: This is where you make the
role-vs-person distinction land.[^role-vs-person][^driver-id][^audit]

> "Watch this transition right here. It's 7 PM, end of day shift.
> The Charge Nurse role is handing off from Nurse Williams to
> Nurse Rodriguez. In the harness, the Charge Nurse agent stays
> the same — same actor identity, same accumulated memory of the
> day's events. What changes is the *driver* — the human on
> whose behalf the agent is now acting. Nurse Williams's session
> ends, Nurse Rodriguez's session begins, and the agent's
> driver_id updates to reflect that."
>
> "This is intentional and it matters. In production, your
> nursing staff turns over every 8 or 12 hours. The role
> persists across shifts; the people change. MemoryHub's identity
> model captures that distinction natively. The role has
> continuity of memory; the audit trail captures which specific
> human was driving the role at any given moment. Both questions
> matter — 'what does the Charge Nurse role know?' and 'who was
> Charge Nurse on Tuesday night at 11:47 PM?' — and MemoryHub
> answers both."
>
> "Why does this matter beyond compliance? Because when Marcus
> develops a new symptom at 11:47 PM on Tuesday, the night
> Charge Nurse agent has the complete context the day Charge
> Nurse agent built up — every observation, every nuance, every
> 'he won't use the call light' note — without any handoff loss.
> The shift changed; the institutional memory didn't."

**The tribal knowledge moment (45 seconds)**:[^tribal-knowledge][^cds-boundary]

> "Now in week 2, something happens that's clinically common.
> Marcus develops post-stroke depression. Not unusual — the
> guideline expects this. The team consults Behavioral Health.
> Watch what the Behavioral Health agent does first."
>
> "It's reading a memory that was written months ago by Dr.
> Patel, the unit's attending physiatrist. Here's what the
> memory says: 'On this unit, we initiate SSRIs over SNRIs for
> post-stroke depression in patients with hypertension. Reasoning:
> SNRIs can elevate blood pressure and most of our post-stroke
> patients are on antihypertensive regimens we don't want to
> fight. Not formal protocol — clinical judgment learned from
> this population.'"
>
> "This is not in your CDS. It's not in your formulary. It's
> not in any guideline. It's the kind of soft clinical wisdom
> the unit has developed over years of treating this specific
> patient population. In current practice, this knowledge lives
> in Dr. Patel's head, and when Dr. Patel goes on vacation or
> retires, it walks out the door with her. Here, it's
> persistent. The Behavioral Health agent reads it before
> recommending an antidepressant, and the recommendation lands
> consistently with team practice."

**The cane contradiction (45 seconds)**: This is your contradiction
detection moment.[^contradiction]

> "Earlier in the week, the PT agent wrote this memory: 'Patient
> seemed hesitant about using the cane during gait training
> today. Body language read like reluctance. Might be a
> confidence issue — OT might want to address it.'"
>
> "Two days later, the OT had a different conversation with
> Marcus during ADL session. Here's what she found: 'He's not
> hesitant about using the cane functionally. He's worried about
> how he'll look at his grandson's ballgames using a cane. It's
> an emotional issue tied to his identity as a coach, not a
> functional acceptance issue. Different intervention needed:
> peer support and a conversation about how other coaches manage
> with assistive devices, not more confidence-building during
> gait training.'"
>
> "OT's memory contradicts PT's interpretation. Watch what
> happens — OT calls report_contradiction. MemoryHub surfaces
> the conflict to the team. The morning huddle reads both
> memories side by side. The plan adjusts. PT continues gait
> training normally. OT incorporates the emotional dimension
> into ADL work. Case Manager looks into peer support resources.
> Notice that PT's original observation isn't *deleted* — it's
> preserved in the contradiction history. PT wasn't *wrong* to
> notice the hesitancy. She was just interpreting it through one
> lens. OT's conversation revealed a different lens. Both
> observations matter."

### Milestones demonstrated

- **Driver_id distinction**[^driver-id]: same role, different
  humans across shifts. The role persists; the audit trail
  captures who was driving when.
- **Role-vs-person identity model**[^role-vs-person]: actor (the
  Charge Nurse role) is stable across shift changes; driver
  (the human on shift) changes per session.
- **Project-scope reads**[^project-scope]: agents reading from the
  team's shared memory.
- **Tribal knowledge memory**[^tribal-knowledge] (the SSRI
  preference).
- **Patient narrative context**[^narrative-context] (call light
  observation, mentioned in passing).
- **Contradiction detection**[^contradiction]: report_contradiction
  in action.
- **Contradiction resolution flow**[^contradiction]: how the team
  uses the surfaced conflict.

### Harness operator notes / shot list

- **The shift change moment must be visually obvious in the
  recording.** Show the `driver_id` value changing in the harness
  output while the `actor_id` stays constant. If the harness
  doesn't natively highlight this, add a visible callout in
  post-production editing.
- **Capture**: Dr. Patel's tribal knowledge memory being read by
  the Behavioral Health agent, with the full memory text visible
  on screen long enough to read in the back row.
- **Capture both memories of the cane contradiction**: PT's
  original interpretation memory and OT's contradicting memory.
  When `report_contradiction` is called, the relationship between
  the two memories should be visually rendered. Side-by-side
  display preferred.
- The night shift Charge Nurse reading the day shift Charge
  Nurse's accumulated memory needs at least one visible
  `read_memory` call in the recording so the cross-shift continuity
  is concrete, not abstract.

## Segment 5 — Phases 4-5: discharge and outpatient continuity (2:00)

### What's on screen

Compressed walkthrough of discharge and outpatient. The single most
important moment in the entire demo lives here: the cross-care-setting
narrative continuity moment.[^cross-encounter]

### Talking points

**Discharge (30 seconds)**:[^narrative-context][^cds-boundary]

> "Marcus discharges home in week 3. The handoff to outpatient is
> coordinated through the Case Manager agent. Pharmacy reconciles
> medications — and I want to be clear here: the *structured*
> medication reconciliation is happening in your CDS, not in
> MemoryHub. What's happening in MemoryHub is the *narrative
> context* around the conversation. Marcus mentioned during the
> reconciliation that he hated gabapentin in the past because of
> the cognitive side effects. That's not in the formulary, it's
> not in the allergy list, but if neuropathic pain develops
> post-stroke, the next prescriber needs to know."

**The killer moment (1:00)**: This is the single most important
moment of the demo. Slow down. Make it land.[^cross-encounter][^narrative-context]

> "Six weeks later. Marcus is at his first outpatient PT session.
> Different building, different facility, different PT, different
> EHR module if you're being honest about how your environment
> actually works. The outpatient PT has Marcus's structured
> discharge summary — assessment scores, recommendations,
> outpatient frequency. She has done this a thousand times."
>
> "Here's what she usually does: she spends the first three or
> four sessions getting to know the patient. What motivates him?
> What bores him? What works? What doesn't? It's good clinical
> care, but it's also re-derivation. Everything she's learning,
> the inpatient PT already knew."
>
> "Watch the screen. Before her first session, the outpatient PT
> agent reads a memory written by the inpatient PT three weeks
> earlier. Here's what it says: 'Patient does best with
> task-specific gait training when the task is framed around
> little league coaching — walk to the pitcher's mound and back.
> Generic gait drills bore him and he disengages. Outpatient PT
> should know this — same patient, same motivation dynamics.'"
>
> "She walks into the session, opens with task-specific training
> framed around coaching activities, and Marcus engages
> immediately. Three sessions of re-derivation? Skipped. He's
> further along in his recovery at week 6 than he would have
> been in current practice."
>
> "*This* is what we mean by the context that makes clinical
> decisions go well. Your discharge summary captured the
> structured plan. MemoryHub captured what the inpatient team
> *learned* about Marcus that the structured plan can't
> carry."[^value-prop]

**Brief mention of agent-operational memory (30 seconds)**:[^operational-memory]

> "One quick thing to point out before we move on. Watch the
> Inpatient Nurse agent — it just read a memory it wrote *to
> itself* a few weeks ago. The memory says 'when the SLP agent
> updates the dysphagia diet trajectory, the update lands at
> approximately 7 AM, not 6:30 AM as I was originally reading.
> Adjust handoff read schedule accordingly to avoid stale diet
> information at start of shift.'"
>
> "That's the agent fleet learning about *itself*. No human
> wrote that memory. No human reads it directly. It's the
> AI fleet's operational memory — the kind of self-correction
> that human teams develop naturally over time, and that an
> agent fleet needs its own memory layer to develop, too."

### Milestones demonstrated

- **Cross-care-setting narrative continuity**[^cross-encounter]
  (the killer moment)
- **Pharmacy narrative context**[^narrative-context] (separate
  from CDS med rec)[^cds-boundary]
- **Agent-operational memory**[^operational-memory] (the
  self-written memory)
- **Project-scope reads across handoffs**[^project-scope]
- **Value prop landing**[^value-prop]: this is the segment where
  the headline phrase gets its strongest demonstration

### Harness operator notes / shot list

- **The killer moment is the most important shot in the entire
  recording.** The outpatient PT agent's `read_memory` call must
  be visible, the memory text must be on screen, and the camera
  needs to hold on it for at least 4 seconds — long enough that
  even the slowest reader in the audience can take it in. Don't
  rush this.
- **Capture**: the inpatient PT memory being written in week 3,
  earlier in the recording. The audience will only see the
  outpatient read in this segment, but the recording needs to
  contain the original write so the editing process can show a
  brief flashback or overlay if you want to.
- **Capture**: the agent-operational memory being read by the
  Inpatient Nurse agent. The audience needs to see that no human
  is in the loop for this read — the agent is consulting its own
  prior self-written memory.

## Segment 6 — The audit trail and driver_id moment (1:30)

### What's on screen

The recorded clip shifts to a query mode. Two queries are run:

1. "Show me everything the Charge Nurse agent did during Tuesday's
   night shift."
2. "Show me everything done on behalf of Nurse Williams across the
   entire fleet."

The two queries return different result sets, both correctly
attributed.[^audit][^driver-id][^role-vs-person]

### Talking points

**The compliance hook (45 seconds)**: Healthcare IT audiences love
audit. Lean in.[^audit][^identity-triple][^driver-id]

> "Let me switch from the clinical narrative for a moment and
> talk to the compliance officers in the room. Everything we
> just walked through — every memory written, every memory read,
> every contradiction reported, every PHI quarantine — is
> recorded in MemoryHub's audit log. Every operation has two
> identities attached: the *actor* (which agent did it) and the
> *driver* (on whose behalf it was done)."
>
> "This is important because — as I showed you with the shift
> change earlier — the role-acting and the human-on-whose-behalf
> are different things. And in healthcare, both questions
> matter."

**Query 1 (20 seconds)**:[^role-vs-person][^audit]

> "Watch this. I'm going to ask: 'Show me everything the Charge
> Nurse agent did during Tuesday night shift.' On screen now
> you're seeing every action that role took during those 12
> hours — across both Nurse Williams's shift and Nurse
> Rodriguez's shift, because the role spans the boundary."

**Query 2 (20 seconds)**:[^driver-id][^audit]

> "Now I'm going to ask a different question: 'Show me everything
> done on behalf of Nurse Williams across the entire fleet of
> agents.' Different result set. This shows me what Nurse
> Williams was driving — not just the Charge Nurse role, but any
> other role she touched during her shift."

**The point landing (5 seconds)**:

> "Both questions are answerable in seconds. In your current
> world, that's a multi-day audit project."

### Milestones demonstrated

- **Audit log with actor/driver split**[^audit][^identity-triple]
- **Driver_id queryability**[^driver-id] — both directions (by
  role, by human-on-whose-behalf)
- **Role-vs-person identity model in action**[^role-vs-person]
- **Compliance use case**

### Harness operator notes / shot list

- **Capture both queries running** with their distinct result
  sets visible. This is one of the few segments where the
  on-screen content is dense — the audience needs to see actual
  rows of audit data, not just a summary.
- Result rows must clearly show the `actor_id` and `driver_id`
  columns so the distinction between the two queries is
  visible.[^identity-triple][^driver-id]
- For the recording: ensure the queries are pre-baked and
  produce well-formatted output, not raw JSON dumps. A
  three-column table (timestamp, actor, driver) is the right
  shape.
- **If running live as Plan A**: the two queries must be in a
  prepared script that the presenter triggers with a single
  keystroke each, so there's no typing latency on stage.

## Segment 7 — Phase 6 and the plateau contradiction (0:30)

### What's on screen

A brief moment from the long-term primary care phase. The PCP
reading a memory from outpatient about the patient's progress, and
the resolved-plateau-prediction contradiction
surfacing.[^contradiction][^versioning]

### Talking points

**Quick close on the longitudinal arc (30 seconds)**:[^versioning][^contradiction][^cross-encounter]

> "Months later, Marcus is back with his PCP for routine
> follow-up. Two quick things to point out. First, the PCP
> agent is reading a memory written by the inpatient PM&R
> physiatrist *months ago* — a prediction that motor function
> would plateau in 8 to 12 weeks. The outpatient team
> contradicted that prediction at week 10 because Marcus was
> still showing measurable gains, and they updated the original
> memory rather than writing a new one. The PCP sees the
> superseded prediction *and* the version history. She knows
> what the team thought and why they revised it."
>
> "Second — and I want to land this — when Marcus shows up at
> the PCP visit, the PCP doesn't have to read 14 chart notes
> from inpatient and outpatient to understand the patient's
> story. She reads a handful of memories that the team curated
> across the entire episode. Faster, more accurate, less
> burnout."

### Milestones demonstrated

- **Memory versioning**[^versioning] (the plateau prediction was
  updated, not proliferated)
- **Cross-time narrative continuity at the longest
  scale**[^cross-encounter]
- **Contradiction resolution preserved across
  time**[^contradiction]
- **Clinician burnout reduction** (implicit)

### Harness operator notes / shot list

- **Capture**: the PCP agent's `read_memory` call returning the
  plateau prediction memory with its version history visible.
  The version history must show both the original prediction
  and the superseded update, with timestamps and authoring
  agents.
- Keep this segment short in the recording — this is a closing
  beat, not a major moment.

## Segment 8 — Closing pitch (1:00)

### What's on screen

Recap slide with the phrase, the CDS boundary, and three bullets
covering what the audience just saw. End slide with contact info /
call to action.

### Talking points

**The phrase, one more time (15 seconds)**:[^value-prop][^cds-boundary]

> "MemoryHub holds the context that makes clinical decisions go
> well. That phrase is the entire pitch. Your CDS makes the
> recommendations. Your EHR holds the structured data. MemoryHub
> holds everything around them — the soft narrative context,
> the team's tribal knowledge, the cross-handoff continuity,
> and the agent fleet's own operational learning."

**What you saw (30 seconds)**: Recap the three or four moments that
mattered most.

> "What you saw in the last 12 minutes:
>
> One. A patient's stated goals captured in his own words and
> referenced by every discipline as they planned
> interventions.[^narrative-context][^provenance]
>
> Two. A care team's tribal knowledge — the SSRI preference —
> persisting across the unit independent of who was on
> call.[^tribal-knowledge]
>
> Three. A contradiction surfaced and resolved, not by computer
> logic, but by the team reading both interpretations and
> adjusting the plan.[^contradiction]
>
> Four. The cross-care-setting handoff that *actually worked* —
> the outpatient PT skipping three sessions of re-derivation
> because the inpatient PT's narrative context survived the
> transition.[^cross-encounter]
>
> Five. An audit trail that answers both 'what did this role
> do?' and 'what was done on behalf of this clinician?' in
> seconds.[^audit][^driver-id][^role-vs-person]"

**The call to action (15 seconds)**:

> "MemoryHub runs on Red Hat OpenShift AI. It complements your
> existing CDS and EHR — it doesn't compete with
> them.[^cds-boundary] We're looking for clinical informatics
> teams who want to pilot it with their own care teams. Come
> find us at booth [X], or reach out at [contact]. Thank you."

### Milestones demonstrated

None new — this is recap.

### Harness operator notes / shot list

- No recorded clip in this segment. Stay on the recap slide for
  the full 30 seconds while the presenter delivers the "what
  you saw" beats. Don't transition too fast.

## Demo flow at a glance

For rehearsal purposes, the milestone tie-ins are easier to scan as
a single table:

| Time | Segment | Primary milestone | Secondary milestone | Footnotes |
|---|---|---|---|---|
| 0:00-1:30 | Opening hook & framing | (None — setup) | Phrase, CDS boundary, AI-supports-humans | `[^value-prop]` `[^cds-boundary]` `[^humans-in-loop]` |
| 1:30-3:00 | Patient & team intro | Identity model (10 agents register) | Project membership, fleet provisioning | `[^identity-triple]` `[^project-scope]` `[^cli-provisioning]` |
| 3:00-5:00 | Acute → VA admission | Cross-system memory handoff | PHI quarantine + audit + provenance | `[^cross-system]` `[^narrative-context]` `[^provenance]` `[^phi-curation]` `[^audit]` |
| 5:00-8:00 | Inpatient + shift change | Driver_id distinction across shifts | Tribal knowledge memory + contradiction detection | `[^role-vs-person]` `[^driver-id]` `[^tribal-knowledge]` `[^contradiction]` |
| 8:00-10:00 | Discharge & outpatient | Cross-care-setting narrative continuity (THE KILLER MOMENT) | Agent-operational memory | `[^cross-encounter]` `[^operational-memory]` `[^value-prop]` |
| 10:00-11:30 | Audit trail | Driver_id audit query | Role-vs-person + compliance use case | `[^audit]` `[^driver-id]` `[^role-vs-person]` `[^identity-triple]` |
| 11:30-12:00 | Phase 6 & plateau | Memory versioning | Cross-time continuity | `[^versioning]` `[^contradiction]` `[^cross-encounter]` |
| 12:00-13:00 | Closing pitch | Recap of all milestones | Call to action | (all of the above) |

## Trim plan if running long

If at the 8-minute mark you're noticeably behind, here are the
specific cuts in priority order:

1. **First cut**: trim Segment 7 entirely. Skip the plateau
   contradiction. Save 30 seconds. **Lost milestones**:
   `[^versioning]`. The contradiction footnote stays demonstrated
   in Segment 4.
2. **Second cut**: shorten the agent-operational memory mention in
   Segment 5 to a single sentence ("the agent fleet also writes
   memories about itself, which we'll talk about in Q&A"). Save
   30 seconds. **Lost milestones**: `[^operational-memory]` is
   reduced to a mention, not a demonstration.
3. **Third cut**: shorten the daily rhythm intro in Segment 4
   from 30 seconds to 15 seconds. Save 15 seconds. No milestone
   loss.
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

1. Spend more time on Segment 5's killer moment. Let the audience
   really sit with the inpatient PT's memory and what it would
   mean for their own practice.
2. Add an aside in Segment 6 about how the audit trail integrates
   with their existing compliance and incident review processes.
3. Pause for one audience question in the Q&A position before
   closing.

Don't try to add new material on the fly — rehearsed material
delivers better than improvised expansion.

## What you absolutely cannot say

Words and phrases that will lose the room:[^humans-in-loop][^cds-boundary]

- "Replaces" anything human (PCP, nurse, therapist, case manager)
- "Automated care" or "AI care"
- "Decision-making AI" (you can say "AI agents that hold the
  team's shared memory" — that's not the same thing)
- "Better than CDS" or any direct comparison to CDS that implies
  competition
- "Reduces headcount" or anything that smells like it
- "Clinical reasoning" attributed to the agent (the *clinicians*
  reason; the agents hold context)

If a question in Q&A pushes toward any of these, deflect:

> "Great question. The agents don't make clinical decisions —
> the clinicians do. What the agents do is make sure the
> clinician is making that decision with the full context the
> team has built up. Same decision authority, better
> information."

## Open questions for rehearsal

1. **Visual style for the harness output**: terminal-style is
   honest but ugly; a real UI is prettier but suggests we have
   product polish we don't yet have. Recommendation: clean
   structured terminal output with clear role labels, distinct
   colors for `actor_id` vs `driver_id`, and obvious quarantine
   notifications. Decided in the recording-strategy section
   above; this is a reminder to validate it during the recording
   session.

2. **Whose grandson's name is "Tyler"**: needs to be fictional
   and ideally not a Rule of 12 violation (no real Tyler
   Reeves currently playing little league in Manassas). Same
   for any other named individuals in invented memories.

3. **Booth presence**: the call to action assumes we have a
   physical booth at HIMSS. If we don't, the close needs to
   change to a different next step (URL, contact form, follow-up
   email signup).

4. **Q&A preparation**: the most likely Q&A questions are
   probably:
   - "How does this integrate with Epic / Cerner?"
   - "What's the security and privacy story?"
   - "How is this different from [a CDS vendor]?"
   - "What does this cost?"
   - "How long does deployment take?"
   - "Who else is using this?"
   These should have prepared one-line answers that don't get
   into trouble.

5. **The presenter's clinical credibility**: if Wes (or whoever
   delivers this) is asked a clinical question they can't
   answer, the right response is "I'm a technologist, not a
   clinician — let me get our clinical advisor on that one."
   Pre-identify who that clinical advisor is and have them
   reachable during the demo session.

6. **Recording session logistics**: when does the recording
   session happen? Who runs the harness? Where is it captured?
   The recording session is its own production task and needs
   its own scheduling and rehearsal time, separate from the
   talk itself. Suggest blocking 2-3 hours for the recording
   session including reshoots, plus another 2-3 hours for cut
   and edit.

7. **Live cluster Plan A readiness**: if going live, the cluster
   must be reachable, the agent fleet preloaded, the queries
   pre-baked, and a 1-keystroke trigger for each segment ready.
   This requires the same harness as the recording, just running
   in real time. Validate end-to-end at least the day before.

## Feature reference key

Each footnote below maps a moment in the demo to the MemoryHub
feature it demonstrates, the design doc that defines it, and the
GitHub issue (if any) tracking the implementation.

[^value-prop]: **The headline phrase**: "MemoryHub holds the
    context that makes clinical decisions go well." This is the
    one-line value prop that anchors the entire clinical scenario.
    It's not a feature — it's the framing that makes the features
    legible to a clinical audience.
    *Defined in*: `docs/scenarios/clinical/README.md` ("The value
    proposition in one sentence" section).
    *Visible in the demo*: title slide (Segment 1), explicit
    callout in Segment 5 after the killer moment, recap slide in
    Segment 8.

[^cds-boundary]: **CDS boundary positioning**: the explicit
    framing that MemoryHub is *complementary* to Clinical Decision
    Support, not competitive with it. CDS makes the clinical
    recommendations; MemoryHub holds the surrounding context.
    *Defined in*: `docs/scenarios/clinical/README.md` ("The CDS
    boundary" section); reinforced in
    `docs/scenarios/clinical/stroke-rehab-marcus-reeves.md`
    ("MemoryHub vs. Clinical Decision Support" section).
    *Visible in the demo*: framing block in Segment 1, callout
    during pharmacy discharge moment in Segment 5, closing pitch
    in Segment 8.
    *Not a tracked feature* — this is positioning, not code.

[^humans-in-loop]: **Agents-support-humans framing**: every
    agent in the fleet is operated by a human clinician in
    production. The demo presenter plays the role of the entire
    care team as a demo necessity, not as a product claim about
    automation.
    *Defined in*: `docs/scenarios/README.md` ("AI supports humans,
    it doesn't replace them" section);
    `docs/scenarios/clinical/README.md` ("The humans in production
    framing" section); each role description in
    `docs/scenarios/clinical/stroke-rehab-marcus-reeves.md` has
    an "In production" sidebar.
    *Visible in the demo*: agent disclaimer in Segment 1; "what
    you cannot say" section is the verbal discipline that keeps
    this framing intact.
    *Not a tracked feature* — this is positioning, not code.

[^identity-triple]: **The owner/actor/driver identity model**:
    every memory operation involves three distinct identities.
    `owner_id` (who the memory belongs to, determines scope),
    `actor_id` (which agent performed the operation, always
    derived from authenticated identity), `driver_id` (on whose
    behalf, may equal actor_id for autonomous operation).
    *Defined in*: `docs/identity-model/data-model.md` ("The triple:
    owner, actor, driver" section). Maps to RFC 8693 token
    exchange semantics and FHIR Provenance.
    *Tracked in*: GitHub issue #65 (schema migration adding
    `actor_id` and `driver_id` columns to MemoryNode), #66
    (plumbing through tools).
    *Visible in the demo*: agent registration in Segment 2 (each
    agent's `actor_id` shown), audit trail queries in Segment 6
    (both columns visible in result rows).

[^driver-id]: **Driver_id specifically — the on-whose-behalf
    concept**: identifies the principal an agent is acting for.
    Equals `actor_id` for fully autonomous operation; differs when
    the agent is being driven by a human (or another agent) on
    that human's behalf. Captured per-session (via
    `register_session(default_driver_id=...)`) or per-request
    (override parameter).
    *Defined in*: `docs/identity-model/data-model.md` ("Tool API
    changes" section). FHIR mapping: `Provenance.agent.onBehalfOf`.
    RFC 8693 mapping: subject_token principal.
    *Tracked in*: GitHub issues #65, #66.
    *Visible in the demo*: shift change moment in Segment 4
    (driver changes while actor stays constant), audit query 2
    in Segment 6 ("everything done on behalf of Nurse Williams").

[^role-vs-person]: **Role-as-actor + person-as-driver
    distinction**: a role like "Charge Nurse" persists across
    shifts as a stable `actor_id`; the human on shift is a
    rotating `driver_id`. This is what makes shift-change
    resilience work — the role's accumulated memory survives
    every staff turnover, and the audit trail captures both
    "what did the role know?" and "who was driving the role at
    time T?" as separately answerable questions.
    *Defined in*: `docs/identity-model/data-model.md`
    (implicitly, via the actor/driver split — this is how the
    triple lands in clinical settings).
    *Tracked in*: GitHub issues #65, #66 (the underlying
    capability); demonstrated as a clinical pattern by this
    scenario.
    *Visible in the demo*: shift change moment in Segment 4 is
    the central demonstration; audit query 1 in Segment 6
    payoffs the concept by showing the role's actions spanning
    both shifts.

[^project-scope]: **Project-scope membership enforcement**:
    agents are members of specific projects (in the demo,
    `marcus-reeves-rehab`). Project-scope memories are
    readable/writable only by members. Enforces the hive-mind
    boundary so cross-project leakage is impossible.
    *Defined in*: `docs/identity-model/authorization.md`
    ("Project membership enforcement (critical path)" section).
    *Tracked in*: GitHub issue #64 (the critical-path
    implementation work).
    *Visible in the demo*: agent registration in Segment 2
    (project membership confirmed); every project-scope memory
    write in Segments 3-7 implicitly demonstrates the
    enforcement.

[^cross-system]: **Cross-system memory handoff**: a memory
    written by an agent in one care setting (community hospital)
    is read by an agent in a different care setting (VA medical
    center) at the receiving end of a transfer. The structured
    discharge summary still moves through HL7 / interface engine;
    the memory carries what won't fit in the structured handoff.
    *Defined in*: `docs/scenarios/clinical/stroke-rehab-marcus-reeves.md`
    ("Memory touchpoints" — Phase 1 → Phase 2 transition).
    *Tracked in*: implicitly via project-scope reads/writes
    (#64, #65, #66). No dedicated issue — this is an emergent
    behavior of project-scope membership.
    *Visible in the demo*: Segment 3 (Acute Care Hospitalist
    writes the transfer memory; VA Physiatrist reads it on
    admission).

[^narrative-context]: **Patient narrative context memory
    category**: the soft, unstructured patient knowledge that
    doesn't fit in structured EHR fields and isn't billable.
    Patient preferences, what motivates them, what the team has
    learned about how to communicate with them, family dynamics
    that matter to the care plan.
    *Defined in*: `docs/scenarios/clinical/README.md` ("What
    MemoryHub does (this is where the value lives)" section,
    first bullet);
    `docs/scenarios/clinical/stroke-rehab-marcus-reeves.md`
    ("Memory touchpoints" — touchpoints 1, 2, 4 are all
    narrative context).
    *Tracked in*: not a discrete feature — emerges from generic
    `write_memory` + project-scope. The *category* is a
    positioning choice; the implementation is just memory
    storage.
    *Visible in the demo*: patient goals memory in Segment 3
    (touchpoint 1), call light observation referenced in
    Segment 4, gabapentin pharmacy context in Segment 5, the
    killer moment in Segment 5 (touchpoint 4 — the inpatient PT's
    coaching framing).

[^provenance]: **Provenance branches**: a memory can have a
    child branch with `branch_type: "provenance"` that records
    where the memory's content came from (a specific
    conversation, a specific source document, a specific
    observation). Lets future readers understand the basis of a
    memory without re-deriving it.
    *Defined in*: `docs/memory-tree.md` (the underlying tree
    branch model).
    *Tracked in*: existing functionality, no new issue. The
    branch model is already implemented.
    *Visible in the demo*: patient goals memory in Segment 3
    (Case Manager writes the goals with a provenance branch
    citing the admission conversation).

[^phi-curation]: **PHI/PII curation pipeline**: when an agent
    attempts to write a memory containing patient identifiers
    (or HIPAA-specific identifiers like MRN, NPI, DEA numbers,
    DOB-in-clinical-context), the curation pipeline catches the
    attempted write and quarantines it before persistence. The
    agent then reformulates the memory to preserve clinical
    meaning without identifying details.
    *Defined in*: `docs/scenarios/clinical/demo-plan.md`
    (PHI/HIPAA detection patterns section);
    `docs/scenarios/clinical/stroke-rehab-marcus-reeves.md` (PHI
    moments section).
    *Tracked in*: GitHub issue #68 (HIPAA/PHI detection patterns
    in the curation pipeline).
    *Visible in the demo*: PHI moment in Segment 3 ("Marcus +
    Tyler + Manassas" quarantine), reinforced verbally elsewhere.

[^audit]: **Audit log**: every memory operation (write, read,
    update, delete, contradiction report, PHI quarantine) is
    captured by `audit.record_event(...)` with both `actor_id`
    and `driver_id` recorded. For the demo, the persistence
    layer is a stub that writes structured log lines; future
    work will route through LlamaStack telemetry.
    *Defined in*: `docs/identity-model/authorization.md` ("Audit
    logging — stub now, persistence later" section).
    *Tracked in*: GitHub issue #67 (audit logging stub
    interface), #70 (persistent audit log via LlamaStack
    telemetry).
    *Visible in the demo*: PHI quarantine attempt visible in
    audit in Segment 3; audit queries are the centerpiece of
    Segment 6.

[^tribal-knowledge]: **Care team tribal knowledge memory
    category**: the practices a unit has developed that aren't
    formal protocol but are how the team actually works. The
    SSRI-over-SNRI preference memory in this scenario is the
    canonical example. This kind of knowledge lives in senior
    clinicians' heads and walks out the door when they leave.
    *Defined in*: `docs/scenarios/clinical/README.md` ("What
    MemoryHub does" — second bullet);
    `docs/scenarios/clinical/stroke-rehab-marcus-reeves.md`
    (touchpoint 3).
    *Tracked in*: not a discrete feature — same emergence as
    narrative context. Category positioning, not separate code.
    *Visible in the demo*: tribal knowledge moment in Segment 4
    (Behavioral Health agent reads Dr. Patel's SSRI memory).

[^contradiction]: **Contradiction detection** via the
    `report_contradiction` tool. When one memory's interpretation
    conflicts with another's, an agent surfaces the conflict
    explicitly. Both memories are preserved; the contradiction
    relationship is queryable; the team uses the surfaced
    conflict to update their working interpretation without
    losing the original observation.
    *Defined in*: `docs/scenarios/clinical/stroke-rehab-marcus-reeves.md`
    ("Contradiction moments" section). The
    `report_contradiction` tool already exists in the MCP
    server; this is reuse, not new feature work.
    *Tracked in*: existing tool. Demo scenario validation in
    `docs/identity-model/demo-plan.md` ("Contradiction
    detection demo flow validation" section) — needs end-to-end
    walkthrough to confirm gaps.
    *Visible in the demo*: cane contradiction moment in Segment 4
    (PT vs OT on the cane); plateau contradiction in Segment 7.

[^cross-encounter]: **Cross-encounter narrative continuity**:
    the load-bearing payoff of project-scope memory and
    narrative-context memories combined. A memory written in one
    care setting (inpatient) is read in another care setting
    (outpatient) weeks later, allowing the receiving clinician
    to skip re-derivation and start where the previous
    clinician left off.
    *Defined in*: `docs/scenarios/clinical/README.md` ("What
    MemoryHub does" — third bullet);
    `docs/scenarios/clinical/stroke-rehab-marcus-reeves.md`
    (touchpoint 4 — the killer moment).
    *Tracked in*: emerges from project-scope membership (#64),
    schema (#65), and tool plumbing (#66).
    *Visible in the demo*: **the killer moment in Segment 5** —
    the outpatient PT reads the inpatient PT's coaching-framing
    memory before the first session. This is the single most
    important demonstration in the demo.

[^operational-memory]: **Agent-operational memory category**:
    the agent fleet writes memories about *itself* — operational
    lessons it has learned about how it works. No human writes
    these; no human reads them directly. They're the AI fleet's
    self-correction layer.
    *Defined in*: `docs/scenarios/clinical/README.md` ("What
    MemoryHub does" — fourth bullet);
    `docs/scenarios/clinical/stroke-rehab-marcus-reeves.md`
    (touchpoint 5).
    *Tracked in*: not a discrete feature — emerges from
    `write_memory` + scope/owner conventions. The *category* is
    novel positioning.
    *Visible in the demo*: brief mention in Segment 5 (the
    Inpatient Nurse agent's self-written memory about SLP
    update timing). Most novel demo moment, but at risk of
    confusing the audience — frame carefully.

[^versioning]: **Memory versioning via `update_memory`**: when
    new information supersedes an existing memory, the agent
    calls `update_memory` (preserves version history with
    `isCurrent` flag) instead of writing a new "actually..."
    memory. Future readers see the current state and can
    inspect the history of how the team's understanding
    evolved.
    *Defined in*: `docs/memory-tree.md` (versioning model with
    `isCurrent` flag, already implemented).
    *Tracked in*: existing functionality. Reinforced as best
    practice in `docs/scenarios/clinical/stroke-rehab-marcus-reeves.md`
    (touchpoint 6 — goal reassessment via update_memory).
    *Visible in the demo*: plateau prediction superseded in
    Segment 7 (PCP sees both the original prediction and the
    superseded version with timestamps).

[^cli-provisioning]: **Agent generation CLI**: a static
    code-gen tool that takes a fleet manifest YAML and produces
    Kubernetes Secrets, the users ConfigMap, and the harness
    manifest needed to deploy and identify the demo's agent
    fleet. The CLI is the source of the ten clinical agents
    seen in the demo.
    *Defined in*: `docs/identity-model/cli-requirements.md`
    (the full requirements doc for the CLI).
    *Tracked in*: GitHub issue #69 (build agent generation CLI
    for demo fleet provisioning).
    *Visible in the demo*: implicit in the agent fleet startup
    in Segment 2. Not directly demoed, but the existence of the
    fleet depends on it. Worth a one-liner mention if there's
    time and the audience is operationally curious ("the fleet
    you see was provisioned from a single YAML manifest").
