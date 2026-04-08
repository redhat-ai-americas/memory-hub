# Emergency Response Scenarios

This folder holds emergency response scenarios for MemoryHub demos.
The first scenario (multi-day wildfire incident with operational
period handoffs and a wind-shift event) is the **fifth demo**
MemoryHub is being built toward, after the clinical, cybersecurity,
public safety, and agriculture scenarios.

## The value proposition in one sentence

> **MemoryHub holds the context that makes incident decisions go well.**

Same shape as the clinical, cybersecurity, public safety, and
agriculture value props, with one word changed for the domain. The
platform's value proposition is consistent across verticals: the
incident decisions are made by the human Incident Commander and the
command staff using their judgment, the existing tools provide the
data, and MemoryHub holds the surrounding context — the operational
state across operational periods, the cross-incident pattern memory,
the multi-agency dynamics, and the agent fleet's own operational
learning — that determines whether incident decisions land well.

## The decision-support boundary

Emergency response has decision-support tools, but they're focused
on different layers than what MemoryHub provides. The Incident
Command System (ICS) and the National Incident Management System
(NIMS) govern the *organizational* coordination of responders. CAD
systems handle dispatch. Resource allocation tools track crews and
assets. GIS platforms visualize the operational picture. EOC
software manages cross-agency coordination. None of them hold the
working memory that determines whether an operational period
handoff goes well.

### What existing emergency response systems do (don't try to do this)

- **CAD (Computer-Aided Dispatch)** — call intake, unit
  dispatching, status tracking
- **Resource ordering systems** — ROSS, IROC for federal wildland
  fire; state and local equivalents for structural and EMS
- **GIS platforms** — Esri ArcGIS, QGIS-based platforms,
  WildCAD-E for wildland fire visualization
- **EOC software** — WebEOC, Veoci, Knowledge Center, others —
  for cross-agency coordination during major incidents
- **Incident management systems** — IAP-software for the
  Incident Action Plan documents (eIAP, IAPS, similar)
- **Common Operating Picture (COP) platforms** — TAK-based
  systems, others
- **Notification platforms** — Everbridge, AtHoc, IPAWS for
  public alerting
- **Federal-specific tools** — IRWIN (Integrated Reporting of
  Wildland-fire Information), FAMIT, CAD2CAD interoperability

These do dispatch, resource ordering, visualization, IAP
generation, cross-agency coordination, and public notification.
The audience uses some combination of all of them. **MemoryHub does
not try to be any of them.**

### What MemoryHub holds in this scenario (this is where the value lives)

The things existing emergency response systems can't easily hold or
don't try to hold:

- **Operational period handoff state** — the working memory the
  outgoing IC and command staff carry that doesn't fit in the IAP
  document. "We tried that approach on division Z this morning and
  it didn't work because the access road has a switchback that
  the dozer can't take." The IAP captures the *plan*; MemoryHub
  captures the *story* of what's been tried, what's working, and
  what's not.
- **Cross-incident learning** — fire behavior, terrain dynamics,
  evacuation route reliability, structure defense outcomes from
  prior incidents on similar fuel types and similar terrain. "When
  chamise on south-facing slopes burned in this humidity range
  last August, expected rate of spread was X chains per hour."
  Prior incident postmortems capture this in writing, and the
  writing gets filed and forgotten.
- **Multi-agency tribal knowledge** — the soft dynamics of working
  with specific cooperating agencies, mutual aid partners, and NGO
  partners. "When working with USFS Region 5 strike teams, brief
  through the strike team leader rather than directly. The Red
  Cross liaison from the Sacramento chapter is Janet Williams, she
  works the night shift, and she prefers a structured handoff
  format."
- **Real-time hypothesis state** — the team's current best
  understanding of fire behavior, weather, and threat picture,
  with confidence and what reinforced or contradicted it. CAD
  tracks units; GIS visualizes locations; nothing tracks "what we
  currently believe and why we believe it."
- **Agent fleet operational state** — sensor coverage gaps,
  drone battery rotation windows, asset availability windows
  that affect operational planning. The kind of cross-fleet
  coordination that no human can hold across an active incident
  while also running operations.
- **Negative findings** — "we cleared division C at 14:00 with
  full structure protection in place, the threat has passed
  there, don't re-task structure protection resources back to
  division C without new evidence." The single biggest pain
  point in long-running incidents is wasted re-tasking, and no
  current tool holds it persistently.

The relationship is **complementary**. CAD dispatches the unit.
The IAP document captures the formal plan. GIS plots the
operational picture. EOC software coordinates across agencies.
MemoryHub holds the working memory that determines whether the
night-shift IC has the same understanding of the incident as the
day-shift IC who handed it off.

## The "humans in production" framing

This is critical for the emergency response audience for reasons
that overlap with the LEO audience but go further. Emergency
response is defined by **rapid life-safety decisions made under
uncertainty**. The IC decides when to issue an evacuation order.
The Operations chief decides which divisions get which resources.
The Structure Protection Specialist decides which structures are
defensible. None of these decisions can ever be made
autonomously by an AI agent — the legal, ethical, professional,
and cultural constraints all point the same way.

**In production, every agent in this fleet is operated by a human
practitioner.** The Satellite Imagery agent is operated by the
intelligence section or the GIS specialist. The Weather agent is
operated by the Incident Meteorologist (IMET) or the fire
behavior analyst (FBAN). The Drone agent is operated by the UAS
pilot. The Resource Allocation agent is operated by the Resources
Unit Leader (RESL). The Evacuation Coordinator agent is operated
by the Operations chief or branch director coordinating with the
sheriff. The Structure Defense agent is operated by the Structure
Protection Specialist (SPRO). The Incident Commander agent is
operated by the IC. **No agent makes any incident decision.** They
hold the operational memory their human practitioners need to make
those decisions well.

For the demo, Claude (or whoever is running the harness) plays
the role of the entire response team. This is a demo necessity,
not a product claim. The audience needs to understand this in the
first 60 seconds.

### Emergency response third rails

Each of the prior scenarios has a third rail. Emergency response
has several, and they all point at "don't let the AI make
life-safety decisions":

- **Automated evacuation orders** — evacuation order authority
  belongs to specific officials (sheriff, emergency manager, IC
  in some jurisdictions). The agent fleet does not issue
  evacuation orders. It surfaces the data the official needs to
  make the call.
- **AI structure triage** — deciding which structures to defend
  and which to write off is an inherently human call with legal,
  ethical, and professional weight. The agent fleet does not
  triage structures.
- **Predictive harm scoring** — anything that ranks people or
  properties by likelihood of harm is loaded territory. The agent
  fleet does not score people.
- **Autonomous resource dispatch** — committing crews to assignments
  is the Operations chief's authority. The agent fleet supports the
  decision, doesn't make it.
- **AI fire behavior prediction as ground truth** — fire behavior
  models exist and are useful, but the audience knows they fail in
  unpredictable ways. The agent fleet surfaces what the models
  say, what the field is observing, and the contradictions
  between them. The IC weighs both.

Specific language to use during the demo:

- "The IC agent helps the IC hold the operational picture across
  the operational period handoff"
- "The Resource Allocation agent surfaces unit availability and
  prior tasking history so the Operations chief has the
  information for the assignment call"
- "Each agent is the practitioner's interface to the incident's
  shared memory"
- "Every action attributed to the human who took it"

Specific language to avoid:

- "AI predicts structure loss" / "AI predicts evacuation needs"
- "Automated evacuation"
- "Autonomous resource dispatch"
- "AI-driven incident management" (vendor cliche)
- "Smart emergency response"
- "Replaces command staff" / "reduces the need for IC training"
- "Self-managing incident response"
- Anything that implies AI is deciding who is at risk

## Why emergency response is a strong fifth demo

Three reasons emergency response is the right capstone demo:

1. **Different audience, same value prop language.** The clinical,
   cybersecurity, public safety, agriculture, and emergency
   response demos all use the same one-line value prop with one
   word changed. Demonstrating the phrase works across five
   radically different verticals is a strong platform messaging
   signal.
2. **The operational period handoff problem is universally
   recognized in this audience and currently unsolved.** Every
   IMT person in the room has had the experience of inheriting
   an incident with insufficient context from a tired outgoing
   IC. The IAP captures the formal plan but not the working
   memory. MemoryHub addresses this directly, and the audience
   will recognize the value instantly.
3. **The demonstration of "AI that supports humans, doesn't
   make decisions" lands hardest here.** Emergency response has
   the highest stakes of any of the five domains. If MemoryHub's
   humans-in-loop framing holds up here — at the exact moment
   when the audience is most sensitive to AI overreach — it
   holds up everywhere. The emergency response demo is the
   stress test for the platform's positioning.

## Audience

**Primary**:

- Federal: FEMA, USFS, BLM, NPS, BIA, NIFC (National
  Interagency Fire Center), CISA emergency communications
- State: state emergency management agencies, state forestry
  agencies (CalFire, Florida DOF, Texas A&M Forest Service,
  etc.), state fire marshals, state offices of emergency
  services
- Local: county offices of emergency services, county fire
  departments, large municipal fire departments, local
  emergency management
- Type 1, Type 2, and Type 3 Incident Management Teams
- Cooperator agencies: Red Cross, Salvation Army, World Central
  Kitchen, voluntary organizations active in disasters (VOAD)
- Defense: DSCA (Defense Support of Civil Authorities), Army
  Corps of Engineers
- Tribal emergency management

**Secondary**:

- Private utilities (power, water, gas) with emergency response
  obligations
- Insurance and reinsurance companies (post-event modeling)
- Emergency response training institutions (NFA, EMI)
- Academic emergency management programs
- Critical infrastructure protection programs

**Tertiary**:

- Emergency response equipment vendors
- Critical communications providers
- GIS and mapping platform vendors
- Notification system vendors

This audience is operationally sophisticated, deeply skeptical of
technology that claims to "help" without understanding the
realities of field operations, and **immediately respectful of
anything that genuinely solves the operational period handoff
problem**. The handoff is the universal pain point across every
agency type in the room.

## Scenario inventory

| File | Status | Incident archetype | Source framework |
|---|---|---|---|
| [wildfire-response-meadow-creek.md](wildfire-response-meadow-creek.md) | **In active development** | Meadow Creek Fire — multi-day wildfire in Sierra foothills, wind-shift event threatening a small community | NIMS/ICS, NWCG IRPG (Incident Response Pocket Guide), AHA/ASA equivalents for wildland fire |

Future emergency response scenarios will be added here as they're
developed. Likely candidates: hurricane response coordination
(multi-state, multi-day, longer arc), urban search and rescue
post-earthquake, hazmat incident response, multi-agency mass
casualty incident, atmospheric river / flooding response.

## Source material preference

Emergency response has a stronger framework foundation than
agriculture or public safety, though weaker than clinical
(VA/DoD CPGs) or cybersecurity (NIST SP 800-61). Preferred
sources:

- **NIMS / ICS** doctrine — the foundational organizational
  framework that all federal, state, and most local
  emergency response uses
- **NWCG (National Wildfire Coordinating Group) publications**
  — the IRPG (Incident Response Pocket Guide), the Fireline
  Handbook, NWCG position task books, fire behavior reference
  materials
- **NFPA standards** — for structural fire response and many
  EM topics
- **FEMA publications** — Comprehensive Preparedness Guides
  (CPG), Incident Management Handbook
- **State emergency management plans** — publicly available,
  varying quality, but a reference for state-level
  coordination patterns
- **After-action reports** from prior major incidents — these
  are gold for demonstrating "what we learned that's relevant
  now" but must be cited carefully and never used to imply
  criticism of any specific agency

When picking sources for a new emergency response scenario,
prefer publicly available materials from NWCG, FEMA, NFPA, and
state agencies. Avoid proprietary vendor materials and any
source that hasn't been publicly reviewed.
