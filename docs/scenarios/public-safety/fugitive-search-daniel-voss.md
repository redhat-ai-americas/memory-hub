# Multi-Sensor Fugitive Search: Daniel Voss

A working scenario for MemoryHub's third demo, targeting a public
safety audience. Built around a six-hour multi-jurisdictional search
for an already-identified suspect in a non-fatal nightclub shooting,
with a fleet of ten agents that help the response team hold their
operational picture across sensor sources, jurisdictions, shift
changes, and prior incident learning.

## The phrase

> **MemoryHub holds the context that makes tactical decisions go well.**

That phrase is the entire frame for this scenario. Every sensor
correlation, every hypothesis update, every negative finding, every
tribal knowledge memory in this doc is in service of it. The
tactical decisions in this scenario are made by the human Incident
Commander and the supporting analysts. The agents help them hold
the operational context that determines whether those decisions
land well.

## Agents support humans, they don't replace them

This is critical to read before the rest of the scenario, and
critical to internalize for the LEO audience specifically:

**In production, every agent in this fleet is operated by a human
practitioner.** The Camera Network agent is the interface a CCTV
operator uses to recall what coverage has been canvassed and what
the team has already cleared. The Tip Line Triage agent is the
interface a tip line analyst uses to compare incoming tips against
the current operational picture. The Incident Commander agent is
the interface the IC running the search uses to hold the synthesized
picture across all sources. The Resource Dispatcher agent is the
interface the dispatcher uses to coordinate ground units against
the current best hypothesis.

For the demo, Claude (or whoever is running the harness) plays the
role of the entire response team. This is a demo necessity, not a
product claim. **The agents do not make tactical decisions on their
own.** They do not dispatch units autonomously. They do not assess
threats. They do not identify suspects. They do not engage in
predictive analysis of who is dangerous. They hold the operational
memory their human practitioners need to make those decisions well.

The audience for a LEO demo is more politically sensitive than the
clinical or cybersecurity audiences. Some attendees will hear "AI
in policing" and think about civil liberties concerns. Some will
hear it and think about catching bad guys faster. The framing must
work for both. The way it works is by being **rigorously honest
about who makes decisions** and by emphasizing that the audit trail
makes every decision *traceable to the human who made it*.

Specific language to use during the demo:

- "The Pattern Analyst agent helps the analyst surface what the
  team learned from prior searches with similar subject profiles"
- "The Incident Commander agent holds the current best hypothesis
  so the IC doesn't have to reconstruct it after every shift
  change"
- "Each agent is the practitioner's interface to the operation's
  shared memory"
- "Every action attributed to the human who took it"

Specific language to avoid:

- "Predictive policing" (any usage)
- "Autonomous detection" / "AI threat detection"
- "AI identifies the suspect" (the suspect is identified by
  humans before the agent fleet ever activates)
- "Facial recognition" (avoid prominent use even if the technology
  exists)
- "Automated decision-making"
- "Reduces officer involvement"

## MemoryHub vs. existing LEO systems

Public safety doesn't have a single dominant decision-support
paradigm the way healthcare has CDS. Instead, LEO operations use a
fragmented set of tools — CAD, RMS, GIS/mapping, LPR databases,
real-time crime centers, fusion centers — each doing one thing.
The boundary section in `docs/scenarios/public-safety/README.md`
walks through what each of those does. The short version: **CAD
dispatches the unit, GIS plots its location, RMS holds the
case file. MemoryHub doesn't try to be any of those.**

What MemoryHub holds is the **operational picture across time and
across sources** — the current best hypothesis, what reinforced it,
what contradicted it, what's already been cleared, what worked in
prior searches, what each sensor source has and hasn't covered. The
existing tools hold data; MemoryHub holds the team's working
understanding.

## Source material

This scenario is designed against publicly available frameworks
rather than a single document:

- **NIST/DOJ Incident Command System (ICS)** for the phase
  structure and command relationships
- **IACP best practice guides** for tactical search operations
- **DOJ COPS Office** materials on multi-agency coordination
- General procedural realism based on publicly reported active
  search operations (no specific real case is being replicated)

The subject archetype is synthetic but designed to be realistic
for a mid-sized city or county jurisdiction (not a small rural
town with no resources, not a major metro with a 200-officer
tactical division — somewhere in between).

**Critical disclaimer**: this scenario uses a fugitive who has
been **positively identified by humans** before the agent fleet
ever activates. Witnesses have given statements. Security camera
footage has been reviewed. A warrant has been issued. The agent
fleet's job is *locating* the subject, not identifying him. This
is a deliberate framing choice to keep the scenario clear of the
"AI identifies suspects" third rail.

## Subject archetype

**Daniel Voss** is a 28-year-old male identified as the suspect
in a non-fatal shooting at the Riverside District nightclub at
01:14 AM Saturday. Two victims were transported to the hospital
with gunshot wounds; both are in stable condition. Voss was
identified by multiple witness statements and high-quality
security camera footage that captured a clear view of his face,
clothing, and approximate height and build. Two other witnesses
named him by sight (he is locally known). A state warrant was
issued at 03:00 AM. Active multi-agency search begins at 03:30
AM, two hours and sixteen minutes after the initial incident.

What's known about Voss at the start of the search:

- Local resident, lives in a rented apartment 4.2 miles from the
  nightclub
- Drives a maroon 2014 Toyota Camry, plate identified
- History of two prior arrests, both for assault, both pleaded
  down to misdemeanors. No prior violent felonies.
- No known vehicle in his name beyond the Camry
- Family in the area: a brother in a neighboring county, an
  ex-girlfriend in town, a cousin two counties over
- Phone number known; carrier subpoena in progress for tower data
- Employed at a local auto repair shop until two weeks ago
  (recently terminated)

What's not known:

- Whether he is still in the city
- Whether he is on foot or has obtained another vehicle
- Whether he has changed clothes from the nightclub footage
- Whether he is armed (likely yes — the weapon was not recovered
  at the scene)
- Whether he is alone

Time pressure: he has been at large for two hours and sixteen
minutes when the search begins. The public safety risk continues
until he is apprehended. He is potentially armed and is being
treated as such.

The 6-hour search timeline gives the demo phases that map naturally
to the agent fleet's roles. Voss is plausibly within a 15-mile
radius of the nightclub when the search begins (rough rule of
thumb for foot/vehicle flight in that timeframe). The radius
expands as the search continues.

This archetype was chosen for several reasons. It activates the
entire agent fleet in a way no single role feels like padding. It
involves multiple jurisdictions (city PD, county sheriff,
neighboring city PD, state troopers — each has a role). It has
natural cross-incident learning moments (similar searches in the
past with similar subject profiles). It creates clear contradiction
opportunities (sensor source A says one thing, source B says
another). And critically, **the suspect is already identified** —
the agent fleet's job is to *find* him, not to *figure out who he
is*. This is the framing that keeps the scenario clear of the most
politically loaded territory.

## The agent fleet (10 roles)

Each agent is the human practitioner's interface to the
operation's shared memory. The "In production" sidebar on each
role makes explicit who operates the agent in real deployment.

### 1. Camera Network Agent

Operates the city and county camera infrastructure: CCTV at
public buildings, traffic cameras at major intersections,
business security camera feeds (with cooperation), and integrated
doorbell camera networks where available. Surfaces what's been
canvassed, what hits look promising, and what areas are blind
spots.

> **In production**: a CCTV operator in the city's real-time
> crime center chats with this agent during active searches,
> recalling what areas have been canvassed in this search and
> what the camera coverage gaps look like.

### 2. License Plate Reader (LPR) Agent

Operates fixed and mobile license plate reader networks. The
city and county have a mix of permanent LPR cameras at key
intersections plus mobile LPRs on patrol vehicles. Surfaces hits
on the subject's known plate and surfaces vehicles in the search
area that match descriptions of "vehicle of interest."

> **In production**: an LPR analyst in the real-time crime
> center chats with this agent, recalling what hits have come
> through and what the team has already followed up on.

### 3. Drone / Aerial Agent

Operates aerial assets: a county sheriff's UAV with thermal
imaging, requested mutual aid from a neighboring agency for
additional drone coverage, and (later in the search) a state
trooper helicopter for wider area coverage. Surfaces thermal
hits, areas covered, areas not covered, and asset availability
windows.

> **In production**: the UAS pilot or air operations coordinator
> chats with this agent, recalling what areas have been
> overflown, what thermal signatures have been investigated,
> and when battery rotations are scheduled.

### 4. Tip Line Triage Agent

Processes incoming citizen tips from the public. Tips come in
via phone, web form, and social media. Most are low-quality —
sightings that don't match the description, frequent
caller-tipsters, well-meaning misidentifications. A few are
genuinely actionable. The agent helps the tip line analyst
score credibility and surface the actionable ones quickly.

> **In production**: the tip line analyst on duty chats with
> this agent, comparing incoming tips against the current
> operational picture and the team's heuristics about tip
> credibility.

### 5. Pattern Analyst Agent

Performs behavioral and geographic pattern analysis based on the
subject's known habits, prior behavior, and the team's experience
with similar searches. Importantly, this is **not predictive
policing in any sense** — it's a pattern-matching surface for an
analyst whose job is exactly this kind of analysis already. The
agent helps the analyst recall what worked in prior searches,
not make predictive decisions.

> **In production**: a crime or intelligence analyst chats with
> this agent, recalling patterns from prior searches with
> similar subject profiles and surfacing what the team has
> learned about how this kind of subject typically evades.

### 6. Geographic Analyst Agent

Combines GIS data, terrain features, escape routes, transit
infrastructure, and known associate addresses into a geographic
picture of where the subject could plausibly be. Surfaces
high-probability areas, low-probability areas, and the rationale
for each.

> **In production**: a geographic or crime analyst chats with
> this agent, recalling the team's geographic reasoning across
> the search.

### 7. Multi-Agency Liaison Agent

Coordinates with cooperating agencies — neighboring jurisdictions,
state police, federal partners (if relevant), mutual aid. Holds
the team's understanding of which agencies are active, what
their assets are, what their constraints are, and how the
relationships work.

> **In production**: the liaison officer or operations chief
> chats with this agent, recalling the current state of
> inter-agency coordination, the assets each agency has
> committed, and the practical dynamics of working with each
> partner.

### 8. Incident Commander Agent

Holds the synthesized operational picture for the IC. Surfaces
the current best hypothesis, the reasoning behind it, the
contradicting evidence, and the team's current priorities.
Critical for shift changes and across long operations.

> **In production**: the incident commander running the search
> chats with this agent throughout the operation, recalling the
> evolving picture as new information comes in. Across a long
> operation with multiple shift handoffs, this agent is what
> holds operational continuity for the IC role.

### 9. Resource Dispatcher Agent

Coordinates ground units, K9 teams, and tactical resources
against the current best hypothesis. Surfaces unit availability,
location, current assignment, and the team's history of
successful and unsuccessful tasking decisions.

> **In production**: the dispatcher coordinating ground assets
> chats with this agent, recalling unit positions, assignments,
> and the team's collective awareness of which resources have
> been used most effectively for what kinds of tasks.

### 10. Public Information / Communications Agent

Coordinates communications with the public, media, and internal
agency leadership. Drafts BOLOs, media releases, public alerts,
and internal status briefings. Holds context about what
information has been released publicly, what's being held back
operationally, and who the key stakeholders for each
communication are.

> **In production**: the public information officer chats with
> this agent throughout the operation, recalling the
> communication state and the operational sensitivities around
> what gets released when.

The Cell Tower / Geolocation specialist mentioned in the README
placeholder is folded into the Pattern Analyst agent's role for
this scenario — modeling it as a separate agent would inflate the
fleet count without adding meaningful demo value. Cell tower data
is consulted during pattern analysis when legal authorities are
in place. The Social Media Monitor role is similarly folded into
the Tip Line Triage agent for the same reason. If the demo grows
beyond 10 agents, those become the natural additions.

## Workflow phases

Six phases tracking the search from initial notification to
apprehension. Each phase activates a subset of the agents and
produces specific memory touchpoints.

### Phase 1 — Initial response and fleet activation (03:30 - 04:00)

Active agents: all ten agents activate during this 30-minute
window as the search is organized.

The state warrant was issued at 03:00 AM. By 03:30, the
multi-agency search is being organized. The Incident Commander
is named (Sergeant Hammond from the city PD). The Liaison agent
contacts neighboring jurisdictions. The Camera Network and LPR
agents start surveying their networks for any retrospective
evidence of the subject's movements after the shooting. The
Public Information agent prepares the initial BOLO. The
Resource Dispatcher catalogs available units across agencies.

This phase is lightweight on memory writes — it's mostly setup.
The important thing is that the fleet activates and starts
holding the operational picture.

### Phase 2 — Initial canvass and hypothesis formation (04:00 - 05:30)

Active agents: Camera Network, LPR, Tip Line Triage, Pattern
Analyst, Geographic Analyst, Drone (deployment around 05:00),
Incident Commander, Resource Dispatcher

The first ninety minutes of active search. Camera Network
reviews retrospective footage from cameras near the nightclub
and along plausible escape routes. LPR pulls hits on the
subject's known vehicle. Pattern Analyst reads memories from
prior similar searches and forms an initial geographic
hypothesis. Tip line starts taking calls from the public after
the BOLO goes out at 04:30. The Drone agent's first asset (the
county sheriff's UAV) is deployed at 05:00 over the highest
probability search area.

The Incident Commander writes the first hypothesis memory at
05:00, anchored to what the agents have surfaced.

### Phase 3 — Lead development and false-lead clearance (05:30 - 07:00)

Active agents: all ten

The most active phase. Tips are flowing in. Some are followed
up; most are cleared as low-credibility or non-matching. The
camera network is canvassing in real time. LPR is checking
vehicles in the search area. The drone is searching open
terrain. Negative findings start accumulating — "we cleared
the Riverside neighborhood, no match." The Incident Commander
agent updates the working hypothesis as new evidence comes in
and old leads are cleared.

This is where the contradiction surfaces appear. Two tip
callers report contradictory directions of travel. An LPR hit
on the Camry doesn't match the subject's pattern. A drone
thermal hit turns out to be a deer.

### Phase 4 — Convergence (07:00 - 08:30)

Active agents: all ten

Multiple sensor sources begin to converge on a probable
location. A doorbell camera catches what looks like the subject
walking northbound on a residential street at 06:42. The Camera
Network agent surfaces this hit. The Pattern Analyst overlays
it on the working hypothesis and notes that it's consistent
with the subject heading toward a specific area where his
cousin's residence is located (already under surveillance). The
Geographic Analyst confirms the route is plausible on foot from
his last known location. The Incident Commander updates the
working hypothesis: the subject appears to be moving toward his
cousin's residence, possibly seeking shelter.

The Resource Dispatcher pre-positions tactical assets near the
area. The Liaison agent confirms with the cousin's jurisdiction
(neighboring city PD) that surveillance is in place. The
Multi-Agency Liaison coordinates the tactical approach.

### Phase 5 — Apprehension (08:30 - 09:00)

Active agents: Resource Dispatcher, Drone, Incident Commander,
Camera Network, Liaison

A tactical team approaches the cousin's residence. The drone
overflies in support. The subject is observed entering a
detached garage behind the residence. Tactical team makes
entry. Subject is arrested without incident at 08:47. The
firearm is recovered.

### Phase 6 — Debrief and after-action capture (next day)

Active agents: Incident Commander, Pattern Analyst, all
practitioners writing post-incident lessons

The next day, the team holds an after-action review. New
memories are written that will be read by the agent fleet
during the next similar search. Specific lessons captured:

- The doorbell camera detection at 06:42 was the inflection
  point, not the LPR hits. The team should weight residential
  doorbell camera networks higher in similar searches going
  forward.
- The cousin's residence was correctly identified as a high
  probability hide location 90 minutes before the subject was
  observed there. The Pattern Analyst's "subject seeks shelter
  with extended family" pattern from prior similar searches
  was validated.
- The early decision to clear the Riverside neighborhood
  freed resources that were needed during the convergence
  phase. The negative findings discipline paid off.
- Inter-agency coordination with the neighboring city PD took
  18 minutes from initial contact to surveillance in place.
  Goal for next time: under 15 minutes. The Liaison agent
  should pre-cache known contacts for faster activation.

These memories will be available the next time the team runs
a similar search.

## Memory touchpoints

These are the specific memory operations the demo will showcase.
Every example below is **operational state, hypothesis tracking,
negative findings, cross-incident pattern memory, or agent-fleet
operational learning** — none of it duplicates CAD, RMS, GIS, or
LPR database functionality.

### Touchpoint 1: Initial hypothesis formation (Phase 2)

The Incident Commander agent writes the first hypothesis memory
at project scope around 05:00 AM, after the initial canvass:

> "Initial hypothesis at 05:00. Subject Daniel Voss is most
> likely on foot within a 4-mile radius of the nightclub.
> Vehicle (maroon Camry) has not been seen on LPR since 01:38
> AM, suggesting he abandoned it within the first 30 minutes.
> Pattern Analyst notes prior subjects with similar profiles
> typically seek shelter with extended family within 6-12
> hours. Geographic Analyst notes three known associate
> addresses in plausible walking distance. Confidence: 0.55.
> Working hypothesis to be updated as evidence comes in."

The hypothesis carries through the rest of the search. Every
subsequent agent reads it. Every contradicting or reinforcing
piece of evidence updates it.

**Why this is the load-bearing memory**: in current practice,
the working hypothesis lives in the IC's head and on a
whiteboard. Shift changes lose half of it. New information that
arrives an hour later isn't connected back to the original
reasoning. MemoryHub holds the hypothesis explicitly with its
provenance and updates it as a versioned memory.

### Touchpoint 2: Negative findings (Phase 3)

The Camera Network agent writes a negative-finding memory at
project scope around 06:00 AM:

> "Riverside neighborhood camera coverage canvassed 14:00 -
> 15:30 [05:00 - 05:30 AM] with full coverage of all major
> exits and primary residential corridors. No match for
> subject description. Confidence high — neighborhood is well
> instrumented and we had eyes on every exit. Don't re-task
> ground units to this area without new evidence. Camera
> coverage map attached for the next operator on this incident."

The Resource Dispatcher reads this memory and stops sending
ground units to Riverside. The IC is freed from having to
re-derive "did we already check that area?" The negative
finding persists across the rest of the search.

**Why it pulls its weight**: this is the single biggest pain
point in active searches. In current practice, negative
findings get lost — the team clears an area, and then 90
minutes later a new IC takes over and re-tasks units to the
same area. Multi-hour searches routinely waste 20-40% of
their resources re-checking already-cleared territory.
MemoryHub turns this into a structural fix.

### Touchpoint 3: Cross-incident pattern recognition (Phase 2)

When the Pattern Analyst agent forms its initial geographic
hypothesis around 04:30, it surfaces a memory written 14 months
ago after a different search:

> "From IR-PS-2024-031 (Marshall County multi-jurisdictional
> search, January 2024). Subject profile: male, late 20s,
> local, prior contact with the system, fled on foot from a
> non-domestic violent incident, vehicle abandoned within 30
> minutes, no known affiliation with organized criminal
> networks. The subject in that search was found 18 hours
> later in a detached outbuilding behind an extended family
> member's residence, 6.2 miles from the initial scene.
> Lesson for similar profiles: prioritize known extended
> family addresses in geographic analysis, especially
> outbuildings (garages, sheds) rather than primary residences
> where surveillance is more obvious."

The Pattern Analyst weights extended family addresses
accordingly. The Geographic Analyst surfaces the cousin's
residence as a high-probability location at 04:45, nearly four
hours before the subject is observed there.

**Why it works as a demo moment**: this is the equivalent of
the cybersecurity demo's "we've seen this before" moment.
Every experienced LEO investigator has had the experience of
"this reminds me of something — what was it?" In current
practice, that recall is unreliable and depends on whether
the right person is in the room. MemoryHub makes it
structural.

### Touchpoint 4: Tribal knowledge memory (Phase 1)

Early in the search, the Tip Line Triage agent reads a memory
written months ago about the Incident Commander:

> "When IC Sergeant Hammond is running a search, she prefers
> tip line items pre-scored for credibility before they hit
> her queue. She specifically does not want low-credibility
> items unless three or more independent reports converge on
> the same location. This is a personal preference based on
> her experience that high-volume tip queues drown the IC's
> attention. Default to filtering for her commands."

The Tip Line Triage agent applies this filter for the
duration of Sergeant Hammond's command. When the shift changes
later, the agent will check whether the next IC has different
preferences.

**Why it's the right kind of memory**: this is exactly the
soft tribal knowledge that matters operationally but lives
nowhere in current systems. It's not in CAD. It's not in any
SOP. It walks out the door when Hammond retires.

### Touchpoint 5: Agent-operational memory (Phase 2)

The Drone agent reads a memory it wrote to itself two
operations ago:

> "Operational lesson from PS-2024-088: when running thermal
> coverage of wooded terrain in cold weather, deer signatures
> consistently look like seated humans on the first pass. We
> wasted 22 minutes investigating a thermal hit that turned
> out to be a deer. Rule: in cold-weather wooded terrain,
> require either a second visual confirmation pass or a
> ground team check-in before flagging a thermal hit as
> 'probable subject.' This rule applies to the county
> sheriff's UAV thermal — different sensors may have
> different characteristics."

When the Drone agent gets a thermal hit at 06:15 in the
wooded park area, it applies this rule: the hit is reported
as "thermal signature pending confirmation," not "probable
subject." The IC is not pulled away from the working
hypothesis to investigate a likely deer.

**Why it's the most novel touchpoint**: this is the agent
fleet learning about its own operational quirks across
incidents. No human writes this memory; no human reads it
directly. The fleet self-corrects for false positives that
would otherwise waste IC attention.

### Touchpoint 6: Multi-source convergence (Phase 4)

At 06:42, a doorbell camera registers what looks like the
subject walking northbound on a residential street. The
Camera Network agent surfaces the hit at project scope. The
Pattern Analyst reads it and immediately writes a memory
linking it to the working hypothesis:

> "Doorbell hit at 06:42 on Maple Street is consistent with
> the subject heading northbound from his last known position
> at the abandoned vehicle location. Walking pace and
> direction match. Distance 1.8 miles in approximately three
> hours, accounting for likely evasive routing — plausible.
> If continued on this trajectory, he reaches the vicinity
> of his cousin's residence (2nd Street, neighboring
> jurisdiction) within the next 45-60 minutes. Recommend
> Geographic Analyst confirm walkability of the route and
> Liaison agent confirm surveillance is in place at the
> cousin's residence."

This memory triggers the convergence phase. Geographic
Analyst confirms the route. Liaison confirms surveillance.
Resource Dispatcher pre-positions tactical assets. The
working hypothesis updates with a much higher confidence
score (0.78 from 0.55).

**Why it's the operational payoff**: the team's working
understanding updates in real time as evidence converges.
In current practice, this kind of multi-source convergence
happens slowly because the analyst who would notice the
linkage isn't necessarily the analyst who sees the doorbell
hit. MemoryHub makes the linkage structural.

### Touchpoint 7: Post-incident learning capture (Phase 6)

The day after the search, the team writes new memories
explicitly for the next operation:

> "Lesson from PS-2024-184 (Voss search): the doorbell camera
> network was the inflection point, not the LPR hits.
> Residential doorbell camera coverage in the city has grown
> significantly in the past 18 months. The Camera Network
> agent should treat doorbell networks as a primary source
> for foot-based searches in residential areas, not just as
> supplementary coverage. The convergence in this search
> happened because we caught a doorbell hit at 06:42 that
> would have been missed in our 2022 SOP."

These memories will be read during the next similar search.
The fleet's hypothesis weighting and search prioritization
will reflect this lesson.

## Contradiction moments

Two specific moments where one agent's evidence contradicts
another's, and the team uses MemoryHub's contradiction
detection to surface and resolve the disagreement.

### Contradiction 1: LPR hit vs. tip caller location

**Setup** (Phase 3, around 06:00 AM): the LPR agent writes a
memory at project scope:

> "LPR hit at 05:58 on the subject's known plate (maroon
> Camry) at the intersection of Highway 14 and Rural Route
> 7, eastbound. Confidence: confirmed plate match."

**Contradiction** (Phase 3, around 06:10): the Tip Line
Triage agent writes a memory and calls
`report_contradiction`:

> "Tip caller at 06:08 reports a male matching the subject
> description on foot at the bus station downtown, four
> miles from the LPR hit location. Caller describes
> clothing matching the BOLO. Caller has previously called
> in two tips that were credible. The tip and the LPR hit
> are physically inconsistent — the subject can't be in
> both places at the same time. Either someone else is
> driving the Camry, or the foot sighting is mistaken
> identity. Need IC adjudication."

**Resolution**: the Incident Commander reads both memories.
Decision: dispatch ground units to confirm the bus station
sighting (higher likelihood of being the subject given the
foot trajectory hypothesis) while flagging the LPR hit as
possible vehicle theft or unauthorized use. The LPR hit
turns out to be a cousin's husband driving the Camry —
unrelated to the subject's location. The bus station
sighting turns out to be misidentification, but the
adjudication process correctly directed the higher-priority
investigation first.

**Why this contradiction matters**: the disagreement is
real and it's the kind of thing that frequently happens in
multi-source operations. In current practice, the IC has to
mentally hold both conflicting reports and adjudicate
without a record. MemoryHub captures the disagreement, the
adjudication, and the eventual resolution in a way that
survives shift changes and informs after-action review.

### Contradiction 2: Pattern Analyst hypothesis vs. Geographic Analyst constraints

**Setup** (Phase 2, around 04:45 AM): the Pattern Analyst
writes a memory:

> "Recommended high-priority search areas based on subject
> profile and prior similar incidents: (1) cousin's
> residence in neighboring jurisdiction, (2) ex-girlfriend's
> residence in city, (3) brother's residence in adjacent
> county. All known extended family addresses. Subject
> profile suggests these are highest probability shelter
> locations within first 12 hours."

**Contradiction** (Phase 2, around 04:55 AM): the
Geographic Analyst writes a memory and calls
`report_contradiction` on the Pattern Analyst's
recommendation:

> "Geographic constraint check on Pattern Analyst's
> recommendations. Cousin's residence and brother's
> residence are both reachable on foot within 12 hours from
> the nightclub. Ex-girlfriend's residence is 11 miles away
> through urban terrain with limited walking infrastructure.
> Reaching her residence on foot in 6 hours requires either
> a vehicle (which we believe was abandoned) or public
> transit (limited at this hour) or a ride. Recommend
> downgrading the ex-girlfriend's residence from 'high
> priority' to 'medium priority — investigate only if
> evidence of vehicle or transit use emerges.'"

**Resolution**: the Pattern Analyst reads the geographic
constraint and updates its recommendation. The
ex-girlfriend's residence drops to medium priority. The
search resources are concentrated on the cousin's residence
and the brother's residence, which is where the convergence
eventually happens.

**Why this contradiction matters**: it's a *constructive*
disagreement. The Pattern Analyst was right about behavioral
profile; the Geographic Analyst was right about physical
feasibility. Combining them gave a better picture than
either alone. MemoryHub captured the disagreement and the
resolution in a way that any future search can learn from.

## Sensitive-data moments

Two specific moments where an agent attempts to write a memory
containing sensitive data and the curation pipeline catches it.

### Sensitive moment 1: Innocent third-party identification

The Camera Network agent identifies a vehicle at 05:42 in the
search area that matches a generic description (red sedan).
The agent attempts to write:

> "Vehicle at 05:42 at Oak Street and 4th Avenue: red 2018
> Honda Accord, plate 7BVJ391, registered to Maria Santos,
> 1247 Pine Street. Vehicle present in search area —
> investigate."

The curation pipeline catches it. Maria Santos is an
**uninvolved third party** who happens to drive a vehicle
matching a generic description. Her name, plate, and address
should not be persisted into shared memory just because her
car was in the search area. The pipeline quarantines and
the agent rewrites:

> "Vehicle at 05:42 at Oak Street and 4th Avenue: red 2018
> Honda Accord. Initial check: not the subject's known
> plate. Owner verification cleared by ground unit at 05:48.
> Not a match. No further action."

The investigative fact is preserved (we checked, it wasn't
him). The uninvolved person's identifying details are not
persisted — they exist in the operational systems
(verification check) where appropriate access controls apply,
but they don't bleed into the broader operational memory.

**Why this is the right kind of curation**: in active
searches, an enormous amount of innocent-third-party
identifying data flows through the operation. License plates
of cars in the search area. Faces on doorbell cameras.
Addresses where ground units knock on doors. Most of those
people have nothing to do with the subject. Their personal
information should not become part of the persistent
operational memory. The curation pipeline enforces this at
the moment of writing, not as an after-the-fact cleanup.

### Sensitive moment 2: Source/method exposure

During tip triage, the Tip Line Triage agent attempts to write
a memory about a particularly valuable tip:

> "High-credibility tip at 06:32 from confidential informant
> Robert Chen (CI #4471). Chen reports seeing the subject
> entering a vehicle at the corner of 8th and Maple
> approximately 30 minutes ago. Chen is a long-time CI
> handled by Detective Morales and has been reliable across
> multiple operations."

The curation pipeline catches the combination of CI name +
CI number + handler identification. **Source identification
in operational memory is a serious tradecraft violation** —
it could expose the CI to retaliation if the memory is ever
exfiltrated, and it bleeds source information into a context
that doesn't need to know it.

The pipeline quarantines and the agent rewrites:

> "High-credibility tip at 06:32 from a confidential source
> with established reliability. Source reports seeing the
> subject entering a vehicle at the corner of 8th and Maple
> approximately 30 minutes ago. Source identity managed
> through normal CI handling procedures. Treat tip as
> high-credibility and prioritize for follow-up."

The operational fact is preserved. The source's identity is
not. The tip is acted on with the right credibility weight,
but the source's name, identifier, and handler are not
exposed in the memory layer.

**Why this matters**: source protection is one of the most
serious ethical and operational concerns in LEO work. The
audience will respond strongly to a demo moment that shows
the system actively defending against source exposure. This
is a category where MemoryHub's curation pipeline is doing
exactly what trained tradecraft would teach an analyst to do
manually — and doing it consistently rather than depending
on an analyst remembering to be careful at 06:32 AM during a
fast-moving operation.

## What's drawn from sources vs. what's invented

Honest disclosure of what the demo invents.

**Drawn from real frameworks and practices**:

- The phase structure (response → canvass → lead development →
  convergence → apprehension → after-action) loosely maps to
  Incident Command System operational period structure
- The role list reflects real LEO operational structures across
  jurisdictions
- The general dynamics of multi-source canvassing, hypothesis
  formation, and resource allocation are realistic for how
  active searches actually run
- The negative-findings problem (re-tasking units to already-
  cleared areas) is a documented and widely acknowledged
  operational pain point
- The role of doorbell camera networks as an emerging primary
  source for foot-based searches is real and growing
- Confidential informant handling and source protection
  practices are real

**Invented for this scenario**:

- The subject (Daniel Voss) and every detail about him
- The jurisdiction and every detail about it
- All officer names, including Sergeant Hammond, Detective
  Morales, and the synthetic CI
- All specific timestamps, addresses, and vehicle plates
- All quoted memories
- The specific contradictions and their resolutions
- The IR-PS-2024-031 prior search reference

The point is realistic *shape* that a LEO professional would
recognize without finding any single detail wrong.

**Sidestepped entirely**:

- Specific facial recognition technology (politically loaded
  and legally constrained in many jurisdictions)
- Cell tower geolocation specifics (legal authorities vary by
  state and federal context — getting this wrong would
  damage credibility)
- Specific federal agency capabilities (would either understate
  or overstate, both are bad)
- Use-of-force decisions (not what the demo is about)
- Anything that could be confused with predictive policing or
  bias-amplification scenarios

## Open questions

1. **Should the Multi-Agency Liaison agent be modeled, or
   folded into the Incident Commander agent?** The current
   design treats it as a separate role because multi-agency
   coordination is operationally distinct from running the
   search itself. An IC running a single-agency search would
   not need a separate Liaison agent. For the demo, the
   multi-jurisdictional aspect is part of the value
   demonstration, so the Liaison agent stays.

2. **How explicit should the cousin's residence search be in
   the demo?** Searching a relative's home for a fugitive is
   operationally common but emotionally fraught — it involves
   ground units approaching the home of someone who is *not*
   the subject and may be entirely uninvolved. The demo
   should treat this with care. The current design
   emphasizes that the cousin's home is *under
   surveillance*, not subject to a no-knock raid. The
   apprehension happens in a detached garage, not in the
   primary residence. This deliberately avoids the most
   politically loaded aspect of the search.

3. **Demo length and pacing.** The full 6-hour search would
   take 6 hours to play out in real time. The demo
   compresses this to 15-20 minutes by jumping between
   phases. We should pre-pick which 4-5 memory touchpoints
   land in the live demo and which we mention in passing.

4. **The "predictive policing" framing risk.** The Pattern
   Analyst agent is doing pattern matching against prior
   incidents, which sounds adjacent to predictive policing
   to a hostile listener. The framing must emphasize that
   this is *case-specific recall* of how prior similar
   searches resolved, not *predictive identification* of
   suspects or risk scoring of individuals. This needs to
   be drilled into the demo language and tested with a
   skeptical reviewer before going live.

5. **LEO SME validation.** Same concern as the clinical and
   cybersecurity scenarios: we should have a working LEO
   practitioner (ideally someone who has run multi-agency
   searches) review this scenario before demoing it.
   Operational mistakes that a LEO professional would catch
   immediately will undermine the demo's credibility and
   open the door to "this team doesn't understand our work"
   dismissals.

6. **The subject's race and demographic details.** The
   scenario deliberately doesn't specify Voss's race or
   ethnicity. This is intentional — bringing race into a
   synthetic LEO scenario is unnecessary and risks
   distracting from the point. If asked directly during
   Q&A, the answer is "the scenario doesn't specify because
   it's not relevant to the operational story we're
   telling."

7. **Animation visualization for the LEO scenario**. The
   stretch animation idea (circles with pulses going to and
   from the central core) lands particularly well here
   because the multi-source convergence is the most
   visually compelling moment — five sensor agents pinging
   the central memory with their findings, the IC agent
   integrating, ground units repositioning in response. If
   the animation is built, this scenario benefits more from
   it than the clinical or cybersec scenarios do.
