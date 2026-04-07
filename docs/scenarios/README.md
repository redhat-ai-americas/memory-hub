# Scenarios

This folder captures the demo scenarios MemoryHub uses to show its value to
specific audiences. Each scenario lives in its own subfolder so it can be
developed, demoed, and refined independently.

## The framing every scenario shares

Two principles run through every scenario in this folder. They're load-bearing
positioning, not stylistic notes — get them wrong and the demo lands wrong.

### AI supports humans, it doesn't replace them

Every scenario in this folder is built around the premise that **the agents
help the people doing the work — they don't take their jobs**. In a clinical
scenario, a nurse chats with the Inpatient Nurse agent the way she might
consult a knowledgeable colleague. In a SOC scenario, a Tier 1 analyst chats
with the Tier 1 agent the way she might compare notes with a more senior
analyst who's been at the firm longer. The agent is the human's interface to
the team's shared memory and accumulated experience, not an autonomous
decision-maker.

For the demo itself, Claude (or whoever is driving the harness) plays the
role of all the humans. This is a demo necessity, not a product claim. The
write-up of every scenario must be explicit, repeatedly, that the agents are
**operated by humans in production**. The audience needs to understand this
in the first 60 seconds or they will misread the entire demo as "AI replaces
the workforce."

Specific language to use:

- "The Inpatient Nurse agent helps the nurse hold context across shifts"
- "The Tier 2 agent recalls what the team learned in past incidents so the analyst doesn't have to"
- "Each agent is operated by a human practitioner in production"

Specific language to avoid:

- "The agent makes the decision"
- "The agent diagnoses / detects / determines"
- "Replaces the need for"
- "Automated workflow" (instead: "agent-assisted workflow")

### Don't fight existing decision-support paradigms

Every scenario domain has existing systems that do *decision support*. In
healthcare it's CDS (clinical decision support — Epic Best Practice
Advisories, Wolters Kluwer, Cerner alerts). In cybersecurity it's SIEM
correlation rules, EDR detections, and SOAR playbooks. In emergency response
it's incident command systems and resource allocation tools. These systems
are well-established, well-funded, and well-understood by the audiences we're
demoing to. Trying to compete with them is a losing position — the audience
already has them, already trusts them, and will assume MemoryHub doesn't
understand the domain if we appear to duplicate them.

The right framing in every scenario:

> **MemoryHub holds the *context that makes [domain] decisions go well*. The
> existing decision-support systems make the decisions. MemoryHub holds what
> they can't easily hold: the soft narrative context, the team's tribal
> knowledge, the cross-encounter continuity, and the agent fleet's own
> operational learning.**

This phrase, "the context that makes [domain] decisions go well," is the
single best one-line value prop we have. Use it.

In each scenario doc, there should be an explicit "MemoryHub vs. existing
decision-support" boundary section that tells the reader:

- What the existing decision-support paradigm in this domain does
- What MemoryHub does that the existing paradigm doesn't
- Why they're complementary, not competitive

## Scenario inventory

| Folder | Scenario | Status | Audience |
|---|---|---|---|
| [`clinical/`](clinical/) | Stroke rehabilitation across care settings | **In active development — first demo** | Healthcare IT, RHOAI customers, clinical informatics |
| [`cybersecurity/`](cybersecurity/) | SOC threat hunting and incident response | **In active development — second demo** | SOCs, MSSPs, CISOs, CISA, defense contractors |
| [`public-safety/`](public-safety/) | Multi-sensor fugitive search swarm | **In active development — third demo** | Law enforcement, public safety, defense, intelligence |
| [`agriculture/`](agriculture/) | Mid-season disease detection on a working family farm | **In active development — fourth demo** | Ag-tech investors and executives, major ag platform vendors, large operations, ag-tech startup founders |
| [`emergency-response/`](emergency-response/) | Multi-day wildfire response with operational period handoffs | **In active development — fifth demo** | FEMA, USFS, CalFire, state and local emergency managers, IMT members, NGO emergency response leaders |

All five scenarios are now in active development. Each has a folder
README, a full scenario doc, and a demo script targeting an
appropriate decision-maker conference for the audience.

## Visualization stretch item

Across all scenarios, there's a stretch goal of a basic animation showing
agent coordination — something simple like circles representing agents with
pulses going in and out of a central core (MemoryHub) and between each other.
The point is to spark the audience's imagination about what's happening
underneath the harness output. A non-technical audience member should look at
the animation and instantly understand "the agents are reading and writing
to a shared memory."

This is **explicitly a stretch item** — only attempt it if everything else is
working. Plain harness output + spoken narration is sufficient for the
first demo if the visualization isn't ready.

## How to add a new scenario

1. Create a new sibling folder (`docs/scenarios/<name>/`).
2. Add an entry to the inventory table above.
3. Start with a `README.md` that captures: target audience, value prop in
   one sentence, decision-support paradigm in this domain that we should
   not fight, agent fleet shape, key memory examples.
4. When you're ready to develop the scenario into a real demo, add a
   detailed scenario doc alongside the README (e.g.,
   `<incident-or-patient-archetype>.md`).
5. Cross-link from the top-level inventory.
