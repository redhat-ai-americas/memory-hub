# Public Safety Scenarios

This folder holds public safety scenarios for MemoryHub demos. The first
scenario (multi-sensor fugitive search swarm) is the **third demo**
MemoryHub is being built toward, after the clinical and cybersecurity
scenarios.

## The value proposition in one sentence

> **MemoryHub holds the context that makes tactical decisions go well.**

Same shape as the clinical and cybersecurity value props, with one word
changed for the domain. The platform's value proposition is consistent
across verticals: the tactical decisions are made by humans using their
judgment, the existing tooling provides the data, and MemoryHub holds
the surrounding context — the hypothesis state across time, the negative
findings that prevent wasted effort, the cross-incident patterns from
prior searches, and the agent fleet's own operational learning — that
determines whether tactical decisions land well.

## The decision-support boundary

Public safety doesn't have a single dominant "decision-support paradigm"
the way healthcare has CDS or cybersecurity has SIEM/EDR/SOAR. Instead,
LEO operations have a fragmented set of tools, each doing one thing
well, with very little integration between them. This actually gives
MemoryHub more room to be ambitious — but the demo must still
acknowledge the existing systems and position MemoryHub as
complementary, not competitive.

### What existing LEO systems do (don't try to do this)

- **CAD (Computer-Aided Dispatch)** systems handle dispatch, unit
  tracking, and call management. CentralSquare, Tyler Technologies,
  Motorola Solutions are major vendors.
- **RMS (Records Management Systems)** hold case records, incident
  reports, arrest records, and historical data.
- **GIS / mapping platforms** like Esri ArcGIS provide tactical
  visualization, geographic analysis, and crime mapping.
- **License Plate Reader databases** (Vigilant Solutions, Flock Safety,
  Rekor) hold LPR hits and vehicle movement data.
- **Real-time crime centers** (RTCCs) in larger departments provide
  live monitoring of cameras, alerts, and operational pictures.
- **Fusion centers** (state and regional) provide multi-source
  intelligence analysis and information sharing across agencies.

These do dispatch, records, mapping, LPR, monitoring, and intel
fusion. **MemoryHub does not try to be any of them.**

### What MemoryHub holds in this scenario (this is where the value lives)

The things existing LEO systems can't easily hold or don't try to hold:

- **Hypothesis state across time** — the team's current best
  understanding of where the subject is, with confidence, what
  reinforced the hypothesis, and what contradicted it. CAD tracks
  units; GIS visualizes locations; nothing tracks "what we currently
  believe and why we believe it."
- **Negative findings that prevent wasted effort** — "we cleared
  the Riverside neighborhood between 14:00 and 15:30 with full
  coverage of exits. Don't re-task units there without new
  evidence." This is the single biggest pain point in active
  searches, and no current tool holds it persistently.
- **Cross-incident pattern memory** — "the last time we searched
  for a subject with this profile in this terrain, they were
  found in an abandoned outbuilding within 4 miles of the initial
  sighting. Geographic Analyst should weight that pattern."
  Postmortem reports capture this in writing, but the writing
  gets filed and forgotten.
- **Multi-source sensor cross-correlation as narrative**, not just
  as data points — "the LPR hit at 03:42 and the doorbell camera
  detection at 03:51 are 1.2 miles apart, consistent with the
  subject continuing on foot in the projected direction."
- **Tribal knowledge across incident commanders and shifts** —
  "IC Sergeant Hammond prefers tip line items pre-scored for
  credibility before they hit her queue. The Tip Line Triage agent
  learned this last incident."
- **Agent fleet operational state** — drone battery rotation
  windows, sensor coverage gaps, asset availability — the kind of
  cross-fleet coordination that no human can hold across an
  active operation.

The relationship is **complementary**. CAD dispatches the unit.
GIS plots its location. MemoryHub holds the memory that says
"that area was already cleared at 14:00 — re-tasking is wasted
effort unless something changed."

## The "humans in production" framing

This is critical for LEO audiences — possibly more critical than for
clinical or security audiences. Public safety AI is politically
loaded, and any implication that AI is making tactical decisions
unattended will lose the room and probably make news.

**In production, every agent in this fleet is operated by a human
practitioner.** The Camera Network agent is operated by a CCTV
operator in the real-time crime center. The Tip Line Triage agent is
operated by a tip line analyst. The Incident Commander agent is
operated by the incident commander running the search. The Resource
Dispatcher agent is operated by the dispatcher coordinating ground
units. **The agents emphatically do not make tactical decisions on
their own — they hold the operational memory their human
practitioners need to make those decisions well.**

For the demo, Claude (or whoever is running the harness) plays the
role of the entire SOC — sorry, the entire response team. This is a
demo necessity, not a product claim. The audience needs to
understand this in the first 60 seconds or they will misread the
entire demo as "AI replaces police work" — which is not what
MemoryHub does and not what the demo is showing.

### LEO-specific third rails

The cybersecurity demo has "auto-containment" as its third rail.
The clinical demo has "AI replaces clinicians" as its third rail.
LEO has several:

- **Predictive policing** — burned phrase. Don't use it. Even
  describing geographic pattern analysis as "predictive" will
  trigger the audience members who follow civil liberties
  discourse.
- **Autonomous threat assessment** — implies AI deciding who is
  dangerous. Don't go there.
- **Automated suspect identification** — implies AI deciding who
  the perpetrator is. The demo scenario must use a fugitive who
  has *already been positively identified by humans* (warrant
  issued) and is being *located*, not identified.
- **Facial recognition** — politically loaded, often legally
  restricted. Even if the technology exists in the agent fleet,
  the demo should not feature it prominently. Use other
  identification mechanisms (witness statements, license plate
  hits, BOLO descriptions) for the demo.
- **Bias amplification** — the audience knows AI in policing has
  historically reflected and amplified biased data. The framing
  of MemoryHub should emphasize that the audit trail makes
  every decision *traceable to a human*, which is the bias
  mitigation story (you can see exactly who made which call and
  why).

Specific language to use during the demo:

- "The Incident Commander agent helps the IC hold the operational
  picture across multiple jurisdictions and a long shift"
- "The Pattern Analyst agent surfaces what the team has learned
  from past searches for similar subject profiles"
- "Each agent is the practitioner's interface to the operation's
  shared memory"
- "Negative findings tracking" (the value prop is *reducing*
  wasted effort, which is operationally good for everyone)

Specific language to avoid:

- "Predictive policing" (any usage)
- "Autonomous detection" / "AI threat detection"
- "AI identifies the suspect"
- "Facial recognition"
- "Automated decision-making"
- "Reduces officer involvement"
- Anything that sounds like surveillance escalation

## Why public safety is a strong third demo

Three reasons public safety is the right follow-up to clinical and
cybersecurity:

1. **Different audience, same value prop language.** The clinical,
   cybersecurity, and public safety demos all use the same one-line
   value prop with one word changed ("clinical" / "security" /
   "tactical"). That consistency is platform messaging gold and
   demonstrates the value prop generalizes across domains.
2. **Multi-sensor fusion is a real, unmet need in this audience.**
   Most LEO agencies have some kind of fusion capability but are
   not satisfied with it — there's appetite for better. MemoryHub's
   multi-agent shared memory is a natural fit and isn't trying to
   compete with anything they already trust.
3. **No human-replacement anxiety, *if framed correctly*.** The
   audience worries about automated tactical decisions, not about
   "AI replacing officers." The "agents help analysts and
   commanders" framing maps cleanly to the LEO operational
   structure where commanders make decisions and analysts provide
   information. As long as we don't trip the political third
   rails listed above, the framing lands.

## Audience

- Federal: FBI, US Marshals (especially fugitive task forces),
  ATF, DEA, ICE/HSI, Secret Service
- State: state police, highway patrol, state bureaus of investigation
- Local: city police, county sheriffs, particularly in
  mid-to-large jurisdictions with real-time crime centers
- Fusion centers (state and major urban area)
- Defense: special operations forces (SOFIC audience), joint task
  forces, OSI, NCIS
- Intelligence community: multi-source fusion analysts
- Public safety integrators and platforms: Axon, Motorola
  Solutions, Palantir-adjacent, Esri ArcGIS for Public Safety,
  Mark43, CentralSquare
- Border and customs enforcement (CBP, state border units)

This audience is sophisticated about multi-source fusion (most have
it in some form) but is generally not satisfied with current tools.
There is real appetite for better.

## Scenario inventory

| File | Status | Subject archetype | Source framework |
|---|---|---|---|
| [fugitive-search-daniel-voss.md](fugitive-search-daniel-voss.md) | **In active development** | Daniel Voss, 28, identified suspect in nightclub shooting, 6-hour multi-jurisdictional search | NIST/DOJ ICS, IACP active shooter response guidelines |

Future public safety scenarios will be added here as they're
developed. Likely candidates: missing person / Amber Alert
coordination, large-event security operations, multi-agency
disaster response (overlap with the emergency-response folder),
border surveillance fusion.

## Source material preference

Public safety doesn't have a single equivalent of VA/DoD CPGs or
NIST SP 800-61. The closest analogs are:

- **NIST/DOJ Incident Command System (ICS)** — the operational
  framework adopted across federal, state, and local agencies for
  coordinated response
- **IACP best practice guides** — published by the International
  Association of Chiefs of Police on a variety of operational
  topics
- **DOJ COPS Office publications** — community-oriented policing
  best practices
- **PERF (Police Executive Research Forum)** publications —
  practitioner-oriented research and case studies
- **FBI National Academy** training materials (for those publicly
  released)

When picking sources for a new public safety scenario, prefer
publicly available, citable materials from these organizations.
Avoid proprietary vendor materials and any source that hasn't been
through public review. The credibility of LEO scenarios depends
heavily on operational realism, and the audience will instantly
catch errors that come from making things up.
