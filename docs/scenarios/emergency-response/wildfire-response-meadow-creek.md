# Multi-Day Wildfire Response: Meadow Creek Fire

A working scenario for MemoryHub's fifth demo, targeting an
emergency response audience. Built around a synthetic three-day
wildfire incident in the Sierra foothills with a wind-shift event
that threatens a small mountain community, with a fleet of ten
agents that help the response team hold their operational picture
across operational period handoffs, multi-agency coordination, and
prior incident learning.

## The phrase

> **MemoryHub holds the context that makes incident decisions go well.**

That phrase is the entire frame for this scenario. Every cross-period
memory, every multi-source convergence, every IC decision point,
every operational lesson in this doc is in service of it. The
incident decisions in this scenario are made by the human Incident
Commander, the Operations chief, the Structure Protection Specialist,
the Liaison Officer, and the rest of the command staff. The agents
help them hold the context — across operational periods, across
agencies, across prior incidents — that determines whether those
decisions land well.

## Agents support humans, they don't replace them

This is critical to read before the rest of the scenario, and
emergency response is the highest-stakes domain in the platform's
demo set:

**Emergency response is defined by rapid life-safety decisions made
under uncertainty.** The IC decides when to issue an evacuation
order. The Operations chief decides which divisions get which
resources. The Structure Protection Specialist decides which
structures are defensible. The Public Information Officer decides
what to tell the community and when. None of these decisions can
ever be made autonomously by an AI agent — the legal, ethical,
professional, and cultural constraints all point the same way.

**In production, every agent in this fleet is operated by a human
practitioner in a real ICS position.** The Satellite Imagery agent
is operated by the intelligence section or the GIS specialist
(GISS). The Weather agent is operated by the Incident Meteorologist
(IMET) or the Fire Behavior Analyst (FBAN). The Drone agent is
operated by the UAS pilot. The Resource Allocation agent is
operated by the Resources Unit Leader (RESL). The Evacuation
Coordinator agent is operated by the Operations chief or branch
director coordinating with the sheriff. The Structure Defense
agent is operated by the Structure Protection Specialist (SPRO).
The Multi-Agency Liaison agent is operated by the Liaison Officer
(LOFR). The Incident Commander agent is operated by the IC. The
PIO agent is operated by the Public Information Officer.

For the demo, Claude (or whoever is running the harness) plays
the role of the entire response team. This is a demo necessity,
not a product claim. **The agents do not make incident decisions.**
They do not issue evacuation orders. They do not commit crews to
assignments. They do not triage structures. They do not score
people or properties by risk. They hold the operational and
historical memory the response team needs to make those decisions
well.

The audience for an emergency response demo is operationally
sophisticated and immediately allergic to vendor pitches that
sound like they want to take over decisions from trained
practitioners. The framing must respect the IMT structure, use
ICS vocabulary correctly, and never imply that the technology is
making the call.

Specific language to use during the demo:

- "The IC agent helps the IC hold the operational picture across
  the operational period handoff"
- "The Resource Allocation agent surfaces unit availability and
  prior tasking history so the Operations chief has the
  information for the assignment decision"
- "The Structure Defense agent surfaces what the team learned
  about defensibility on this fuel type in prior incidents — the
  Structure Protection Specialist makes the triage call"
- "Each agent is the practitioner's interface to the incident's
  shared memory"

Specific language to avoid:

- "AI predicts structure loss" / "AI predicts evacuation needs"
- "Automated evacuation"
- "Autonomous resource dispatch"
- "AI-driven incident management"
- "Smart emergency response"
- "Replaces command staff"
- "AI fire behavior prediction" used as ground truth (the
  audience knows fire behavior models fail)

## MemoryHub vs. existing emergency response systems

The audience for this demo has a stack. They have CAD. They have
resource ordering systems (ROSS, IROC, state equivalents). They
have GIS platforms (mostly Esri ArcGIS). They have EOC software
(WebEOC, Veoci, Knowledge Center). They have IAP-software
(eIAP, IAPS). They have notification systems (Everbridge, AtHoc,
IPAWS). The pitch must be unambiguous that MemoryHub is
*complementary* to all of them.

### What existing emergency response systems do (we don't try to do this)

In a modern Type 2 or Type 1 incident, the existing stack
handles:

- **CAD**: call intake, unit dispatching, status tracking
- **Resource ordering** (ROSS, IROC, state systems): formal
  resource requests, ordering, tracking, demobilization
- **GIS / mapping**: incident perimeter visualization, division
  layouts, structure defense maps, common operating picture
- **EOC software**: cross-agency coordination, status updates,
  resource requests at the EOC level
- **IAP-software**: Incident Action Plan generation, ICS form
  completion, briefing materials
- **Common Operating Picture (COP) platforms**: TAK-based
  tactical awareness, blue force tracking
- **Notification platforms**: public alerting, evacuation
  notifications via IPAWS

These do dispatch, resource ordering, visualization, IAP
generation, cross-agency coordination, and public notification.
**MemoryHub does not try to be any of them.**

### What MemoryHub holds in this scenario

The things existing emergency response systems can't easily hold
or don't try to hold:

- **Operational period handoff state in narrative form** —
  what the outgoing IC and command staff know that doesn't fit
  in the IAP document. The tried approaches that didn't work,
  the field-observed behavior that contradicted modeling, the
  team's working interpretation of why certain divisions are
  going better than expected and others worse.
- **Cross-incident learning** — fire behavior, terrain
  dynamics, evacuation route reliability, structure defense
  outcomes from prior incidents on similar fuel types and
  similar terrain.
- **Multi-agency tribal knowledge** — the soft dynamics of
  working with specific cooperators that aren't in any formal
  SOP.
- **Real-time hypothesis state** — the team's current best
  understanding of fire behavior, weather, and threat
  picture, with confidence and what reinforced or
  contradicted it.
- **Negative findings** — divisions that have been cleared,
  threats that have been ruled out, leads that have been
  followed and closed.
- **Per-IC and per-IMT preferences** — operational style
  preferences that shape how the agents serve different
  command staff across the incident's lifetime.
- **Agent-fleet operational state** — sensor coverage gaps,
  drone battery rotation windows, asset availability windows.

The relationship is **complementary**. CAD dispatches the unit.
The IAP captures the formal plan. GIS visualizes the picture.
EOC software coordinates across agencies. **MemoryHub holds the
working memory of the incident** — what the night-shift IC
needs to know that didn't fit in the IAP briefing format.

## Source material

This scenario is designed against publicly available frameworks:

- **NIMS / ICS** doctrine for the organizational structure,
  position titles, and operational period concept
- **NWCG (National Wildfire Coordinating Group) publications**
  — the IRPG (Incident Response Pocket Guide), the Fireline
  Handbook, fire behavior reference materials
- **NFPA 1144 / 1141** for structure protection standards in
  wildland-urban interface incidents
- **Federal Wildland Fire Policy** materials for the broad
  coordination context

The incident is synthetic but designed to be realistic for a
mid-sized wildfire in the Sierra Nevada foothills, similar in
shape and scale to many incidents that have occurred in
California, Oregon, and Nevada in recent fire seasons. The
scenario does **not** replicate any specific real fire and
should not be confused with one.

## Incident archetype

**The Meadow Creek Fire** is a wildland fire in mixed
timber/chaparral terrain in the western Sierra Nevada foothills.
The location:

- **Origin**: a downed power line on a remote forest road, Day
  0 afternoon (approximately 14:30)
- **Initial size**: ~15 acres at first detection by satellite
- **Growth pattern**: Day 1 morning ~250 acres, Day 1 evening
  ~800 acres, Day 2 evening ~1,800 acres (after the wind-shift
  event)
- **Terrain**: rolling foothills, 40-60% slopes in places,
  mixed ponderosa and chaparral, several small drainages
- **Adjacent values at risk**: a small mountain community
  called Meadow Creek (population approximately 280, mostly
  permanent residents with some vacation homes), a state
  highway connecting the community to the valley below, a
  regional water utility transmission line, several
  recreational sites

**The team**:

- **Day 0 - Day 1 evening**: Type 3 incident, local agency
  (county fire) running it with Type 3 IC named Sergeant
  Hammond (a long-time county fire BC who has run dozens of
  Type 3 incidents)
- **Day 1 evening - Day 3**: Type 2 IMT activated and assumes
  command. IC is Cynthia Park (a state-trained Type 2 IC).
  Day shift and night shift command staff established.
- **Cooperating agencies**: USFS (the fire is on federal
  land), CalFire (state coordinator), Meadow Creek Volunteer
  Fire Department (closest local resource), county sheriff
  (evacuation authority), county OES, Red Cross (sheltering),
  state highway patrol (highway closures), regional water
  utility (infrastructure protection), neighboring county
  fire departments (mutual aid)

**The scenario event for this demo**: a wind shift on Day 2
evening pushes the fire toward the Meadow Creek community.
The forecast called for the wind shift at 21:00 with gusts up
to 25 mph. At 19:30, the wind shift arrives 90 minutes early
and stronger than forecast — gusts of 35 mph from the
southwest, pushing the fire over a containment line on the
east flank and making a run toward the community. The team has
to coordinate evacuation, structure defense, and resource
reallocation in real time over the next 4-6 hours.

The demo focuses on the period from **Day 2 morning** (start of
the operational period that includes the wind shift event)
through **Day 3 morning** (the operational period handoff after
the wind shift event has been managed). This captures one full
operational period, the wind shift dynamics, the multi-agency
coordination during a fast-moving event, and the handoff to the
next operational period.

Time pressure: when the wind shift arrives 90 minutes early, the
team has approximately 60-90 minutes to issue evacuation orders,
pre-position structure defense, and coordinate with the sheriff
on the order before the fire reaches the community boundary.

## The agent fleet (10 roles)

Each agent maps to a real ICS position. The "In production"
sidebar names the position and what the practitioner does.

### 1. Satellite Imagery Agent

Pulls satellite-based fire detection products: MODIS, VIIRS,
GOES hot spots and smoke column tracking. Surfaces the
incident's perimeter as estimated from satellite, smoke
movement, and any newly detected hot spots that might be
spotting beyond the main fire.

> **In production**: the GIS Specialist (GISS) or intelligence
> section chats with this agent to recall what satellite
> products have shown across the incident, what the smoke
> column has done over time, and how the satellite estimate
> compares with field reports.

### 2. Weather Agent

Pulls forecasts from NWS Spot Forecasts, IMET briefings, RAWS
(Remote Automatic Weather Station) data, and red flag
warnings. Surfaces wind shift predictions, humidity recovery
expectations, and the team's interpretation of which forecast
sources have been reliable for this incident's microclimate.

> **In production**: the Incident Meteorologist (IMET) or the
> Fire Behavior Analyst (FBAN) chats with this agent to recall
> the forecast trajectory, spot forecasts received, and the
> team's interpretation of how the local weather has compared
> with regional forecasts.

### 3. Drone / Aerial Recon Agent

Operates UAS assets — incident-owned drones for thermal and
infrared mapping, structure threat assessment, and rapid
post-burn area mapping. Coordinates with helicopter
intelligence flights.

> **In production**: the UAS pilot or air operations branch
> coordinator chats with this agent to recall what's been
> overflown, when, with what sensor packages, and what was
> seen.

### 4. Ground Sensor Agent

Operates the network of fixed ground sensors — RAWS stations,
fuel moisture sensors, fire detection cameras (where
deployed), and any incident-specific sensors. Surfaces
real-time conditions at the points where the network has
coverage.

> **In production**: the Situation Unit Leader (SITL) or the
> intelligence section chats with this agent for ground-truth
> conditions to compare against forecasts and satellite
> products.

### 5. Resource Allocation Agent

Tracks engines, hand crews, dozers, helicopters, air tankers,
and overhead positions. Surfaces availability, current
assignment, prior tasking history, and the team's collective
awareness of which resources have been most effective for
which kinds of tasks on this incident.

> **In production**: the Resources Unit Leader (RESL) chats
> with this agent during planning meetings and dynamic
> reallocation, recalling what's been tried, what's working,
> and where the gaps are.

### 6. Evacuation Coordinator Agent

Manages the operational picture for evacuation zones,
evacuation routes, shelter capacity, special needs
populations, and the timing of evacuation orders and
warnings. **The agent does not issue evacuation orders.** It
holds the picture the Operations chief, the Sheriff, and the
County OES need to coordinate the order through proper
authority.

> **In production**: the Operations chief and the
> County OES emergency manager both chat with this agent
> during evacuation coordination. The actual evacuation order
> is issued by the Sheriff (or other authorized official
> per local ordinance), not by the agent.

### 7. Structure Defense Agent

Holds the operational picture for structure protection:
defensibility assessments, water availability, prior outcomes
on similar structures in similar conditions, and the team's
working priorities. **Does not triage structures
autonomously.** Surfaces what the SPRO needs to make the call.

> **In production**: the Structure Protection Specialist
> (SPRO) chats with this agent during the rapid assessment
> phase of any threat to a community, recalling prior
> incidents and the team's developing understanding of
> defensibility in this particular WUI environment.

### 8. Multi-Agency Liaison Agent

Coordinates with cooperating agencies: USFS, CalFire, county
sheriff, county OES, mutual aid neighbors, Red Cross, state
highway patrol, regional water utility. Holds the team's
understanding of which agencies are active, what their
contributions are, and the soft dynamics of working with each
partner.

> **In production**: the Liaison Officer (LOFR) chats with
> this agent throughout the incident to recall the current
> state of inter-agency coordination, the assets each agency
> has committed, and the practical dynamics of working with
> each partner — including soft preferences about briefing
> formats, meeting cadences, and primary points of contact.

### 9. Incident Commander Agent

Holds the synthesized operational picture for the IC.
Surfaces the current best understanding of fire behavior, the
working hypothesis about where the threat is going, the
contradicting evidence, and the team's priorities. **Critical
for operational period handoffs** — this is the agent that
holds the working memory the outgoing IC carries that doesn't
fit in the IAP document.

> **In production**: the Incident Commander chats with this
> agent throughout the operational period and especially
> during operational period handoff briefings, when the
> incoming IC needs to absorb 12 hours of operational state
> in a 30-minute window.

### 10. Public Information Officer (PIO) Agent

Drafts public updates, press releases, evacuation
notification messages, social media posts, and community
briefing materials. Holds the operational picture of what
information has been released publicly, what's being held
back operationally, what the affected community has been
told, and what the media is reporting.

> **In production**: the Public Information Officer (PIO)
> chats with this agent throughout the incident to recall the
> communication state, the operational sensitivities around
> what gets released when, and the soft dynamics of working
> with specific media outlets and community groups.

## Workflow phases

Six phases tracking the team from the start of Day 2's
operational period through the operational period handoff on
Day 3 morning. Each phase activates a subset of the agents
and produces specific memory touchpoints.

### Phase 1 — Day 2 morning operational period start (06:00 - 10:00)

Active agents: all ten agents activate or transition during
this window. The Type 2 IMT has been on the incident since
Day 1 evening and is now starting its second operational
period. Day shift IC Cynthia Park takes over from the night
shift IC at 06:00.

The morning briefing happens at 06:30. The IAP for the day's
operational period was drafted by the Plans section overnight.
Cynthia Park reads the formal IAP — and chats with the IC
agent to absorb the working memory the night shift IC
carries that didn't fit in the IAP.

By 09:00, the day's operations are underway. Crews are at
their division assignments. Resource Allocation is tracking
unit positions. Structure Defense has begun a pre-emptive
assessment of the Meadow Creek community structures based on
the forecast wind shift expected at 21:00.

### Phase 2 — Mid-day operations and pre-positioning (10:00 - 17:00)

Active agents: all ten

Active suppression continues. The Meadow Creek community
becomes the focus of structure protection planning. Evacuation
Coordinator works with the Sheriff's office on contingency
evacuation zones if the wind shift becomes a problem. The
Multi-Agency Liaison coordinates with Red Cross on shelter
capacity and with the regional water utility on infrastructure
priorities.

This is the "calm before" phase. The team is preparing for the
forecast wind shift event that night, but the fire's current
behavior is consistent with model expectations.

### Phase 3 — Wind shift event (19:30 - 21:30)

Active agents: all ten, in compressed time

At 19:30, the on-incident RAWS station registers a wind shift
90 minutes earlier than forecast — gusts of 35 mph from the
southwest, much stronger than the predicted 25 mph. The
Weather agent immediately surfaces the discrepancy. The fire
makes a run on the east flank, jumping a containment line. The
threat to the Meadow Creek community is now imminent.

The next 90 minutes are the most intense in the demo. The IC
makes the call to recommend evacuation. The Sheriff issues the
evacuation order. The Operations chief reallocates resources
to structure defense at Meadow Creek. The PIO drafts the
public notification. The Liaison coordinates with Red Cross
on accelerated shelter activation.

By 21:00 the evacuation is in progress. Structure defense
positions are established. The fire reaches the eastern
edge of the community at approximately 21:15.

### Phase 4 — Active structure defense and evacuation (21:30 - 02:00)

Active agents: all ten

The fire interacts with the community boundary. Structure
defense crews work the structures. The evacuation continues
through approximately 23:30 when the Sheriff confirms all
known residents are out (with a small number of refusals
documented). The Drone agent provides thermal coverage of the
community to spot any spot fires inside the protected
perimeter.

By 02:00, the immediate threat to the community is contained.
Most structures have been successfully defended. The fire has
moved past the eastern edge of the community and is now
burning in a section of state forest beyond the community.

### Phase 5 — Operational period handoff to night shift (02:00 - 03:00)

Active agents: IC, all command staff, all sensor agents

Night shift command staff arrives. The day shift IC and
command staff prepare the handoff briefing. The IC agent is
critical here — it holds the working memory the day shift
carries and surfaces it for the night shift in a structured
form that doesn't fit in the formal IAP update.

Specific things that need to transfer in the handoff:

- The wind shift came early and stronger than forecast — the
  IMET should weight the on-incident RAWS over the regional
  forecast for the rest of the incident
- Three structures on the east edge of Meadow Creek were lost
  during the active phase; ten structures were successfully
  defended; the team's interpretation of why the lost
  structures were lost (defensible space had recently been
  cleared but a wood deck on the windward side caught
  ember-cast embers)
- The Sheriff's office has logged six refusal-to-evacuate
  cases that may need follow-up if conditions deteriorate
- The Red Cross liaison rotated overnight; the new liaison is
  working out of Sacramento and prefers a structured
  handoff format
- The water utility's transmission line on the ridge is
  intact but the access road is blocked by burnt debris; need
  cleanup before re-energization can be confirmed

None of these fit in the formal IAP. All of them are critical
for the night shift to know.

### Phase 6 — Day 3 morning operational period start and post-event capture (03:00 - 08:00)

Active agents: night shift command staff, then day shift
returning at 06:00

The night shift assumes operations. The fire is in mop-up
mode in the Meadow Creek area but still burning actively in
the state forest section. The day shift returns at 06:00 for
the next operational period, and the team writes
post-event memories for the rest of the incident and for
future similar incidents.

## Memory touchpoints

These are the specific memory operations the demo will showcase.
Every example below is **operational period state, cross-incident
fuel behavior memory, multi-agency tribal knowledge, real-time
hypothesis tracking, or post-event learning** — none of it
duplicates CAD, ROSS, GIS, EOC software, or any other existing
emergency response system.

### Touchpoint 1: Operational period handoff at start of Day 2 (Phase 1)

When IC Cynthia Park takes over at 06:00, she chats with the IC
agent to absorb the night shift's working memory. The agent
surfaces a memory written by the night shift IC at 04:30:

> "Night shift handoff notes for Cynthia. Fire activity moderated
> overnight as expected with the inversion. Division Z on the
> east flank is the one to watch — we got a partial line in but
> it's anchored to a road that has a switchback the dozer
> couldn't clear, so there's a 200-yard gap we couldn't close.
> Today's plan in the IAP shows a hand crew taking that gap; my
> recommendation is to give that crew the priority air support
> if any spot fires develop in the gap. The forecast has the
> wind shift coming at 21:00 — Plans built the IAP around that
> assumption. The IMET (Sarah) is concerned the shift could
> come earlier and stronger than the regional forecast says
> because the local terrain channels wind in this drainage.
> Watch the on-incident RAWS station closely after 17:00. If it
> starts shifting before forecast, get evacuation contingencies
> running early. Strike Team Charlie has been on the line since
> Day 1 morning and needs relief by 14:00 today regardless. The
> Red Cross liaison Janet is great but works night shift only —
> her day-shift counterpart is new, named Marcus, briefed him at
> 23:00 last night and he's solid but unfamiliar with our
> incident."

Cynthia reads this in five minutes. The IAP gives her the
formal plan; this memory gives her the *story* of why the plan
is shaped the way it is, what to watch for, and the soft
dynamics she needs to manage today.

**Why this is the load-bearing memory**: in current practice,
the night shift IC writes some of this in the formal handoff
notes section of the IAP, but most of it gets transmitted in a
30-minute verbal briefing that the incoming IC has to absorb
while also processing the formal plan. Critical context gets
lost. The new IC starts the operational period without the
working memory of why decisions were made, and ends up
re-deriving things or making decisions that contradict what
was already learned. MemoryHub holds the working memory
explicitly.

### Touchpoint 2: Cross-incident fuel behavior recall (Phase 2)

Around mid-day, the Fire Behavior Analyst is using the Weather
agent to model the wind shift event expected that night. The
Weather agent surfaces a memory written by an FBAN on a
different incident the previous summer:

> "Cross-incident note from the Sage Ridge Fire (PS-WF-2024-088),
> August 2024. When chamise on south-facing slopes in the 1,800
> to 2,400 foot elevation band burned with single-digit relative
> humidity and afternoon winds in the 20-25 mph range, observed
> rate of spread was 15-22 chains per hour. Note that the
> regional forecast that day predicted 8-12 mph winds; the local
> RAWS recorded 22 mph gusts. The discrepancy between regional
> forecast and local observed wind was the dominant variable in
> the fire's run that afternoon. Lesson for future incidents in
> similar fuel/terrain: **trust the on-incident RAWS over the
> regional forecast for spread rate calculations on south-facing
> chamise**, especially when humidity is below 15%."

The FBAN reads this and adjusts the fire behavior projection
for tonight's expected wind shift. The team's contingency
planning for the wind shift event is informed by what they
learned a year ago on a different incident.

**Why it works as a demo moment**: this is the equivalent of
the cybersec "we've seen this before" moment and the LEO
"prior search" recall. Every fire behavior analyst in the
audience will recognize the experience of "I remember
something like this from last summer but I can't find it."
MemoryHub makes it structural.

### Touchpoint 3: Multi-agency tribal knowledge (Phase 1)

When the Liaison Officer is preparing for the morning's
multi-agency coordination call, the Multi-Agency Liaison
agent surfaces a memory written months ago:

> "When working with USFS Region 5 strike teams, brief through
> the strike team leader rather than directly to crew members.
> The strike team leader is the chain of command and going
> around them creates friction that slows response. This is a
> consistent pattern across multiple incidents with R5 strike
> teams and not specific to any individual crew. Particularly
> important during operational period transitions when our
> command staff changes but the strike team leader continues
> across multiple periods."

The Liaison coordinates the morning's activities through the
R5 strike team leader, not directly with individual crews.
The dynamic that takes new Liaison Officers months to learn is
available from day one.

### Touchpoint 4: Real-time hypothesis state during the wind shift (Phase 3)

At 19:30, the Weather agent detects the early wind shift and
writes a hypothesis update memory at project scope:

> "WIND SHIFT EARLY at 19:30. On-incident RAWS station MDC-7
> registers 35 mph SW gust, 90 minutes ahead of forecast and
> 10 mph stronger than predicted. The forecast at 16:00 said
> 25 mph from 21:00. This is the early/stronger pattern the
> night shift IC warned about in this morning's handoff —
> the local terrain is channeling wind harder than the
> regional model predicts. Working hypothesis: fire will make
> a run on the east flank within 30-60 minutes, threatening
> the eastern edge of the Meadow Creek community. Confidence:
> high. Recommend immediate notification to IC for evacuation
> contingency activation."

The IC sees the hypothesis update at 19:32. Within 5 minutes,
she has the picture clear enough to make the call to recommend
evacuation. The Sheriff's office is contacted at 19:38. The
evacuation order goes out at 19:52.

**Why this is the operational payoff of the cross-incident
memory**: the night shift IC's warning from the morning
handoff (touchpoint 1) and the cross-incident fuel behavior
memory (touchpoint 2) both pointed at exactly this scenario.
The team was prepared. The evacuation went out faster than
it would have if the wind shift had been a surprise.

### Touchpoint 5: Negative findings during structure defense (Phase 4)

Around 22:30, after the active fire run through the
community's eastern edge, the Drone agent overflies the
community with thermal imagery. The Structure Defense agent
writes a memory at project scope:

> "Drone thermal coverage of Meadow Creek at 22:30 shows the
> following structures clear of active fire and embers: 4471
> Pine Creek Rd (defended), 4475 Pine Creek Rd (defended),
> 4479 Pine Creek Rd (defended), 4483 Pine Creek Rd
> (defended), 4490 Pine Creek Rd (no fire reached property),
> [list continues for 12 more addresses]. Three structures
> lost: 4467 Pine Creek Rd (lost — ember-cast through wood
> deck on windward side), 4471 Mountain View Dr (lost —
> structure already had pre-existing fire damage from
> firewood pile), 4477 Mountain View Dr (lost — defensive
> position became untenable when wind shifted, crew safely
> relocated). Don't re-task structure defense crews to the
> defended addresses without new evidence — they're cleared
> for the rest of this operational period. The lost
> structures need post-event documentation but no further
> defense action."

The Operations chief reads this memory and re-tasks the
structure defense crews to the next-priority threat area
(the regional water utility transmission line on the ridge).
The crews don't waste time re-checking already-defended or
already-lost structures.

**Why this matters**: same as the LEO scenario's negative
findings discipline. In current practice, structure defense
crews routinely get re-tasked to areas that have been
cleared because the cleared status doesn't survive the
operational tempo. MemoryHub turns this into a structural
fix.

### Touchpoint 6: Per-IC preference memory (Phase 1)

When the IC agent prepares Cynthia Park's morning briefing,
it applies a preference memory written about her by a
previous incident she ran:

> "When IC Cynthia Park is running an incident, she prefers
> the morning briefing in this order: weather first, then
> fire behavior, then resource status, then division reports,
> then safety, then everything else. She's specifically said
> she wants weather and fire behavior together at the top
> because if those are unusual, everything downstream depends
> on them. This is a personal preference and applies across
> any incident she runs, not specific to this one."

The IC agent generates Cynthia's morning briefing in her
preferred order. Cynthia gets the briefing the way she
processes information best, and she catches the unusual
forecast variable (the IMET's concern about local terrain
channeling) on the first read.

### Touchpoint 7: Post-event learning capture (Phase 6)

The morning after the wind shift event, the team writes new
memories for future incidents:

> "Lessons from the Meadow Creek Fire wind shift event,
> Day 2 evening: (1) The on-incident RAWS station predicted
> the wind shift ~90 minutes before the regional forecast
> caught it. For incidents in this drainage system, weight
> on-incident RAWS over regional forecast for wind timing.
> (2) The pattern of 'forecast wrong by 90 minutes and 10
> mph' in this terrain has now been observed on this
> incident, the Sage Ridge Fire (2024), and the Pine Hollow
> Fire (2023). This is reproducible — three incidents is
> enough to call it a pattern. (3) Pre-positioning structure
> defense crews 4 hours before the forecast wind shift was
> the right call — gave us 90 minutes of buffer when the
> shift came early. Continue this practice for similar
> setups. (4) The wood-deck-on-windward-side structure loss
> pattern (one of the three lost in Meadow Creek) is the
> same pattern observed in the Camp Fire after-action
> reports. This is a known structure defense failure mode,
> but 'known' isn't enough — the structure assessment in
> Meadow Creek did not flag it. We need to specifically look
> for this pattern in future structure triage and write it
> into our pre-incident assessment criteria."

These memories will be read by the agent fleet during the
next similar incident — and "next similar incident" in
California fire season is a matter of weeks, not years.

## Contradiction moments

Two specific moments where one source's evidence contradicts
another's, and the team uses MemoryHub's contradiction
detection to surface and resolve the disagreement.

### Contradiction 1: Forecast vs. on-incident weather

**Setup** (Phase 1, Day 2 morning): the Weather agent has
been reporting the regional NWS spot forecast, which says the
wind shift will arrive at 21:00 with gusts up to 25 mph. The
IMET is concerned but doesn't have hard data yet to override
the forecast. The morning IAP is built around the forecast.

**Contradiction** (Phase 3, Day 2 evening 19:30): the Weather
agent receives the on-incident RAWS reading (35 mph gust at
19:30) and calls `report_contradiction` against its earlier
reported forecast:

> "Earlier-reported forecast (16:00): wind shift at 21:00,
> gusts to 25 mph. On-incident RAWS reading at 19:30: 35 mph
> gust from SW. The forecast was wrong by 90 minutes and
> 10 mph. The forecast is contradicted by direct observation.
> Working interpretation: trust the on-incident RAWS for the
> rest of this operational period. Cross-reference: this is
> the same pattern observed on Sage Ridge Fire (PS-WF-2024-088,
> August 2024) — local terrain channels wind harder than the
> regional model predicts."

**Resolution**: the IC acknowledges the contradiction. The
incident's working understanding of weather updates to weight
the on-incident RAWS over the regional forecast for the
remainder of the wind shift event. The forecast isn't
deleted — it's preserved as a record of what was predicted
versus what occurred, useful for after-action review and
future cross-incident learning. The cross-reference to the
2024 Sage Ridge Fire becomes part of the pattern memory that
the next incident will read.

**Why this contradiction matters**: forecast vs. observed is
the most common contradiction in wildland fire operations,
and getting it wrong has cost lives in real incidents.
MemoryHub's contradiction detection surfaces the discrepancy
explicitly so the team makes a deliberate decision about
which source to trust, rather than letting the forecast
silently dominate the working picture.

### Contradiction 2: Field observation vs. fire behavior model

**Setup** (Phase 2, Day 2 mid-day): the Fire Behavior Analyst
has been running a fire behavior model that projects rate of
spread on the east flank at approximately 8 chains per hour
for the afternoon, based on current weather and fuel
moisture inputs. The model output is part of the day's
operational planning.

**Contradiction** (Phase 2, Day 2 around 15:30): a Division
Supervisor on the east flank reports field observations
showing rate of spread closer to 14 chains per hour. The
field observation contradicts the model. The Division Sup
calls into Operations with the discrepancy.

The Resource Allocation agent writes a memory and calls
`report_contradiction` against the FBAN's earlier model
output:

> "Field observation contradicts model. FBAN model at 12:00
> projected 8 chains per hour rate of spread on east flank
> this afternoon. Division Z Sup reporting actual observed
> rate of spread of 14 chains per hour as of 15:30 — nearly
> double the model. The Sup believes the difference is fuel
> moisture in the chamise being lower than the model assumed
> — the area had a hot spell over the weekend that wasn't
> fully captured in the model's fuel inputs. Working
> interpretation: the model is underestimating spread rate.
> Recommend updating the operational plan for the
> afternoon's resource positioning, and treating any
> additional model outputs with appropriate skepticism until
> the discrepancy can be reconciled."

**Resolution**: the IC and Operations chief reweight the
afternoon plan based on the field observation. The FBAN
investigates the model assumptions and updates the inputs.
The contradiction is preserved with the field observation
marked as the operational ground truth for the rest of the
afternoon.

**Why this contradiction matters**: every fire behavior
analyst in the audience knows the experience of model output
contradicting field observation. The audience also knows the
politically and professionally awkward dynamic of having to
push back on a model that the IMT is treating as
authoritative. MemoryHub's contradiction detection gives the
field observation a structural way to surface the
discrepancy without it being a confrontation.

## Sensitive-data moments

Two specific moments where an agent attempts to write a memory
containing sensitive data and the curation pipeline catches
it.

### Sensitive moment 1: Resident PII in evacuation records

The Evacuation Coordinator agent attempts to write a memory
documenting the evacuation status:

> "Evacuation status as of 23:30: confirmed 274 of 280 known
> residents evacuated. Six refusal-to-evacuate cases logged:
> Maria Sanchez (4471 Pine Creek Rd, age 78, wheelchair-bound,
> son lives 2 hours away, refused on grounds of past
> evacuation experience), James Holloway (4475 Pine Creek
> Rd, age 65, refused on principle, has firefighter
> training), [continues for four more individuals with names,
> addresses, ages, and stated reasons]."

The curation pipeline catches the personally identifying
information about named residents, including their
addresses, ages, medical conditions, and family situations.
**Resident PII in operational memory is a serious data
governance issue.** The information is needed for operational
purposes (the Sheriff and Operations need to know about
refusals in case conditions deteriorate), but it should not
persist into shared memory where it could be accessed
broadly across the incident or after the incident closes.

The pipeline quarantines and the agent rewrites:

> "Evacuation status as of 23:30: confirmed 274 of 280 known
> residents evacuated. Six refusal-to-evacuate cases logged
> with the Sheriff's office through standard procedures. The
> refusal cases include known special needs requirements that
> may need follow-up if conditions deteriorate. Refusal
> details (names, addresses, contact information) are
> maintained in the Sheriff's evacuation tracking system per
> standard procedure, not in shared incident memory."

The operational fact is preserved (six refusals, special
needs concerns exist, follow-up may be needed). The
identifying details are not in shared memory — they live in
the Sheriff's system, which has appropriate access controls
and a defined retention policy.

**Why this matters**: incidents create huge amounts of
resident PII flowing through the operational picture
(evacuation lists, special needs registrations, contact
information). The operational systems handle this with
appropriate controls. The shared incident memory is the
wrong place for it to land. The curation pipeline enforces
this discipline at the moment of writing.

### Sensitive moment 2: Inter-agency political dynamics

During the Liaison agent's coordination work, it attempts to
write a memory about a conflict between cooperating
agencies:

> "USFS Region 5 Operations Section Chief Bob Martinez is
> currently in conflict with CalFire Operations Branch
> Director Linda Chen over the structure defense priority
> ordering. Martinez believes the regional water utility
> infrastructure should be the top priority because it
> serves three counties. Chen believes the residential
> structures in Meadow Creek take priority because they're
> occupied. Martinez has been openly critical of Chen's
> decision-making in incident command meetings. This
> conflict is affecting operational coordination on the
> east flank and may need to be addressed at the IC level.
> Background: Martinez and Chen have a history of
> disagreement going back to the 2023 Pine Hollow Fire."

The curation pipeline catches the named individuals, the
characterization of conflict, the negative behavioral
description ("openly critical"), and the historical
reference to a specific prior incident. **Inter-agency
political dynamics in operational memory is a liability
disaster waiting to happen.** This kind of content
becomes a problem in any of the following ways:

- It's discoverable in any after-action review or public
  records request
- It can damage inter-agency relationships if it leaks
- It can become evidence in legal disputes if any aspect of
  the incident is later litigated
- It tends to be one-sided and can mischaracterize
  individuals
- It creates a pattern where personal commentary becomes
  normalized in shared memory

The pipeline quarantines and the agent rewrites:

> "Coordination friction observed on the east flank between
> USFS and CalFire Operations leads regarding structure
> defense priority ordering. The substantive disagreement is
> about whether to prioritize regional water utility
> infrastructure or residential structures. This is a real
> operational decision that should be elevated to the IC
> for resolution. Specific personnel dynamics are not
> appropriate for shared memory — handle through normal
> command channels."

The operational fact is preserved (there is a real
disagreement about priority ordering, it needs IC resolution).
The personal characterizations are not. The memory directs
the team to handle the dynamic through proper channels rather
than through shared notes.

**Why this matters**: incident operations are stressful, and
real conflicts between agencies and individuals happen. The
shared memory layer is not the right place to record those
conflicts. The curation pipeline enforces a discipline that
trained Liaison Officers learn over years — keep the
operational facts separate from the personal commentary.

## What's drawn from sources vs. what's invented

Honest disclosure.

**Drawn from real frameworks and practices**:

- NIMS / ICS doctrine for the organizational structure,
  position titles, command relationships, and operational
  period concept
- NWCG publications for fire behavior, fuels classification,
  and tactical reference
- The general dynamics of forecast-vs-observed weather
  contradictions in wildland fire are realistic and
  historically significant
- The structure defense considerations (defensible space,
  ember-cast vulnerabilities, wood-deck failure modes) are
  drawn from actual after-action reports of Camp Fire,
  Tubbs Fire, and other significant California wildfire
  events
- The Type 3 to Type 2 IMT transition is a real and
  structurally significant moment in incident escalation
- Inter-agency coordination dynamics between USFS, CalFire,
  and county-level agencies are real
- The operational period handoff problem is universally
  recognized in the wildland fire community

**Invented for this scenario**:

- The Meadow Creek Fire and every detail about it
- The Meadow Creek community and every detail about it
- All officer names, including Cynthia Park, Sergeant
  Hammond, Bob Martinez, Linda Chen, Janet Williams, Marcus
  (Red Cross), Maria Sanchez, James Holloway
- All specific addresses, RAWS station identifiers, and
  geographic details
- All quoted memories
- The specific contradictions and their resolutions
- The Sage Ridge Fire and Pine Hollow Fire as prior
  incidents

The point is realistic *shape* that an emergency response
professional would recognize without finding any single
detail wrong.

**Sidestepped entirely**:

- Climate change framing (politically charged, distracts
  from the operational story)
- Forest management policy debates (controversial,
  agency-specific, politically loaded)
- Prescribed burn controversies (politically charged)
- Specific equity / disparity discussions about who gets
  evacuated when (real but politically loaded)
- Liability for structure loss decisions (legally sensitive)
- Use of force during evacuation refusals (legally and
  ethically loaded, not what the demo is about)
- Specific federal vs. state vs. local jurisdictional
  disputes (politically charged)

## Open questions

1. **Should the demo show the wind shift event in real time
   or in compressed flashback?** The wind shift is the most
   dramatic moment in the scenario but it happens in a
   2-hour window that would dominate a 13-minute demo if
   shown linearly. Compressing it via the operational
   period handoff (Phase 5) — where the team summarizes
   "what happened during Phase 3 and Phase 4" — is one
   option. Showing it as the central moment of the demo is
   another. The demo script will need to make this call.

2. **The Type 3 to Type 2 IMT transition is operationally
   significant** but adds complexity to the demo narrative.
   The current scenario design has the transition happen
   before the demo's focal period (between Day 1 evening
   and Day 2 morning). This keeps the demo focused on a
   single command structure throughout. If the demo wants
   to show the Type 3 to Type 2 transition explicitly, the
   scenario should be restructured.

3. **Demo length and pacing.** The 18-hour focal period
   (Day 2 morning through Day 3 morning) needs to compress
   to 15-20 minutes. We should pre-pick which 4-5 memory
   touchpoints land in the live demo.

4. **The structure loss element is operationally realistic
   but emotionally heavy.** The current scenario has three
   structures lost during the active phase. This is
   honest about wildland fire reality but could feel grim
   in a demo context. The demo script should treat this
   carefully — acknowledge the reality without dwelling.

5. **Wildland fire SME validation.** We absolutely need a
   working wildland fire practitioner — ideally someone who
   has run a Type 2 or Type 1 incident — to review this
   scenario before demoing it. The audience will catch
   ICS vocabulary mistakes, incorrect position titles,
   unrealistic operational timelines, or other operational
   errors instantly. The credibility of the demo depends on
   getting these right.

6. **The cross-incident learning between the Meadow Creek
   Fire and the synthetic Sage Ridge Fire and Pine Hollow
   Fire** needs to be honest. These are invented prior
   incidents. The demo presenter should be ready to clarify
   that they're synthetic if asked.

7. **Animation visualization for the wildfire scenario**.
   The wind shift event in Phase 3 is the most visually
   compelling moment in any of the five scenarios — sensor
   agents detecting the shift, the IC agent updating the
   working hypothesis, evacuation coordination starting,
   structure defense being pre-positioned, all in compressed
   time. If the animation gets built, this scenario
   benefits from it more than any other.

8. **The political careful framing of structure loss**. When
   structures are lost in real incidents, the question of
   "who decided which structures got defended" can become
   legally and politically sensitive. The demo should be
   careful to frame structure defense decisions as
   *Structure Protection Specialist* decisions made under
   incident command authority, not as decisions the agent
   fleet made.

9. **The demo must explicitly avoid implying that
   MemoryHub would have prevented the lost structures.**
   The three structures were lost because of an early and
   stronger-than-forecast wind shift, not because of any
   information failure that MemoryHub addresses. The demo's
   value proposition is "the team had the picture they
   needed faster" — not "AI would have saved more
   structures." Getting this distinction right is critical
   for the framing.
