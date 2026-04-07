# World Agritech Demo Script — Disease Detection Scenario

A 10-15 minute presentation outline for delivering the mid-season
disease detection scenario to a World Agritech Innovation Summit-style
audience (ag-tech investors and executives, major ag platform
vendors, large operation owners, ag-tech startup founders, and
innovation-focused practitioners).

This is an **outline** with talking points, not a word-for-word script.
The presenter ad-libs the actual language; the script tells you what
to cover, in what order, and which agent fleet milestones to highlight
when.

The presenter is doing live voiceover. Behind the voiceover plays a
recorded session of the agent fleet running on a real cluster, edited
into clips that match the segment structure below. The presenter
plays the role of the entire farm team in the recording — this is a
demo necessity, and the script repeatedly reinforces that in
production every agent is operated by a working farmer or
practitioner.

Throughout the script, **footnote markers** like `[^cross-season]`
mark the specific MemoryHub feature each statement, segment, or
moment demonstrates. The full feature reference key is at the bottom
of the document, with each footnote linking to the relevant design
doc and GitHub issue.

## Audience and framing

**Who they are**: World Agritech attendees are ag-tech ecosystem
decision-makers — investors and analysts looking at the next
generation of precision-ag tools, executives at major ag platform
companies (Climate Corp, John Deere, Bayer, Corteva, AGCO), startup
founders building the next layer of the ag-tech stack, large-scale
operation owners with technology budgets, and integrators connecting
the precision-ag ecosystem together. International attendance is
significant.

This audience is **deeply skeptical of two things**: ag-tech vendor
hype and ag data ownership. They have watched a decade of "AI in
agriculture" pitches over-promise and under-deliver. They have also
watched major ag platforms collect farm data in ways that
benefit the platforms more than the farmers, and there is
well-founded suspicion in the room about any pitch that sounds like
"another platform that wants your farm data."

The good news: this audience is **also looking for the next real
thing**. They know the existing precision-ag stack is good at field
data and prescriptions but bad at the soft contextual layer that
determines whether a prescription works. They know
multi-generational knowledge is walking out the door as farmers
retire. They know cross-vendor coordination is broken. They know
data ownership is a real differentiator. A pitch that addresses
these concerns directly — and isn't just another wrapper on the
same prescription-generation play — has room to land.

**What they need to hear in the first 60 seconds**:

1. This is not another precision-ag platform.[^decision-support-boundary]
2. This is not "AI replaces farmers."[^humans-in-loop]
3. The data belongs to the operation, not to a vendor.[^data-ownership]
4. There's a specific operational scenario being shown (not a
   generic abstraction).

**What they need to leave with**:

1. The phrase: "MemoryHub holds the context that makes agronomic
   decisions go well."[^value-prop]
2. A clear understanding of the boundary — MemoryHub sits
   alongside Climate FieldView, Operations Center, and the rest
   of the existing precision-ag stack, doesn't compete with any
   of them.[^decision-support-boundary]
3. The cross-season tribal knowledge moment as the most
   distinctive demonstration of value.[^cross-season][^tribal-knowledge]
4. The applicator approval gate as the demonstration that
   MemoryHub is professional ag-tech, not a vendor demo with
   autonomous spraying.[^humans-in-loop]
5. The data ownership story as the credible
   differentiator.[^data-ownership]
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
   end through the full disease detection scenario. This is the
   source material; clips get cut from it in post.
2. The recorded session does not need to match the demo's 13-minute
   target — it can be 30-60 minutes long if the agent fleet runs
   at realistic pace. Pacing happens at the editing stage.
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
  audience sees the real thing — agriculture audiences are
  particularly skeptical of demo polish that hides what's
  underneath
- Role labels prominent — "Crop Scout Drone" not "agent-2"
- `actor_id` and `driver_id` rendered in distinct colors so the
  identity distinction is visible from the back of the
  room[^identity-triple][^driver-id]
- Sensitive-data quarantine notifications must be impossible to
  miss (red, bordered, animated, ideally all
  three)[^data-curation]
- Contradiction markers visually distinct from normal memory
  writes[^contradiction]
- Cross-season memory references should visually link to the
  prior season (e.g., "from the 2024 Field 7 tar spot
  intervention") so the audience understands they're seeing
  actual recall, not generic
  output[^cross-season]
- The Spray Drone applicator approval gate is the demo's safety
  moment — the visual styling needs to make the "waiting for
  approval" state unmistakable[^humans-in-loop]
- Resolution: at minimum 1920x1080, ideally 2560x1440 or higher
  if conference projection supports it
- Terminal font: large enough to read from the back row of a
  conference session room (think 18pt+ at recording resolution)

### Agriculture-audience-specific recording cautions

This is critical for the agriculture audience and matters more
than for the prior scripts:

- **Use obviously fake operation names, field configurations,
  and personal names.** Hollander Farms is synthetic but
  plausible. Cross-check that "Hollander Farms" doesn't match a
  real operation in central Iowa before recording. If it does,
  swap to a different name.
- **Use generic equipment vendor references, not specific
  brands.** "John Deere combines and tractors" appears in the
  scenario doc as context but the recorded harness output should
  use generic terms ("the operation's combines and tractors")
  to avoid inadvertently advertising or competing with specific
  brands.
- **Never depict specific fungicide product names.** The
  scenario doc uses "[fungicide name]" as a placeholder. The
  recording should use a generic "fungicide" or "labeled
  product" without naming a specific product. Naming a real
  product creates legal liability around off-label depiction
  and inadvertently endorses a manufacturer.
- **Never show real yield numbers, real lease rates, or real
  field-level economic data**, even synthetic-looking ones.
  These numbers are sensitive in agriculture in a way that
  doesn't have an obvious parallel in the other domains. The
  one place yield data appears in this script is in the
  sensitive-data quarantine moment — show the *attempted* write
  being blocked, not the actual yield numbers.
- **Use obviously fake personal names** for everyone. Tom,
  Linda, Kelsey, and Miguel are synthetic but plausible. The
  recording should be consistent with the scenario doc.
- **Avoid GMO, pesticide, or herbicide-resistance politics**
  entirely. The demo is about disease detection and fungicide
  application — both relatively neutral. Don't drift into
  contested territory.

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

**Critical for the agriculture audience**: if going live, the
demo cluster needs to look like it's running on infrastructure
the operation controls — not on a public cloud the audience
will instantly associate with "Big Ag harvesting your data."
This is a positioning concern, not just a technical one. If
the only available demo cluster is in a public cloud, the
talking points need to explicitly address this and frame the
production deployment as on-farm or operator-controlled.

## Time budget

Total: 13 minutes (gives you 2-minute cushion against the 15-minute
hard cap; can compress to 10 minutes by trimming Phases 5-6
walkthrough if running long).

| Segment | Time | What's on screen |
|---|---|---|
| 1. Opening hook and framing | 1:30 | Title slide → operation archetype slide |
| 2. Meet the operation and team | 1:30 | Hollander Farms intro → agent fleet startup |
| 3. Detection & cross-season pattern recall | 2:00 | Recorded clip: routine scouting, tar spot detection, multi-generational tribal knowledge |
| 4. Diagnosis confirmation & multi-source convergence | 3:00 | Recorded clip: parallel evidence, contradiction resolution, intervention decision |
| 5. Applicator approval gate & application | 2:00 | Recorded clip: spray prep, approval interface, execution |
| 6. Audit trail and data ownership story | 1:30 | Recorded clip: audit query + data ownership framing |
| 7. Post-application learning capture | 0:30 | Brief retrospective scene, lessons written for next season |
| 8. Closing pitch | 1:00 | Recap slide → call to action |

Buffer: 30 seconds for transitions and audience reactions.

## Segment 1 — Opening hook and framing (1:30)

### What's on screen

Title slide: **"MemoryHub: the context that makes agronomic decisions go well."**[^value-prop]

Below the phrase, a small subtitle: *"A demonstration with a
synthetic mid-season disease response on a working family
farm."*

### Talking points

**The hook (30 seconds)**: Open with a relatable agricultural
moment.

> "Every farmer in this room — and I know there are some in the
> room — has had this experience. You're walking a field at
> dawn, and you remember something. The southwest corner of
> this particular field always shows trouble first. Your father
> told you that fifteen years ago. Last year you saw it again.
> But this year your father isn't here, or your daughter is
> running the operation now, or you've leased this ground from
> a neighbor and you don't know its history. The knowledge that
> would have told you exactly where to look is gone. Sometimes
> you find the trouble in time. Sometimes you don't."

**The framing (30 seconds)**: Establish what we're showing and
what we're NOT showing. Address the third rails directly to
clear the air.[^decision-support-boundary][^data-ownership]

> "What I'm about to show you is not another precision-ag
> platform. It's not a Climate FieldView replacement. It's
> not an Operations Center replacement. It's not a
> prescription generator. And — I want to address this up
> front — it is not a vendor cloud that wants your farm data.
> What you're about to see runs on infrastructure the
> operation controls. The memories belong to the farm. The
> operation chooses where they're stored, who reads them, and
> when they're deleted. There is no 'MemoryHub the company
> harvests your data' angle, because MemoryHub is open
> software running on the operation's own cluster."

**The agent disclaimer (30 seconds)**: Get this in early. Don't
let the audience misread the demo as autonomous
farming.[^humans-in-loop]

> "I'll be playing the role of the entire farm team during this
> demo. Every agent you see is operated by a human practitioner
> in production. The Crop Scout Drone agent? In production,
> that's the operation's precision-ag specialist — often the
> operator's adult child or a hired manager. The Spray Drone
> agent is operated by a **licensed applicator** under FAA Part
> 137. The Agronomy agent is consulted by the farmer when
> making intervention decisions. The Compliance agent is
> operated by whoever handles records. **These agents help
> farmers; they don't replace them. They do not autonomously
> spray. They do not autonomously prescribe. They hold the
> operational and historical memory the farm team needs to
> make the calls.**"

### Milestones demonstrated

None yet — this is setup. But you've planted four things:

- The phrase[^value-prop]
- The decision-support boundary[^decision-support-boundary]
- The data ownership story[^data-ownership]
- The agents-support-humans framing[^humans-in-loop]

### Harness operator notes / shot list

- No harness footage in this segment. Stay on slides.
- Have the recorded clip queued up to begin on the cue at the
  start of Segment 2.

## Segment 2 — Meet the operation and team (1:30)

### What's on screen

Slide: operation archetype. Hollander Farms, 4,500 acres central
Iowa, the team (Tom, Linda, Kelsey, Miguel), the technology
stack, the scenario event (mid-July, V12 corn, early tar spot).

Then transition to the recorded clip showing the agent fleet
registering with MemoryHub.[^identity-triple][^cli-provisioning]

### Talking points

**The operation introduction (45 seconds)**: Make Hollander
Farms feel like a real operation, not a hypothetical.

> "Hollander Farms. Forty-five hundred acres in central Iowa.
> Third generation. Tom Hollander is sixty-one years old, took
> over from his father in 1998, knows the fields the way only
> someone who has farmed them for twenty-five years can know
> them. His wife Linda handles the books and the compliance.
> Their adult daughter Kelsey came back to the farm three
> years ago with an agronomy degree from Iowa State and four
> years at a precision-ag startup — she's increasingly running
> the day-to-day. Miguel has been with the operation for
> twelve years and runs most of the equipment. They grow corn
> and beans on a fifty-fifty rotation."
>
> "It's mid-July. The corn is at V12. Today, Kelsey's morning
> drone scouting flight has picked up something on Field 7.
> Field 7 had tar spot pressure in 2024 — the same Phyllachora
> maydis disease that's been a growing problem in Midwest corn
> since 2018. Today's signature is small. Maybe ten acres in
> the southwest section of the field. The team has three days
> to figure out what to do about it before the disease either
> takes hold or burns itself out. Today, on screen, you're
> going to watch how this team uses shared memory to coordinate
> across drones, soil sensors, weather data, and prior seasons
> to make that call."

**Why this scenario (15 seconds)**:

> "Every detail in this demo respects the things that matter
> to farmers. The fungicide application follows EPA label
> requirements. The spray drone operates under FAA Part 137
> with a licensed applicator in the loop. The data stays on
> the operation's infrastructure. We're not shortcutting any
> of the things you can't shortcut in real ag-tech."

**Agent fleet startup (30 seconds)**: Cue the recorded clip.
Show the ten agents registering with
MemoryHub.[^identity-triple][^project-scope]

> "On screen now you'll see the farm team fleet starting up.
> Each agent is registering with MemoryHub and being
> authenticated. Watch the role names — Crop Scout Drone,
> Thermal/Moisture Drone, Spray Drone, Soil Sensor Network,
> Weather, Tractor and Equipment Coordinator, Agronomy,
> Compliance, Farm Manager, Multi-Operation Liaison. Ten
> roles. In production, each one is the interface a working
> practitioner uses to chat with the operation's accumulated
> shared memory."

### Milestones demonstrated

- **Identity model**[^identity-triple]: ten agents come online,
  each with its own identity. The recorded clip shows each
  agent's `actor_id` as it registers.
- **Project membership**[^project-scope]: all ten agents are
  members of a shared project (`hollander-farms-2025`). The
  audit trail will hang off this project membership later.
- **Fleet provisioning**[^cli-provisioning]: implicit — the fleet
  was generated from a manifest by the agent generation CLI.

### Harness operator notes / shot list

- **Capture**: each agent's `register_session` call landing in
  the harness output, with the role name and `actor_id` clearly
  visible. Hold for 1-2 seconds per agent so the audience can
  read the role names.
- **Capture**: a confirmation line showing all ten agents are
  members of the `hollander-farms-2025` project.
- The driver_id at this point is set to the demo presenter
  (e.g., `wjackson-worldagritech-demo`). Make sure it's
  visible in the registration output — it will be referenced
  later in the audit trail segment.[^driver-id]

## Segment 3 — Detection & cross-season pattern recall (2:00)

### What's on screen

Recorded clip showing the routine scouting flight, the initial
tar spot detection, and the cross-season tribal knowledge moment
that tells the team where to look.[^cross-season][^tribal-knowledge]

### Talking points

**Routine scouting (30 seconds)**:

> "It's Day 1, mid-morning. Kelsey is running a routine scouting
> flight over Field 7 — a 240-acre corn field that's been on
> the team's watchlist this season. The Crop Scout Drone agent
> is capturing multispectral imagery. And here's what it picks
> up — a signature in the southwest section consistent with
> early-stage tar spot. Small. Maybe ten acres. But clear
> enough that the agent flags it for follow-up."

**The killer moment 1 — multi-generational tribal knowledge (1:00)**: Slow down. Make it land.[^cross-season][^tribal-knowledge]

> "Now watch what the Agronomy agent does next. It's reading
> shared memory for context on this detection. And here's what
> it surfaces."
>
> "A memory written by Kelsey in late August of 2024. Here's
> what it says: 'Tar spot detection on Field 7 in 2024. First
> noticed August fifteenth in the same southwest section as
> today's hit. Affected area was about eighteen acres at first
> detection — grew to roughly thirty-five acres before we
> sprayed. Tom's takeaway from last year: The southwest corner
> of Field 7 is always the first place we'll see it. The
> microclimate there — the tree line creates a humidity
> pocket — is exactly what tar spot likes. If we see it
> anywhere in this field, it'll be there first.'"
>
> "I want you to think about what just happened. Kelsey wrote
> down what her father said to her in 2024 about how this
> particular field behaves. Today, ten months later, with the
> same disease showing up in the same spot, that memory is
> right here in front of the team. Tom's understanding of how
> Field 7 behaves — built up over twenty-five years of farming
> it — is now persistent. It's available to Kelsey. It will
> be available to whoever runs this operation after Tom
> retires. It will be available if Kelsey hires a manager. It
> doesn't walk out the door."
>
> "*This* is what the multi-generational tribal knowledge
> problem looks like in agriculture, and it's the single most
> distinctive thing about how MemoryHub fits this domain. The
> existing precision-ag platforms hold field data and
> prescriptions. They don't hold what Tom said to Kelsey at
> the kitchen table about why the southwest corner of Field 7
> is the leading edge. *That* is the context that makes
> agronomic decisions go well."[^value-prop]

**The morning briefing tribal knowledge (30 seconds)**:[^tribal-knowledge]

> "While that's happening, watch what the Farm Manager agent
> does. It's preparing Tom's morning briefing, and it's
> applying a preference memory Kelsey wrote months ago: 'Tom
> prefers the morning briefing in this order — equipment
> health first, weather second, field issues third. He's said
> he wants equipment first because if something is broken, he
> needs to know before he plans the day. Linda prefers the
> opposite order because she handles compliance first thing.'
> The agent generates Tom's briefing in his order. Equipment
> (no issues today). Weather (clear). Field issues — and this
> is where the new tar spot flag lands. Tom reads the
> briefing the way he likes to read it, and the new
> information lands in a frame he'll actually pay attention
> to."

### Milestones demonstrated

- **Cross-season pattern recognition**[^cross-season] (the
  killer moment)
- **Multi-generational tribal knowledge**[^tribal-knowledge]
  (Tom's 2024 takeaway captured by Kelsey)
- **Per-operator preference memory**[^tribal-knowledge] (Tom's
  morning briefing order)
- **Project-scope reads**[^project-scope]
- **Value prop landing**[^value-prop]: the headline phrase gets
  its first strong demonstration here

### Harness operator notes / shot list

- **The 2024 tar spot memory recall is the most important shot
  in this segment.** The Agronomy agent's `search_memory` call
  must be visible, the memory text must be on screen with
  Tom's quoted observation visible, and the camera needs to
  hold on it for at least 5 seconds — long enough that the
  audience can take in not just the words but the *kind of
  knowledge* being captured.
- **Capture**: the Farm Manager agent generating Tom's morning
  briefing in his preferred order, with the preference memory
  visible alongside.
- The visual styling should make the cross-season reference
  unmistakable — "from August 2024" should be a clear visual
  badge on the memory recall.[^cross-season]

## Segment 4 — Diagnosis confirmation & multi-source convergence (3:00)

### What's on screen

The longest segment. Multiple moments compressed into a
fast-paced walkthrough of the diagnosis confirmation phase.
Key beats:

- Multi-source convergence on the diagnosis
- A contradiction between drone imagery and soil sensor data
- The intervention decision rooted in tribal knowledge from
  Tom's operating philosophy
- Per-operator role distinction (Tom and Kelsey both consult
  the Agronomy agent but with different driver_ids)[^role-vs-person][^driver-id]
- A second sensitive-data quarantine moment

### Talking points

**Confirmation in parallel (45 seconds)**:[^cross-season]

> "Kelsey runs a follow-up flight at higher resolution. The
> Thermal/Moisture Drone overflies in parallel. The Soil
> Sensor Network agent surfaces moisture and temperature data
> from the field's sensors. Watch the convergence happen in
> real time on screen."
>
> "The Crop Scout Drone confirms the multispectral signature.
> The Thermal Drone shows the affected area is 1.2 degrees
> Celsius cooler than the surrounding canopy — consistent with
> reduced photosynthesis from disease, not heat stress. The
> Soil Sensor Network shows soil moisture in the affected area
> is normal — ruling out drought stress as a competing
> diagnosis. The Weather agent surfaces the past two weeks of
> elevated humidity supporting disease development."
>
> "The Agronomy agent integrates all four signals into a
> single working memory. Tar spot diagnosis confirmed. Affected
> area approximately ten to twelve acres. Recommend
> intervention decision. **In current practice**, each of these
> four signals would live in a different platform. The
> agronomist would have to pull data from four places and form
> the diagnosis manually, often days later. MemoryHub does the
> synthesis at the moment the question is asked."

**The contradiction moment (45 seconds)**:[^contradiction]

> "And while that convergence is happening, there's a
> contradiction the agents resolve. The Crop Scout Drone agent
> initially wrote: 'Multispectral signature is consistent with
> tar spot, but the affected area also shows reduced NDVI
> values that could be consistent with localized drought
> stress.' The Soil Sensor Network agent reads that and
> writes a contradicting memory: 'Soil moisture in Field 7 SW
> is at 28% — within normal range for this field at this
> growth stage. The drought stress hypothesis is not
> supported. Three sensors all reporting consistent moisture
> levels. Recommend ruling out drought stress.'"
>
> "Soil Sensor Network calls report_contradiction. The
> Agronomy agent reads both interpretations. The soil sensor
> data is more specific and reliable for moisture state than
> drone-derived inference. Drought stress is ruled out. The
> diagnosis converges on tar spot. *And* the contradicting
> interpretation isn't deleted — it's preserved as evidence
> that the team considered drought stress and ruled it out
> for a documented reason. Six months from now, when the team
> is debriefing this season, they'll see exactly what they
> thought and why they revised their thinking."

**The intervention decision and operating philosophy (1:00)**:[^cross-season][^role-vs-person][^driver-id]

> "Now Day 2. The team meets in the morning to decide what to
> do. Tom, Kelsey, and Linda — three different humans
> consulting the same Agronomy agent across the conversation.
> Watch the harness output here. Same Agronomy agent role,
> different drivers — Tom's chats are tagged with his
> driver_id, Kelsey's with hers, Linda's with hers. The agent
> serves all three of them with the same operation memory but
> the audit trail captures who was driving each conversation.
> Same role, different humans."
>
> "And here's what the Agronomy agent surfaces during the
> discussion — a memory Kelsey wrote three years ago after a
> kitchen-table conversation with her father: 'Tom's rule on
> fungicide intervention from a March 2022 conversation: We
> don't spray prophylactically on this farm. We've never had
> to. The fields that always need it should be spot-treated,
> the ones that don't shouldn't be sprayed at all. Spend the
> money on what's actually showing pressure. This is
> operational philosophy — we follow it unless the data
> clearly says otherwise. For Field 7 SW: this is exactly the
> spot-treatment case Tom described.'"
>
> "The team's decision: spot-treat the affected area plus a
> twenty-acre buffer. Not the whole field. Not nothing. The
> middle path — exactly what Tom's operating philosophy
> prescribes. The decision lands consistently with how this
> farm has always operated, *because* the operating philosophy
> is captured and reachable, not because the agents made the
> decision."

**The yield-data quarantine moment (15 seconds)**:[^data-curation][^data-ownership]

> "And one quick governance moment. While the Compliance agent
> is preparing to document the planned application, it
> attempts to write a memory that includes the field's
> projected yield comparison against multi-year averages. The
> curation pipeline catches it instantly. Yield data is
> competitively sensitive. It doesn't belong in shared memory
> where anyone with access could read it. The pipeline
> quarantines and the agent rewrites with the operational
> facts intact and the yield numbers stripped. Yield data
> stays in the operation's private records. *That* is the
> data ownership story you can actually show, not just claim."

### Milestones demonstrated

- **Multi-source convergence on diagnosis**[^cross-season]
- **Contradiction detection**[^contradiction]: drone NDVI
  interpretation vs. soil sensor moisture data
- **Multi-generational tribal knowledge**[^tribal-knowledge]
  (Tom's operating philosophy from 2022)
- **Driver_id distinction across humans on the same
  role**[^driver-id][^role-vs-person]: Tom, Kelsey, and Linda
  all consult the same Agronomy agent with different
  driver_ids
- **Sensitive-data curation**[^data-curation] catching yield
  data before persistence
- **Data ownership story landing**[^data-ownership]

### Harness operator notes / shot list

- **Capture the multi-source convergence visibly.** All four
  signals (multispectral, thermal, soil sensor, weather)
  should be on screen at the same time as the Agronomy agent
  integrates them. Side-by-side or stacked panes work. The
  audience needs to see "four sources, one synthesis."
- **Capture both memories of the drought-stress
  contradiction**: drone's tentative interpretation and
  soil sensor's contradiction. When `report_contradiction`
  is called, the relationship between the two memories
  should be visually rendered.
- **Capture**: the operating philosophy memory being read by
  the Agronomy agent during the team meeting, with Tom's
  quoted words visible.
- **Capture**: the same Agronomy agent role being driven by
  Tom (one driver_id), then Kelsey (different driver_id),
  then Linda (different driver_id) in succession. The
  driver_id changes must be visible as the conversation
  shifts.
- **Capture both halves of the yield-data quarantine**: the
  rejected attempt with the yield numbers visible in the
  rejected text (use obviously fake numbers), visibly marked
  as quarantined, and the rewritten successful version with
  the yield data stripped.

## Segment 5 — Applicator approval gate & application (2:00)

### What's on screen

The demo's safety moment. The Spray Drone agent prepares the
application with full constraint checking, surfaces the
constraints to the licensed applicator, waits for approval, and
executes only after explicit sign-off.

### Talking points

**Application preparation (30 seconds)**:[^humans-in-loop]

> "Day 3 is application day. Kelsey is up before dawn. The
> Spray Drone agent has been preparing the application package
> overnight. Watch the harness output."
>
> "The Spray Drone agent is showing the full preflight
> checklist. Field 7 SW spot treatment plus twenty-acre
> buffer. The labeled fungicide product. The label rate. The
> wind constraints. The drift cone calculation. The REI —
> twelve hours. The PHI — fourteen days, well outside harvest
> projection. Adjacent field constraints checked. The Tractor
> agent confirms no ground equipment will be in Field 7
> during the spray window. The neighbor to the east cleared
> at last spray with no new sensitivities reported."

**The killer moment 2 — applicator approval gate (1:00)**: Slow down. This is the safety moment.[^humans-in-loop]

> "And here is the most important moment in this entire demo.
> The Spray Drone agent has done all the preparation. It has
> checked every constraint. The application is ready to
> execute. **And the agent stops.** It surfaces every line of
> the preflight checklist to Kelsey. It marks itself
> 'Awaiting licensed applicator approval, Kelsey Hollander,
> Part 137.' And it waits."
>
> "I want everyone in this room to understand what just
> happened. The agent did the preparation work. It didn't do
> the spraying. **The agent never sprays without a licensed
> applicator's explicit approval.** That's not a marketing
> claim, it's a structural property of how the agent operates.
> If Kelsey doesn't approve, nothing happens. Not 'AI sprays
> the field while the human sleeps.' Not 'autonomous
> precision agriculture.' A licensed applicator approves
> every flight."
>
> "Kelsey reviews the preflight at 05:42. She approves. The
> drone executes. The application completes at 07:18. At 07:32
> the spray drone reports execution complete and the
> Compliance agent immediately captures the application
> record for the operation's required spray records — product,
> rate, area, time, weather, applicator, target pest.
> Everything that needs to be in the records is in the
> records, automatically, the moment the application
> completes."

**A real-time wind contradiction (30 seconds)**:[^contradiction]

> "And one more moment from the application — a self-correction
> from the Weather agent. The forecast at 05:00 said wind
> would stay below eight miles per hour through nine in the
> morning. At 06:48 — twenty-eight minutes into the
> application — the on-farm weather station registers an
> eleven mile-per-hour gust. The Weather agent catches its
> own forecast being wrong, calls report_contradiction
> against its earlier prediction, and the Spray Drone
> immediately holds. The application pauses. Kelsey reviews
> the contradiction at 06:50. Wait twenty minutes for the
> wind to settle. At 07:10 the wind is back below limits.
> She approves resumption. Application completes at 07:32.
> Slightly later than planned, but within all safety
> envelopes. *That* is what self-aware operation looks like
> when an agent fleet has its own memory of what it observed
> versus what it predicted."

### Milestones demonstrated

- **Applicator approval gate**[^humans-in-loop]: the Spray
  Drone agent waits for explicit approval before any
  application
- **Self-correcting Weather agent**[^contradiction]: forecast
  vs. real-time data contradiction caught by the agent that
  made the original forecast
- **Compliance recordkeeping**[^audit]: application record
  captured automatically for required regulatory records
- **Cross-fleet operational coordination**[^operational-memory]:
  Tractor agent confirming no ground equipment will be in the
  airspace

### Harness operator notes / shot list

- **The applicator approval gate is the most important
  shot in this segment.** Capture the full preflight checklist
  on screen. Capture the "Awaiting licensed applicator
  approval, Kelsey Hollander, Part 137" line in distinctive
  visual styling. Capture Kelsey's explicit approval action.
  The audience needs to see all three steps clearly.
- **Capture**: the application execution and the Compliance
  agent's automatic record capture immediately after
  completion.
- **Capture**: the wind exceedance event, the Weather agent's
  self-contradiction, the Spray Drone hold, and the resumption
  approval. The full self-correction loop must be visible.
- The visual styling for the approval gate should make
  "human in the loop" unmistakable. Color, animation,
  bordered callout — whatever it takes to make the audience
  see that this is a deliberate safety pause.

## Segment 6 — Audit trail and data ownership story (1:30)

### What's on screen

The recorded clip shifts to a query mode. Two queries are run,
followed by a brief data ownership framing
moment.[^audit][^driver-id][^role-vs-person][^data-ownership]

### Talking points

**The data ownership framing (30 seconds)**:[^data-ownership][^audit][^identity-triple]

> "Let me switch from the operational narrative for a moment
> and address the data ownership question directly, because I
> know it's on the mind of every farmer and ag-tech person in
> this room. Everything we just walked through — every memory
> written, every memory read, every contradiction reported,
> every quarantine event — is recorded in MemoryHub's audit
> log. Every operation has two identities attached: the
> *actor* (which agent did it) and the *driver* (the human
> on whose behalf it was done)."
>
> "And critically — this audit log lives on the operation's
> own infrastructure. Not in a vendor cloud. Not on the
> platform company's servers. On the cluster the operation
> controls. The operation can query it, export it, audit it,
> and delete it. **The data belongs to the farm.**"

**Query 1 (20 seconds)**:[^role-vs-person][^audit]

> "Watch this. I'm going to ask the audit log: 'Show me
> everything the Agronomy agent did during the Field 7 tar
> spot decision.' On screen now you're seeing every action
> that role took during the three days — across Tom's
> consultations, Kelsey's consultations, and Linda's
> consultations. Every read, every write, every
> contradiction surfaced, every memory consulted."

**Query 2 (20 seconds)**:[^driver-id][^audit]

> "Now I'm going to ask a different question: 'Show me
> everything done on behalf of Kelsey across the entire
> agent fleet during this incident.' Different result set.
> This shows me what Kelsey was driving — not just the
> Agronomy agent but every other agent she touched, including
> the Spray Drone approval action. Kelsey, as the licensed
> applicator, has her name on every spray-related decision in
> this audit trail."

**The point landing (10 seconds)**:

> "Both questions are answerable in seconds. And the answers
> live on the operation's own infrastructure. The operation
> owns the questions and the answers."

### Milestones demonstrated

- **Audit log with actor/driver split**[^audit][^identity-triple]
- **Driver_id queryability**[^driver-id]
- **Role-vs-person identity model**[^role-vs-person]
- **Data ownership story made tangible**[^data-ownership]:
  the audit trail lives on the operation's infrastructure

### Harness operator notes / shot list

- **Capture both queries running** with their distinct result
  sets visible. The audience needs to see actual rows of
  audit data.
- Result rows must clearly show the `actor_id` and `driver_id`
  columns so the distinction between the two queries is
  visible.[^identity-triple][^driver-id]
- For the recording: the queries should produce
  well-formatted output (a four-column table: timestamp,
  action, actor, driver). Not raw JSON.
- **Reinforce the data ownership story visually** — the
  query interface or the surrounding context should make it
  clear this is running on the operation's infrastructure,
  not in a vendor cloud. If possible, show a brief cluster
  identification ("hollander-farms.local" or similar) that
  reinforces "this is the farm's own cluster."

## Segment 7 — Post-application learning capture (0:30)

### What's on screen

A brief moment from the after-action review. The team writes
new memories explicitly for next season.[^cross-season][^narrative-context]

### Talking points

**Closing the loop (30 seconds)**:[^cross-season][^narrative-context]

> "A week after the application, the team writes new memories
> for next season. The Agronomy agent captures the lessons:
> the early detection on Field 7's southwest microclimate paid
> off, confirming Tom's rule that this is the leading edge
> for that field. The spot treatment plus buffer worked —
> full-field application would have been wasted. The morning
> wind window closed about thirty minutes earlier than the
> regional forecast predicted, so the Weather agent should
> weight the on-farm station more heavily for spray timing
> decisions on this farm going forward. Three lessons
> captured. They will be read by the agent fleet the next
> time tar spot is suspected on this operation, and
> especially on Field 7. The lessons from this season will
> shape next season's response. *That* is what
> multi-generational institutional memory looks like when an
> agent fleet is the surface for it."

### Milestones demonstrated

- **Explicit cross-season learning capture**[^cross-season]
- **Narrative context category**[^narrative-context]: lessons
  written as narrative, not as structured rules

### Harness operator notes / shot list

- **Capture**: the Agronomy agent writing the lesson memories
  with timestamps and the specific lessons visible. Hold for
  2 seconds each.
- Keep this segment short — closing beat, not a major
  moment.

## Segment 8 — Closing pitch (1:00)

### What's on screen

Recap slide with the phrase, the boundary, the data ownership
story, and the bullets covering what the audience just saw. End
slide with contact info / call to action.

### Talking points

**The phrase, one more time (15 seconds)**:[^value-prop][^decision-support-boundary]

> "MemoryHub holds the context that makes agronomic decisions
> go well. That phrase is the entire pitch. Climate FieldView
> holds the field boundary and the prescription. John Deere
> Operations Center holds the equipment telemetry. xarvio
> predicts the disease risk. MemoryHub holds everything
> around them — the cross-season patterns, the
> multi-generational tribal knowledge, the operational
> lessons from prior seasons, and the agent fleet's own
> learning."

**What you saw (30 seconds)**: Recap the moments that mattered
most.

> "What you saw in the last twelve minutes:
>
> One. A memory from Kelsey's notes about her father's
> twenty-five years of experience with one specific field
> microclimate, available to the team at the moment of
> detection.[^cross-season][^tribal-knowledge]
>
> Two. Multi-source convergence — drone imagery, thermal,
> soil sensors, weather — synthesized into a single
> diagnosis at the moment the team was asking the
> question.[^cross-season]
>
> Three. The same Agronomy agent role serving three
> different humans — Tom, Kelsey, and Linda — with the audit
> trail capturing each consultation independently.[^role-vs-person][^driver-id]
>
> Four. A spray drone that prepared a fungicide application
> and *waited* for the licensed applicator's approval before
> executing.[^humans-in-loop]
>
> Five. An audit trail that lives on the operation's own
> infrastructure and answers both 'what did this role do?'
> and 'what was done on behalf of this person?' in
> seconds.[^audit][^data-ownership]"

**The call to action (15 seconds)**:[^data-ownership][^decision-support-boundary]

> "MemoryHub runs on Red Hat OpenShift AI. It runs on
> infrastructure the operation controls — your own cluster,
> your own data, your own decisions. It complements your
> existing precision-ag stack — Climate FieldView,
> Operations Center, xarvio, whatever you're already running
> — it doesn't compete with any of them. We're looking for
> operations and ag-tech partners who want to pilot it. Come
> find us at booth [X], or reach out at [contact]. Thank
> you."

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
| 0:00-1:30 | Opening hook & framing | (None — setup) | Phrase, boundary, data ownership, agents-support-humans | `[^value-prop]` `[^decision-support-boundary]` `[^data-ownership]` `[^humans-in-loop]` |
| 1:30-3:00 | Operation & team intro | Identity model (10 agents register) | Project membership, fleet provisioning | `[^identity-triple]` `[^project-scope]` `[^cli-provisioning]` |
| 3:00-5:00 | Detection & cross-season recall | Cross-season tribal knowledge (KILLER MOMENT 1) | Multi-generational knowledge transfer, per-operator preferences | `[^cross-season]` `[^tribal-knowledge]` `[^value-prop]` |
| 5:00-8:00 | Diagnosis confirmation & convergence | Multi-source convergence + intervention philosophy | Driver_id distinction across humans on same role, contradiction, yield-data quarantine | `[^cross-season]` `[^contradiction]` `[^tribal-knowledge]` `[^role-vs-person]` `[^driver-id]` `[^data-curation]` `[^data-ownership]` |
| 8:00-10:00 | Applicator approval & application | Applicator approval gate (KILLER MOMENT 2) | Self-correcting weather, compliance recordkeeping | `[^humans-in-loop]` `[^contradiction]` `[^audit]` `[^operational-memory]` |
| 10:00-11:30 | Audit trail & data ownership | Driver_id audit query + data ownership story | Role-vs-person | `[^audit]` `[^driver-id]` `[^role-vs-person]` `[^identity-triple]` `[^data-ownership]` |
| 11:30-12:00 | Post-application learning | Explicit cross-season learning capture | Narrative context | `[^cross-season]` `[^narrative-context]` |
| 12:00-13:00 | Closing pitch | Recap of all milestones | Call to action | (all of the above) |

## Trim plan if running long

If at the 8-minute mark you're noticeably behind, here are the
specific cuts in priority order:

1. **First cut**: trim Segment 7 entirely. Skip the post-application
   learning capture moment. Save 30 seconds. **Lost milestones**:
   the explicit "writing memories for next season" demo. The
   general `[^cross-season]` concept stays demonstrated in
   Segments 3 and 4.
2. **Second cut**: shorten the wind-exceedance contradiction in
   Segment 5 to a single sentence ("the Weather agent also
   self-corrected mid-flight when its forecast was wrong — we'll
   talk about that in Q&A"). Save 30 seconds. **Lost milestones**:
   one of two `[^contradiction]` demonstrations.
3. **Third cut**: drop the per-operator preference memory in
   Segment 3 (Tom's morning briefing order). Save 30 seconds.
   **Lost milestones**: one of three `[^tribal-knowledge]`
   demonstrations.
4. **Fourth cut**: drop one of the two audit queries in Segment 6
   (keep the role-based one, drop the human-based one, mention
   the second briefly in narration). Save 20 seconds. **Lost
   milestones**: half of `[^driver-id]`'s demonstration in this
   segment. Keep query 1 and describe query 2 verbally.

Total trimmable: ~1:50. This brings worst-case 13-minute target
down to ~11:10, well inside the 15-minute hard cap.

## Trim plan if running short

If you finish at 11 minutes and want to fill to 13, the easy
extensions are:

1. Spend more time on Segment 3's tribal knowledge moment. Let
   the audience really sit with Tom's quoted observation about
   Field 7's microclimate. The multi-generational angle is
   distinctive enough that it benefits from extra time.
2. Spend more time on Segment 5's applicator approval gate.
   Walk the audience through the preflight checklist line by
   line so the safety dimension lands clearly.
3. Add an aside in Segment 6 about the deployment topology and
   how the on-farm cluster works.
4. Pause for one audience question in the Q&A position before
   closing.

Don't try to add new material on the fly — rehearsed material
delivers better than improvised expansion.

## What you absolutely cannot say

Words and phrases that will lose the room:[^humans-in-loop][^decision-support-boundary][^data-ownership]

- "Replaces farmers" or any equivalent
- "Optimize your yield" (marketing cliche the audience has
  been burned by)
- "Smart farm" / "AI-driven precision agriculture" (vendor
  cliches)
- "Big data agriculture" (the audience associates this with
  data ownership concerns)
- "Cloud-based" used positively without qualification (the
  audience hears "your data leaves the farm")
- "Eliminates the need for [scouting / consultation / human
  role]"
- "AI-powered [anything]" (vendor cliche)
- Confident attribution of an autonomous decision to the agent
  (the audience will recognize this as a tell)
- "Set it and forget it" agriculture (oversells autonomy)
- Anything that sounds like the platform owns the data

If a question in Q&A pushes toward any of these, deflect:

> "Great question. The agents don't make agronomic decisions —
> the farmers do. What the agents do is make sure the farmer
> is making that decision with the full context the operation
> has built up. Same decision authority, better information,
> and the data stays on the operation's infrastructure."

If a question gets specifically about data ownership or
vendor lock-in:

> "I want to be straightforward about this. MemoryHub is
> open-source software that runs on infrastructure the
> operation controls. The memories belong to the farm. The
> operation chooses where they're stored, who reads them, and
> when they're deleted. There is no vendor cloud collecting
> your data. We're trying to be the layer that *defends*
> against the data ownership problem in ag-tech, not another
> instance of it."

## Open questions for rehearsal

1. **Visual style for the harness output**: same recommendation
   as the prior scripts — clean structured terminal output,
   distinct colors for `actor_id` vs `driver_id`, obvious
   quarantine notifications. For agriculture specifically, the
   visual styling for the applicator approval gate must be
   unmistakable.

2. **Synthetic operation details**: the demo references
   Hollander Farms, central Iowa, Tom, Linda, Kelsey, Miguel,
   Field 7, Bob Henderson, the Krueger estate. All synthetic.
   Cross-check that none of these match a real operation
   before recording.

3. **Booth presence**: the call to action assumes we have a
   physical booth at World Agritech. If we don't, the close
   needs to change.

4. **Q&A preparation**: the most likely Q&A questions for an
   ag-tech audience are:
   - "How does this integrate with Climate FieldView /
     Operations Center / xarvio?"
   - "What's the data ownership story specifically — where
     does the data live?"
   - "How do you prevent vendor lock-in?"
   - "Who else is using this in agriculture?"
   - "What about smaller operations that don't have a
     precision-ag specialist on staff?"
   - "How do you handle multi-tenant deployments for
     cooperatives or service providers?"
   - "What does this cost?"
   - "How long does deployment take?"
   - "Does it work without the drones / sensors / equipment
     listed in the demo?"
   These should have prepared one-line answers.

5. **The data ownership concern is the demo's biggest political
   risk and biggest differentiator**. The framing must be
   absolutely consistent throughout the talk. Pre-write the
   one-paragraph version of the data ownership story and
   rehearse it until it's automatic.

6. **The "MemoryHub as new vendor lock-in" concern**: this
   will come up. The answer is that MemoryHub is open source,
   the deployment is on operator-controlled infrastructure,
   and the memories are exportable. Pre-write a one-liner.

7. **Recording session logistics**: when does the recording
   session happen? Who runs the harness? Where is it
   captured? Same as the prior scripts — block 2-3 hours for
   the recording session including reshoots, plus another
   2-3 hours for cut and edit.

8. **Live cluster Plan A readiness**: if going live, the
   cluster must be reachable, the agent fleet preloaded,
   the queries pre-baked, and a 1-keystroke trigger for each
   segment ready. Also ensure the cluster doesn't visibly
   look like a public cloud. Validate end-to-end at least the
   day before.

9. **The presenter's ag credibility**: same concern as the
   prior scripts. If Wes (or whoever delivers this) is asked
   an agronomic question they can't answer, the right
   response is "I'm a technologist, not an agronomist —
   let me get our ag advisor on that one." Pre-identify
   who that ag advisor is and have them reachable during the
   demo session.

10. **Conference target choice**: World Agritech is the
    decision-maker / investor conference. If the demo target
    shifts to a more practitioner-focused conference
    (Commodity Classic, InfoAg, Farm Progress Show), the
    framing should adjust toward more operational depth and
    less investor pitch language.

## Feature reference key

Each footnote below maps a moment in the demo to the MemoryHub
feature it demonstrates, the design doc that defines it, and the
GitHub issue (if any) tracking the implementation.

[^value-prop]: **The headline phrase**: "MemoryHub holds the
    context that makes agronomic decisions go well." This is
    the one-line value prop that anchors the agriculture
    scenario. Same shape as the clinical, cybersecurity, and
    public safety value props with one word changed,
    demonstrating platform messaging consistency across
    domains.
    *Defined in*: `docs/scenarios/agriculture/README.md`
    ("The value proposition in one sentence" section).
    *Visible in the demo*: title slide (Segment 1), explicit
    callout in Segment 3 after the killer moment, recap slide
    in Segment 8.

[^decision-support-boundary]: **The decision-support boundary
    positioning**: the explicit framing that MemoryHub is
    *complementary* to the existing precision-ag stack
    (Climate FieldView, John Deere Operations Center,
    Trimble, Granular, Bayer xarvio, AgLeader, Raven, AGCO
    Fuse, etc.), not competitive with any of them. The
    existing stack does field data and prescriptions;
    MemoryHub holds the surrounding narrative and
    operational memory.
    *Defined in*: `docs/scenarios/agriculture/README.md`
    ("The decision-support boundary" section); reinforced in
    `docs/scenarios/agriculture/disease-detection-hollander-farms.md`
    ("MemoryHub vs. existing precision-ag platforms"
    section).
    *Visible in the demo*: framing block in Segment 1,
    closing pitch in Segment 8.
    *Not a tracked feature* — this is positioning, not code.

[^humans-in-loop]: **Agents-support-humans framing**: every
    agent in the fleet is operated by a human practitioner
    in production. For agriculture specifically, this
    includes the explicit applicator approval gate on the
    Spray Drone agent — applications never execute without
    explicit licensed-applicator sign-off. This is the
    agriculture parallel to the cybersec "no auto-containment"
    third rail and the LEO "no autonomous tactical decisions"
    third rail.
    *Defined in*: `docs/scenarios/README.md` ("AI supports
    humans, it doesn't replace them" section);
    `docs/scenarios/agriculture/README.md` ("The 'humans in
    production' framing" section); each role description in
    `docs/scenarios/agriculture/disease-detection-hollander-farms.md`
    has an "In production" sidebar.
    *Visible in the demo*: agent disclaimer in Segment 1; the
    Spray Drone applicator approval gate in Segment 5 is the
    central demonstration of the principle; "what you cannot
    say" section is the verbal discipline that keeps this
    framing intact.
    *Not a tracked feature* — this is positioning, not code.

[^data-ownership]: **The data ownership story**: unique to
    the agriculture scenario among the demos. Farmers are
    deeply concerned about who owns and monetizes their farm
    data. MemoryHub's framing is that the operation controls
    the deployment, owns the memories, and chooses where data
    is stored, who reads it, and when it's deleted. This
    addresses the audience's biggest concern about adopting
    new ag-tech.
    *Defined in*: `docs/scenarios/agriculture/README.md`
    ("The data ownership concern" section);
    `docs/scenarios/agriculture/disease-detection-hollander-farms.md`
    ("Agents support humans" section, data ownership
    paragraph).
    *Visible in the demo*: opening framing in Segment 1,
    audit trail data ownership framing in Segment 6, closing
    pitch in Segment 8.
    *Not a tracked feature* — this is a deployment topology
    decision and a positioning claim that the deployment story
    must back up.

[^identity-triple]: **The owner/actor/driver identity model**:
    every memory operation involves three distinct identities.
    `owner_id` (who the memory belongs to, determines scope),
    `actor_id` (which agent performed the operation, always
    derived from authenticated identity), `driver_id` (on
    whose behalf, may equal actor_id for autonomous operation).
    *Defined in*: `docs/identity-model/data-model.md` ("The
    triple: owner, actor, driver" section). Maps to RFC 8693
    token exchange semantics and FHIR Provenance.
    *Tracked in*: GitHub issue #65 (schema migration adding
    `actor_id` and `driver_id` columns to MemoryNode), #66
    (plumbing through tools).
    *Visible in the demo*: agent registration in Segment 2,
    audit trail queries in Segment 6.

[^driver-id]: **Driver_id specifically — the on-whose-behalf
    concept**: identifies the principal an agent is acting
    for. In the agriculture scenario specifically, this is
    used to demonstrate that the same Agronomy agent serves
    Tom, Kelsey, and Linda across the team consultation —
    same actor_id, three different driver_ids in succession,
    each capture in the audit trail.
    *Defined in*: `docs/identity-model/data-model.md` ("Tool
    API changes" section).
    *Tracked in*: GitHub issues #65, #66.
    *Visible in the demo*: family team consultation moment
    in Segment 4, audit query 2 in Segment 6 ("everything
    done on behalf of Kelsey").

[^role-vs-person]: **Role-as-actor + person-as-driver
    distinction**: in the agriculture scenario, this is the
    family team consultation pattern. The Agronomy agent is
    a stable role consulted by multiple humans on the
    operation, each with their own driver_id. The role's
    accumulated knowledge serves all of them; the audit
    trail captures who was driving each conversation.
    *Defined in*: `docs/identity-model/data-model.md`
    (implicitly, via the actor/driver split). The
    family-team consultation pattern is the agriculture
    parallel to the clinical Charge Nurse handoff, the
    cybersec on-call rotation, and the LEO IC shift change.
    *Tracked in*: GitHub issues #65, #66.
    *Visible in the demo*: Tom/Kelsey/Linda consulting the
    Agronomy agent in Segment 4; audit query 1 in Segment 6
    payoffs the concept by showing the role's actions
    spanning all three consultations.

[^project-scope]: **Project-scope membership enforcement**:
    agents are members of specific projects (in the demo,
    `hollander-farms-2025`). Project-scope memories are
    readable/writable only by members. For multi-operation
    deployments (cooperatives, service providers), this is
    how each operation's memory stays bounded to its own
    team.
    *Defined in*: `docs/identity-model/authorization.md`
    ("Project membership enforcement (critical path)"
    section).
    *Tracked in*: GitHub issue #64 (the critical-path
    implementation work).
    *Visible in the demo*: agent registration in Segment 2;
    every project-scope memory write/read in Segments 3-7
    implicitly demonstrates the enforcement.

[^cross-season]: **Cross-season learning** — the central
    value-prop demonstration for the agriculture scenario,
    with multiple manifestations:
    (1) **Cross-season pattern recognition**: the Agronomy
    agent surfacing Kelsey's 2024 memory of Tom's
    observation about Field 7's microclimate.
    (2) **Multi-source convergence informed by prior
    season**: the diagnosis confirmation referencing past
    detection patterns.
    (3) **Operating philosophy as memory**: Tom's 2022
    kitchen-table conversation about fungicide intervention
    captured by Kelsey, surfaced when the team is making
    the same kind of decision three years later.
    (4) **Post-season learning capture**: explicit memories
    written for the next time tar spot is suspected on this
    operation.
    All four are forms of "what we've already learned that's
    relevant now," and they all live in the same memory
    category. Cross-season is the agriculture parallel to
    cross-incident learning in cybersec and public safety
    and cross-encounter narrative continuity in clinical.
    *Defined in*: `docs/scenarios/agriculture/README.md`
    ("What MemoryHub holds in this scenario");
    `docs/scenarios/agriculture/disease-detection-hollander-farms.md`
    (touchpoints 1-3, 7).
    *Tracked in*: emerges from project-scope membership
    (#64), schema (#65), tool plumbing (#66). No dedicated
    issue — this is the application-level pattern that the
    underlying features enable.
    *Visible in the demo*: the killer moment in Segment 3
    (Tom's 2024 takeaway memory), the operating philosophy
    moment in Segment 4 (Tom's 2022 conversation), explicit
    post-season learning capture in Segment 7.

[^narrative-context]: **Narrative context memory category**:
    the soft, unstructured operational and historical
    knowledge that doesn't fit in field data tables or
    variable-rate prescriptions. The reasoning behind
    intervention decisions, the operating philosophy of the
    operation, the lessons learned in narrative form, the
    cross-season trends in practitioner language.
    *Defined in*: `docs/scenarios/agriculture/README.md`
    ("What MemoryHub holds in this scenario");
    `docs/scenarios/agriculture/disease-detection-hollander-farms.md`
    (multiple touchpoints).
    *Tracked in*: not a discrete feature — emerges from
    generic `write_memory` + project-scope. The *category*
    is a positioning choice; the implementation is just
    memory storage.
    *Visible in the demo*: post-season lesson capture in
    Segment 7; narrative reasoning surfaced throughout the
    diagnosis and decision phases.

[^tribal-knowledge]: **Multi-generational tribal knowledge
    memory category**: unique to agriculture among the
    demos because of the multi-generational dimension.
    Senior farmers' understanding of how specific fields
    behave, what works in this microclimate, what the
    operating philosophy of the farm is. This kind of
    knowledge walks out the door when farmers retire or
    operations change hands. MemoryHub gives a structural
    mechanism for capturing it across generations.
    *Defined in*: `docs/scenarios/agriculture/README.md`
    ("What MemoryHub holds in this scenario" — second
    bullet, "Multi-generational tribal knowledge");
    `docs/scenarios/agriculture/disease-detection-hollander-farms.md`
    (touchpoints 1, 3, 5).
    *Tracked in*: not a discrete feature — same emergence
    as cross-season. Category positioning, not separate
    code.
    *Visible in the demo*: Tom's 2024 takeaway about
    Field 7's microclimate in Segment 3; Tom's 2022
    operating philosophy from the kitchen table in
    Segment 4; Tom's morning briefing preference in
    Segment 3.

[^contradiction]: **Contradiction detection** via the
    `report_contradiction` tool. In the agriculture
    scenario, two specific demonstrations: (1) drone
    multispectral interpretation suggesting drought stress
    versus soil sensor data ruling out drought stress
    during diagnosis confirmation, and (2) Weather agent
    self-correcting when its earlier forecast is
    contradicted by real-time on-farm wind data during the
    application.
    *Defined in*:
    `docs/scenarios/agriculture/disease-detection-hollander-farms.md`
    ("Contradiction moments" section). The
    `report_contradiction` tool already exists in the MCP
    server.
    *Tracked in*: existing tool.
    *Visible in the demo*: drought-stress contradiction in
    Segment 4, wind exceedance contradiction in Segment 5.

[^operational-memory]: **Agent-operational memory category**:
    the agent fleet writes memories about *itself* —
    operational lessons learned across operations. In
    agriculture, examples include cross-vendor coordination
    state (the Tractor agent's confirmation that no
    equipment will be in the spray field) and learned
    sensor quirks.
    *Defined in*: `docs/scenarios/agriculture/README.md`
    ("What MemoryHub holds in this scenario");
    `docs/scenarios/agriculture/disease-detection-hollander-farms.md`
    (touchpoint 6).
    *Tracked in*: not a discrete feature — emerges from
    `write_memory` + scope/owner conventions.
    *Visible in the demo*: brief mention in Segment 5 (the
    Tractor agent's coordination memory enabling cross-fleet
    safe operation during the spray flight).

[^data-curation]: **Sensitive-data curation pipeline**: when
    an agent attempts to write a memory containing sensitive
    data (yield data, lease arrangements, neighbor
    identification, crop financial information), the
    curation pipeline catches the attempted write and
    quarantines it before persistence. The agent then
    reformulates the memory to preserve operational meaning
    without the sensitive details. The pipeline itself is
    the same code as the healthcare PHI pipeline, the
    cybersec credential pipeline, and the LEO third-party
    identification pipeline, but the *patterns* are
    domain-specific. The agriculture patterns (yield data,
    lease info, neighbor identification) are not yet built
    — they would be a future issue, separate from #68
    (healthcare PHI patterns).
    *Defined in*:
    `docs/scenarios/agriculture/disease-detection-hollander-farms.md`
    ("Sensitive-data moments" section).
    *Tracked in*: pipeline stub via #68 for healthcare;
    agriculture patterns are a future issue (not yet
    filed).
    *Visible in the demo*: yield-data quarantine in Segment
    4 (Compliance agent attempts to write yield projection
    against multi-year averages).

[^audit]: **Audit log**: every memory operation is captured
    by `audit.record_event(...)` with both `actor_id` and
    `driver_id` recorded. For the demo, the persistence
    layer is a stub that writes structured log lines;
    future work will route through LlamaStack telemetry.
    For agriculture specifically, the audit log running on
    the operation's own infrastructure is the
    instantiation of the data ownership story.
    *Defined in*: `docs/identity-model/authorization.md`
    ("Audit logging — stub now, persistence later"
    section).
    *Tracked in*: GitHub issue #67 (audit logging stub
    interface), #70 (persistent audit log via LlamaStack
    telemetry).
    *Visible in the demo*: compliance recordkeeping in
    Segment 5, audit queries in Segment 6.

[^cli-provisioning]: **Agent generation CLI**: a static
    code-gen tool that takes a fleet manifest YAML and
    produces Kubernetes Secrets, the users ConfigMap, and
    the harness manifest needed to deploy and identify the
    demo's agent fleet. The CLI is the source of the ten
    agriculture agents seen in the demo.
    *Defined in*: `docs/identity-model/cli-requirements.md`
    (the full requirements doc for the CLI).
    *Tracked in*: GitHub issue #69 (build agent generation
    CLI for demo fleet provisioning).
    *Visible in the demo*: implicit in the agent fleet
    startup in Segment 2. Worth a one-liner mention if
    there's time and the audience is operationally curious
    ("the fleet you see was provisioned from a single YAML
    manifest — your operation's specific agents and roles
    are configured the same way").
