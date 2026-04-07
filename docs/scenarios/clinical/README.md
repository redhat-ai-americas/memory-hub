# Clinical Scenarios

This folder holds healthcare scenarios for MemoryHub demos. The first scenario
(stroke rehabilitation) is the **first demo** MemoryHub is being built toward.

## The value proposition in one sentence

> **MemoryHub holds the context that makes clinical decisions go well.**

That's the phrase. It's the line that should appear on the title slide of any
clinical demo, in the introduction of every clinical scenario doc, and in the
elevator pitch when someone asks "what is MemoryHub for in healthcare?"

It's load-bearing because it does three things at once:

1. **Acknowledges that clinical decisions are made by clinicians.** Not by
   MemoryHub. Not by agents. Not by AI. By people, using their judgment.
2. **Acknowledges that decision-support systems exist and are doing their
   job.** CDS systems make recommendations. EHRs hold the structured data.
   MemoryHub doesn't try to be either of those things.
3. **Carves out a specific value MemoryHub provides** — the surrounding
   context that determines whether a clinical decision goes well or
   poorly. The patient's preferences, the team's tribal knowledge, the
   continuity across handoffs, the cross-encounter narrative thread.

Memorize this phrase. Use it.

## The CDS boundary

Every clinical scenario doc in this folder must include an explicit
"MemoryHub vs. Clinical Decision Support" boundary section. The audience for
healthcare demos almost always already has CDS deployed (or is planning to),
and they will instantly distrust any pitch that appears to compete with their
existing investment.

### What CDS systems do (don't try to do this)

CDS systems are decision-recommendation engines wired into the EHR. They do:

- Drug-drug interaction checking
- Drug-allergy checking
- Evidence-based dosing recommendations and order set automation
- Clinical scoring (NIHSS, PHQ-9, MELD, sepsis screening, etc.)
- Critical lab value alerts and abnormal result notifications
- Best-practice advisories tied to diagnoses or order sets
- Duplicate test detection
- Documentation prompts
- Guideline-based qualification ("this patient meets criteria for X")

These are well-defined, well-understood, and well-monetized. Epic, Cerner,
and others compete in this space. **MemoryHub does not.**

### What MemoryHub does (this is where the value lives)

The things CDS systems can't easily hold, don't want to hold, or actively
push out of scope:

- **Patient narrative context** — the soft stuff a great nurse remembers
  about a patient that never makes the chart. "Patient prefers morning
  therapy because his wife visits in the afternoon." "Gets anxious in the
  pool, OT noted to use the gym instead." These aren't billable, aren't
  structured, and aren't searchable in the EHR — but they determine
  whether the care plan actually works for the human being in the bed.

- **Care team tribal knowledge** — practices that aren't formal protocol
  but the team knows. "Dr. Patel prefers SSRIs over SNRIs for post-stroke
  depression based on her experience." "This unit advances dysphagia diet
  before weekend if patient stable 48h, never Friday after 3pm." These
  live in heads, not in policy manuals, and they walk out the door when
  staff turn over.

- **Cross-encounter narrative continuity** — the thread that connects what
  happened in inpatient rehab to what's relevant in outpatient PT three
  weeks later. EHRs hold structured data across encounters but
  reconstructing the *story* requires reading every note. MemoryHub holds
  the story directly.

- **Agent-operational state** — the most novel category. As more clinical
  workflows incorporate AI agents (scribes, summarizers, schedulers,
  decision-support assistants), those agents need to remember things
  about how they work together. "The PT agent has learned to specify
  'pre-discharge' vs 'inpatient phase' when asking the Pharmacist agent
  about meds — the same drug can have different orders." This is
  operational memory for the AI fleet itself, and no existing system
  holds it because no existing system has an AI fleet that needs it.

The relationship is **complementary**. The CDS system fires the alert that
says "this patient is at risk for fall." MemoryHub holds the memory that
says "patient won't use the call light because he doesn't want to bother
anyone — staff have learned to round on him every 90 minutes regardless."
Both pieces of information matter; neither belongs in the other system.

## The "humans in production" framing

Every clinical scenario doc in this folder must be explicit, repeatedly,
that **the agents are operated by clinicians in production**. The demo will
have Claude (or whoever is driving the harness) playing the role of all the
clinicians, but this is a demo necessity. The audience must understand that
in real deployment:

- A nurse chats with the Inpatient Nurse agent the way she might consult a
  knowledgeable colleague who knows the patient well
- A physical therapist chats with the PT agent to recall what a previous
  PT noted about the patient's preferences
- A case manager chats with the Case Manager agent to surface the team's
  shared understanding of the patient's home situation

The agents are the clinicians' interface to the team's shared memory.
They're not autonomous decision-makers, they're not replacing the clinical
team, and they're not making care decisions.

This framing should appear in two places in every clinical scenario doc:

1. **A dedicated section near the top** of the scenario doc, written so a
   reader who only reads the first page comes away with the right
   understanding.
2. **Sidebars in each role description**, with a one-line note explaining
   who chats with that agent in production. Example: "In production: the
   inpatient rehab nurse on shift chats with this agent during handoff
   to recall what's happened with the patient over the last 24h."

## Scenario inventory

| File | Status | Patient archetype | Source CPG |
|---|---|---|---|
| [stroke-rehab-marcus-reeves.md](stroke-rehab-marcus-reeves.md) | **In active development** | Marcus Reeves, 64yo Veteran, post-acute stroke rehabilitation across 4 care settings | [VA/DoD Stroke Rehabilitation CPG (2024)](https://www.healthquality.va.gov/HEALTHQUALITY/guidelines/Rehab/stroke/VADOD-2024-Stroke-Rehab-CPG-Full-CPG_final_508.pdf) |

Future clinical scenarios will be added here as they're developed.

## Source guideline preference

When picking the source clinical practice guideline for a new clinical
scenario, prefer:

- **VA/DoD CPGs** (`healthquality.va.gov/Guidelines.asp`) — public domain,
  well-structured with explicit role lists and decision algorithms,
  clinically authoritative, no IP concerns, easy to cite
- **Other public-domain or Creative Commons guidelines** when VA/DoD doesn't
  cover the condition
- Avoid proprietary guidelines (UpToDate, Wolters Kluwer, etc.) unless we
  have explicit permission to cite

The guideline becomes the citation for the scenario's clinical accuracy.
Wherever the demo invents details not in the guideline (which will happen),
the scenario doc must be honest about what's invented vs. what's drawn from
the source.
