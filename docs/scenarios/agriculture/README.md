# Agriculture Scenarios

This folder holds agriculture scenarios for MemoryHub demos. The first
scenario (mid-season disease detection and spray response on a working
row-crop farm) is the **fourth demo** MemoryHub is being built toward,
after the clinical, cybersecurity, and public safety scenarios.

## The value proposition in one sentence

> **MemoryHub holds the context that makes agronomic decisions go well.**

Same shape as the clinical, cybersecurity, and public safety value
props, with one word changed for the domain. The platform's value
proposition is consistent across verticals: the agronomic decisions
are made by the farmer and the farm team using their judgment, the
existing precision-ag tools provide the data, and MemoryHub holds the
surrounding context — the cross-season field knowledge, the
multi-generational tribal knowledge, the equipment coordination
state, and the agent fleet's own operational learning — that
determines whether agronomic decisions land well.

## The decision-support boundary

Agriculture has decision-support tools, but they're focused on
**data visualization and prescription generation** rather than
operational memory. The major platforms (Climate FieldView, John
Deere Operations Center, Trimble, Granular, Bayer xarvio) hold field
data, generate variable-rate prescriptions, and visualize yield
maps. They don't hold the kind of soft contextual knowledge that
determines whether a prescription works in practice.

### What existing precision-ag platforms do (don't try to do this)

- **Climate FieldView (Bayer/Climate Corp)** — field data
  aggregation, scouting, planting and harvest data, variable-rate
  prescription generation, yield mapping, satellite imagery
- **John Deere Operations Center** — equipment telematics, field
  data, prescriptions, machine optimization, MyJohnDeere ecosystem
- **Trimble Ag** — guidance, variable-rate, water management,
  livestock tracking
- **Granular (Corteva)** — farm financial management, agronomic
  records, crop planning, profitability analysis
- **Bayer xarvio** — disease prediction, spray timing
  recommendations, biomass mapping
- **AgLeader, Raven, Ag Junction, AGCO Fuse** — equipment-side
  precision ag platforms with similar feature sets
- **Land grant university extension tools** — region-specific
  decision support for pest pressure, planting dates, etc.

These do field data aggregation, prescription generation, yield
mapping, and equipment optimization. They are also generally
**cloud-based** and operated by major ag companies — which raises
the data ownership concern this audience cares about (see
"humans in production" framing below). **MemoryHub does not try to
be any of them.**

### What MemoryHub holds in this scenario (this is where the value lives)

The things existing precision-ag platforms can't easily hold or
don't try to hold:

- **Cross-season field knowledge** — the kind of pattern memory
  experienced farmers carry in their heads. "Field 7 northwest
  corner has compaction issues from the 2018 wet harvest —
  pre-emptively reduce planting density by 15% in this zone every
  year." This kind of knowledge lives in the farmer's head and
  walks out the door when they retire or sell the operation.
  Variable-rate prescriptions can encode the *current* density,
  but the *reasoning* — and how to revise it as conditions change
  — lives in MemoryHub.
- **Multi-generational tribal knowledge** — agriculture is
  uniquely multi-generational. The senior farmer's understanding
  of how a field behaves in dry years, what insect pressures
  show up in which weather patterns, which hybrids work in the
  microclimate — this is exactly the kind of soft knowledge that
  walks out the door when there's no successor or when a new
  operator takes over. MemoryHub can hold it across generations.
- **Equipment coordination memory** — heterogeneous equipment from
  different vendors needs to work together in real time and
  remember its own operational state. "Tractor agent is on Field
  12 East for the next 3 hours, Spray Drone should not enter that
  airspace." Cross-vendor coordination is hard for cloud
  platforms (each vendor wants you in their walled garden) and
  easy for a memory layer that lives on the farm's infrastructure.
- **Failure-mode memory across operations** — "last spring the
  spray drone over-applied to the headland of Field 5 because the
  boundary file had been updated but the drone's local cache
  hadn't refreshed. Confirm boundary version against the central
  source before every flight." The kind of operational lesson
  that gets learned the hard way and then has to be remembered
  forever.
- **Per-operator tribal knowledge** — "Tom prefers the morning
  briefing to start with equipment health, then weather, then
  field issues. Linda prefers it the other way around because she
  handles compliance first thing." Soft preferences that shape
  how the agents serve their human operators.
- **Agent fleet operational state** — when a drone is overhead,
  when a spray window is open, when soil sensors are reporting
  fresh data, when an equipment health concern has been flagged
  — the cross-fleet operational picture that no single equipment
  vendor's platform holds.

The relationship is **complementary**. Climate FieldView holds
the field boundary and the variable-rate prescription. John Deere
Operations Center holds the equipment telemetry. MemoryHub holds
the *story* of why this year's prescription differs from last
year's, and the operational lessons that determine whether the
spray drone flies today.

## The "humans in production" framing

This is critical for the agriculture audience for a different
reason than the prior three: agriculture is a **profession with
strong cultural and family identity**. Farmers don't want to be
told that AI is going to replace them, and they especially don't
want to be told that a vendor knows better than they do how to run
their operation. The framing must respect the farmer as the
decision-maker and the agent fleet as a tool that supports them.

**In production, every agent in this fleet is operated by a human
practitioner.** The Crop Scout Drone agent is operated by the
precision ag specialist (often the operator's adult child, or a
hired manager). The Spray Drone agent is operated by a **licensed
applicator** — this matters legally and culturally. The Agronomy
agent is consulted by the farmer when making intervention
decisions. The Compliance agent is operated by whoever handles
records (often the operator's spouse in family operations, or a
dedicated office manager in larger ones). The Farm Manager agent
is operated by the operator running the daily standup.

**The agents do not make agronomic decisions.** They surface what
the team has learned, what the sensors are showing, and what the
prior seasons recorded. The farmer makes the call.

For the demo, Claude (or whoever is running the harness) plays the
role of the entire farm team. This is a demo necessity, not a
product claim. The audience needs to understand this in the first
60 seconds or they will hear "AI replaces farmers" — which is
exactly the wrong message for this audience.

### The data ownership concern

This is unique to the agriculture audience and matters more here
than in any of the other scenarios. Farmers are deeply concerned
about who owns and monetizes their farm data. Major ag companies
have spent the past decade collecting farm data through their
precision-ag platforms, and there's well-founded suspicion in the
farming community that this data is being used in ways that
benefit the platform more than the farmer. Class-action lawsuits
have been filed. State legislatures have considered farm data
privacy laws.

**MemoryHub's data ownership story for agriculture audiences must
be unambiguous**: the memories belong to the farm operation. The
operation chooses where they're stored (on-premise, on the
farm's own infrastructure, or with a trusted partner). The
operation chooses who reads them. The operation chooses when to
delete them. There is no "MemoryHub the company harvests your
data" angle, because MemoryHub is open-source software running on
infrastructure the farmer controls.

This is a real differentiator from cloud-only ag platforms and
should be addressed explicitly in the demo framing. It is also
not a trivial claim to make — the deployment story has to back it
up. For the demo, the framing is "this runs on your cluster, your
data stays with your operation." For production, this becomes a
real conversation about deployment topology.

### Specific language to use during the demo

- "The Crop Scout Drone agent helps the precision ag specialist
  recall what the team has learned from prior scouting passes"
- "The Agronomy agent surfaces the cross-season patterns this
  field has shown so the farmer doesn't have to remember every
  year's notes"
- "The Spray Drone agent waits for licensed applicator approval
  before any application"
- "Each agent is the practitioner's interface to the operation's
  shared memory"
- "Your data, your operation, your decisions"

### Specific language to avoid

- "AI replaces farmers" or any equivalent
- "Optimize your yield" (this is the marketing cliche the audience
  has been burned by)
- "Smart farm" (vendor cliche)
- "Big data agriculture" (the audience associates this with data
  ownership concerns)
- "Prescriptive agronomy by AI"
- "Eliminates the need for [scouting / agronomist consultation /
  any human role]"
- "Cloud-based" used positively without qualification (the
  audience hears "your data leaves the farm")
- "AI-driven precision agriculture" (vendor cliche)

## Why agriculture is a strong fourth demo

Three reasons agriculture is the right follow-up to clinical,
cybersecurity, and public safety:

1. **Different audience, same value prop language.** The
   clinical, cybersecurity, public safety, and agriculture demos
   all use the same one-line value prop with one word changed.
   The phrase generalizes across radically different verticals,
   demonstrating platform messaging consistency and breadth.
2. **Genuinely novel territory for agent fleets.** Unlike the
   clinical and security domains where there's an established
   decision-support paradigm to position against, agriculture's
   memory layer story is mostly unaddressed. We can be ambitious
   about what MemoryHub does without competing with anything the
   audience trusts. The data ownership angle adds a credible
   differentiator that cloud-only platforms can't match.
3. **The breadth signal is strongest here.** Showing that
   MemoryHub works for clinical, security, and public safety is
   one kind of platform story. Adding agriculture takes that
   story from "MemoryHub is for serious office-based industries"
   to "MemoryHub is for any domain with multi-agent coordination
   needs." That breadth is a meaningful signal to investors,
   integrators, and platform partners watching the demos.

## Audience

**Primary**:

- Ag-tech companies and innovators: investors at events like World
  Agritech, founders of precision-ag startups
- Major ag platform vendors who want to integrate (rather than
  compete): John Deere ecosystem partners, Bayer/Climate Corp
  partners, Corteva partners, AGCO partners
- Large-scale row-crop operations and ag co-ops with their own
  technology budgets
- Vertically-integrated food producers and processors with
  in-house ag teams

**Secondary**:

- Land Grant universities and Extension services
- USDA, NRCS, and state departments of agriculture
- Carbon credit and sustainability platforms (a growing buyer
  segment for precision-ag tools)
- Agronomy consulting firms
- Crop insurance providers (data-driven underwriting is a growth
  area)

**Tertiary** (audiences worth knowing about even if not the
primary demo target):

- Farm equipment dealers
- Cooperative extension educators
- Agricultural lenders

This audience traditionally doesn't see itself as a target for
sophisticated AI/agent demos, which makes it a strong "breadth"
scenario. Showing that MemoryHub works in agriculture as well as
in healthcare, security, and public safety demonstrates the
platform's generality in a way no single industry-vertical demo
can.

## Scenario inventory

| File | Status | Operation archetype | Source framework |
|---|---|---|---|
| [disease-detection-hollander-farms.md](disease-detection-hollander-farms.md) | **In active development** | Hollander Farms, 4500-acre central Iowa row-crop operation, mid-season tar spot detection and spot-spray response | USDA NRCS conservation practices, university extension IPM guidelines, FAA Part 137 (agricultural aircraft operations) |

Future agriculture scenarios will be added here as they're
developed. Likely candidates: spring planting coordination
(weather-driven decision making), harvest logistics (combine
fleet + grain cart + truck coordination), drought response
(irrigation prioritization across fields), specialty crop
operations (orchards, vineyards, vegetables — different agent
fleet shape).

## Source material preference

Agriculture doesn't have a single equivalent of VA/DoD CPGs or
NIST SP 800-61. The closest analogs are:

- **Land grant university extension publications** — region-
  specific best practices for crops, pest management, equipment
  operation. Iowa State, Purdue, Illinois, Nebraska, and other
  Midwest universities are particularly strong sources for
  row-crop scenarios.
- **USDA NRCS conservation practice standards** — formal
  practice descriptions for soil and water management,
  integrated pest management, and other operational topics.
- **FAA regulations** for any scenario involving aerial
  application — Part 137 governs agricultural aircraft
  operations including drone-based application, and the audience
  knows this regulation matters.
- **EPA labels** for any scenario involving pesticide
  application — labels are legal documents and the application
  must follow them. The demo should never depict an
  off-label use.
- **Practitioner publications** like Wallaces Farmer, Successful
  Farming, AgWeb, and Farm Industry News for industry context.

When picking sources for a new agriculture scenario, prefer
publicly available materials from extension services, USDA, and
practitioner publications. Avoid proprietary vendor materials,
which the audience instantly recognizes as marketing.
