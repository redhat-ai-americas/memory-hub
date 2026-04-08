# Stroke Rehabilitation: Marcus Reeves

A working scenario for MemoryHub's first clinical demo. Built around a
synthetic Veteran patient progressing through post-stroke rehabilitation
across four care settings, with a fleet of ten agents that help the
clinical team hold their shared context across handoffs.

## The phrase

> **MemoryHub holds the context that makes clinical decisions go well.**

That phrase is the entire frame for this scenario. Every memory example,
every contradiction, every PHI moment in this doc is in service of it.
The clinical decisions in this scenario are made by clinicians using
their judgment. The agents help the clinicians hold the surrounding
context that determines whether those decisions land well.

## Agents support humans, they don't replace them

This is critical to read before you read the rest of the scenario:

**In production, every agent in this fleet is operated by a human
clinician.** The Inpatient Nurse agent is the interface a working
inpatient nurse uses to recall what the team knows about the patient.
The PT agent is the interface a working physical therapist uses to
surface what previous PTs have learned about how this patient responds
to intervention. The Case Manager agent is the interface a working case
manager uses to hold the team's shared understanding of the patient's
home situation, family dynamics, and goals.

For the demo, Claude (or whoever is running the harness) plays the role
of all the clinicians. This is because we are demoing the *agent fleet
and its memory*, not the clinicians themselves. **It is not a product
claim that AI replaces the care team.** The audience needs to
understand this in the first 60 seconds of the demo. Every role
description below carries an "In production" sidebar that makes this
explicit again, and the demo presenter should reinforce it verbally
whenever there's a natural moment.

Specific language to use during the demo:

- "The Inpatient Nurse agent helps the nurse on shift hold context
  across the 12-hour handoff"
- "The PT agent recalls what previous PTs have noted so the working
  PT doesn't have to re-derive it"
- "Each agent is the clinician's interface to the team's shared memory"

Specific language to avoid:

- "The agent decides..."
- "The agent diagnoses..."
- "The agent treats..."
- "Fully automated care..."

## MemoryHub vs. Clinical Decision Support

The audience for this demo almost always already has CDS deployed (or
is planning to). The pitch must be unambiguous that MemoryHub is
*complementary* to CDS, not competitive with it.

### What CDS does in this scenario (we don't try to do this)

In an inpatient stroke rehabilitation unit, the CDS layer handles:

- Drug-drug and drug-allergy checks on the secondary stroke prevention
  regimen
- Anticoagulation dosing recommendations and INR monitoring alerts
- Dysphagia diet orders and swallow study results in CPOE
- NIHSS, FIM, mRS scores in structured assessment flowsheets
- Best-practice advisories for VTE prophylaxis, fall risk, skin
  breakdown, and discharge medication reconciliation
- Evidence-based recommendations for antiplatelet therapy, statin
  initiation, blood pressure targets

These all live in the EHR and the CDS layer above it. They're not what
this demo is about, and we should not pretend otherwise. **The medication
reconciliation that catches a missing dual-antiplatelet window is a CDS
job, not a MemoryHub job.** If someone in the audience asks about it,
the right answer is "that's exactly the kind of thing your CDS does, and
MemoryHub is designed to live alongside it, not duplicate it."

### What MemoryHub holds in this scenario (this is what we demo)

The soft, contextual, narrative, and operational memory the EHR and
CDS layer don't try to hold:

- **Patient narrative context** — what makes this particular patient
  tick, his goals beyond the structured ones, what works and doesn't
  work for him personally
- **Care team tribal knowledge** — practices the team uses that aren't
  in the policy manual
- **Cross-encounter narrative continuity** — the story that connects
  inpatient rehab to outpatient PT to community reintegration
- **Agent-operational memory** — what the agent fleet has learned about
  how it works together for this patient

Every memory example below falls into one of these categories. None of
them duplicate CDS or EHR functionality.

## Source guideline

Primary source: [VA/DoD Clinical Practice Guideline for Management of
Stroke Rehabilitation, Version 5.0, May
2024](https://www.healthquality.va.gov/HEALTHQUALITY/guidelines/Rehab/stroke/VADOD-2024-Stroke-Rehab-CPG-Full-CPG_final_508.pdf).

The guideline's Sidebar 5a enumerates 15 named clinical roles with
explicit jurisdictions. Sidebar 5b maps which roles assess which
impairment categories. The patient archetype below is designed to
naturally activate ten of those roles in a way that gives each agent a
meaningful job to do.

The guideline starts at "patient identified as stroke." The pre-rehab
acute hospitalization phase is governed by AHA/ASA stroke guidelines
that the VA/DoD CPG references but does not detail. Where this scenario
includes acute-hospital details, we're inventing plausible content
consistent with AHA/ASA recommendations and labeling it as such.

## Patient archetype

**Mr. Marcus Reeves** is a 64-year-old retired postal worker and
Vietnam-era Marine veteran who lives at home with his wife in a one-story
house. He has a history of well-controlled hypertension, type 2
diabetes, and prior tobacco use (quit 10 years ago). He stays active by
coaching his grandson's little league team in the spring and woodworking
in his garage workshop year-round.

On the morning of the scenario, his wife notices him slumping in his
chair at breakfast with slurred speech and unable to lift his right
arm. She calls 911. EMS transports him to the nearest community
hospital (not a VA facility) where imaging confirms a left middle
cerebral artery ischemic stroke. He receives acute stroke care at the
community hospital for three days, then transfers to the VA medical
center on day 3 for inpatient rehabilitation.

His initial deficits at VA admission:

- Right hemiparesis, arm worse than leg
- Mild expressive aphasia
- Moderate dysphagia
- (Post-stroke depression emerges during week 2 of inpatient rehab)

The goals he and his wife state during the admission conversation:

- Return home rather than go to long-term care
- Walk independently with a cane
- Drive again
- Resume coaching his grandson's little league team in the spring

This archetype was chosen to naturally activate ten agents from the 15
roles enumerated in Sidebar 5a of the source guideline, without any
agent feeling like padding. The dysphagia gives SLP a swallowing
workstream alongside the aphasia workstream. The driving goal pulls in
both PT (visual scanning, reaction time during gait training) and OT
(formal driving evaluation). The post-stroke depression activates
behavioral health. The community-hospital-to-VA transfer activates
pharmacy and case management at a natural handoff point. The patient's
expressed personal goals activate the narrative-context memory the demo
is built around.

## The agent fleet (10 roles)

Each agent is the human clinician's interface to the team's shared
memory. The "In production" sidebar on each role makes explicit who
operates the agent in real deployment.

### 1. Acute Care Hospitalist (community hospital, non-VA)

Owns the acute stroke admission at the community hospital. Coordinates
the imaging, the initial assessment, the secondary prevention regimen,
and the transfer to the VA. This is the agent that most clearly
illustrates the cross-system handoff problem MemoryHub helps with.

> **In production**: the hospitalist on duty at the community ED chats
> with this agent during the admission, and again during the transfer
> handoff. The agent surfaces "what does the receiving VA team need to
> know that won't fit in the standard transfer summary?"

### 2. VA Inpatient Rehab Physiatrist (PM&R)

Owns the inpatient rehabilitation admission at the VA. Per Sidebar 5a:
"rehabilitation management, oversight, and direction." The agent is
present during the admission conversation, the weekly team conferences,
and the discharge planning meeting.

> **In production**: Dr. Patel, the attending physiatrist, chats with
> this agent before walking into the patient's room each morning,
> recalling what the rest of the team has noted overnight that she
> needs to integrate into the day's plan.

### 3. Inpatient Rehab Nurse

Owns continuity across nursing shifts. Bowel and bladder management,
skin care, medication administration, patient education, family
communication. The agent that most clearly illustrates the shift-handoff
problem.

> **In production**: the inpatient rehab nurse on shift chats with
> this agent during handoff at the start of each shift, recalling the
> 24-hour story of the patient that doesn't fit in the structured
> handoff form.

### 4. Physical Therapist

Owns gait, balance, motor function, transfers, and durable medical
equipment recommendations. The PT agent is active throughout the
inpatient rehab phase and continues into outpatient.

> **In production**: the working PT chats with this agent before the
> day's session to recall what previous sessions surfaced about how
> the patient responds to specific interventions, and what his stated
> preferences are.

### 5. Occupational Therapist

Owns activities of daily living, instrumental ADLs, home safety,
adaptive equipment, and the formal driving evaluation (per Sidebar 5b,
driving assessment is OT's jurisdiction). Significant overlap with PT
on the motor and equipment sides — this overlap is where the team's
contradiction-detection demo moment lives.

> **In production**: the working OT chats with this agent to recall
> what the patient has said about home setup, what's worked in
> retraining ADLs, and what the formal driving evaluation found.

### 6. Speech-Language Pathologist (owns aphasia AND dysphagia)

Owns two distinct workstreams for this patient: expressive aphasia
(communication) and dysphagia (swallowing). Per Sidebar 5b, SLP is
involved in cognition, communication, and swallowing/nutrition
assessment categories. Having one agent own both lets the demo show
how a single agent can hold multiple memory threads about the same
patient.

> **In production**: the SLP chats with this agent before each session
> to recall the dysphagia diet trajectory, the communication strategies
> the patient responds to, and what the patient's wife has reported
> about his communication at home.

### 7. Behavioral Health (Neuropsychologist or Psychiatrist)

Owns depression screening, treatment, and cognitive assessment.
Activates in week 2 of the scenario when post-stroke depression
emerges. Also owns family/caregiver support conversations.

> **In production**: the behavioral health clinician chats with this
> agent to recall the patient's affect over time, what his wife has
> shared about caregiver burden, and the rationale behind the current
> treatment plan.

### 8. Clinical Pharmacist

Owns medication reconciliation across the community-hospital-to-VA
handoff, secondary stroke prevention regimen, and drug interaction
screening. **The structured medication reconciliation work itself
happens in CDS** — this agent helps the pharmacist hold the
*narrative context* around the patient's medication history that
doesn't fit in CDS (prior bad reactions, his preference for
once-daily dosing, his stated skepticism about taking statins).

> **In production**: the inpatient pharmacist chats with this agent
> when reviewing the patient's medication regimen, recalling the
> patient's stated preferences and the team's prior medication
> conversations with him and his wife.

### 9. Case Manager / Social Worker

Owns transitions across all four care settings, the home assessment
conversation, financial resources, caregiver burden assessment, and
the discharge planning meeting. This is the role the source guideline
explicitly recommends at every transition point — the role that most
closely resembles "MemoryHub described as a clinical job."

> **In production**: the case manager chats with this agent
> throughout the patient's journey to surface what the team's shared
> understanding of the home situation is, what his wife is
> communicating, and where the team's plan needs adjustment based on
> social context the clinical team might miss.

### 10. VA Primary Care Provider (PACT team)

Owns long-term management after the patient returns home and the
inpatient rehab episode closes. Receives the warm handoff from the
inpatient rehab team. Manages secondary prevention long-term, monitors
for late functional decline, and is the patient's continuous medical
home.

> **In production**: the PCP chats with this agent before the
> patient's first post-discharge appointment, recalling the team's
> shared story of the rehab episode beyond what's in the structured
> discharge summary.

The Neurologist, Ophthalmology/Optometry, Recreation Therapy,
Dietetics, and Vocational Rehabilitation roles enumerated in Sidebar 5a
are *not* in this fleet. The patient archetype doesn't naturally need
their workstreams, and adding them would inflate the agent count
without adding demo value. They are mentioned here so the audience
understands the fleet was deliberately scoped to ten roles, not
arbitrary.

## Workflow phases

Six phases tracking the patient from acute stroke to long-term primary
care followup. Each phase activates a subset of the agents and produces
specific memory touchpoints.

### Phase 1 — Acute hospitalization (community ED, days 0-3)

Active agents: Acute Care Hospitalist, Clinical Pharmacist (alerted to
incoming transfer)

The patient arrives at the community hospital, receives acute stroke
care, and is stabilized. The Acute Care Hospitalist agent helps the
hospitalist assemble the transfer summary. The VA-side Clinical
Pharmacist agent is notified of the incoming transfer and starts
holding context for the medication reconciliation conversation that
will happen at admission.

This phase is where the scenario starts to invent details not in the
VA/DoD Stroke Rehab CPG (which begins at "patient identified as
stroke"). We're keeping this phase brief and focused on the handoff.

### Phase 2 — VA inpatient rehab admission (days 3-5)

Active agents: PM&R Physiatrist, Inpatient Rehab Nurse, Clinical
Pharmacist, Case Manager, PT, OT, SLP

The patient transfers to the VA. PM&R conducts the disposition
assessment, screens for depression (negative at this point), identifies
functional impairments, and confirms acute inpatient rehab is
appropriate. Case Manager begins the discharge planning conversation
with the patient and his wife — this is where the patient's stated
goals enter the team's shared memory. PT, OT, and SLP each conduct
initial evaluations and contribute to the unified rehab plan.

This is the heaviest memory-write phase — most of the foundational
narrative context about the patient is captured here.

### Phase 3 — Inpatient rehab therapy (weeks 1-3)

Active agents: PT, OT, SLP, Inpatient Rehab Nurse, PM&R, Behavioral
Health (week 2 onward), Clinical Pharmacist

Daily individual therapy sessions. Mid-week 2: post-stroke depression
emerges. Behavioral Health is consulted; the team initiates
intervention. SLP advances the dysphagia diet on a deliberate
trajectory. OT begins home-safety planning conversations. PT
recommends a quad cane and starts gait training with the assistive
device.

This phase generates the most memory updates — daily small revisions
to the team's shared understanding of the patient.

### Phase 4 — Discharge planning and transition (week 3)

Active agents: Case Manager, Clinical Pharmacist, PM&R, all therapy
disciplines, Inpatient Rehab Nurse

Case Manager coordinates home assessment, equipment delivery, and
outpatient therapy referrals. Clinical Pharmacist reconciles the
medication list with the patient and his wife (the structured
reconciliation is in CDS; the agent holds the narrative context of
the conversation). PM&R writes the discharge summary. Patient
discharges home with outpatient PT, OT, SLP, and behavioral health
follow-up plus a primary care appointment in two weeks.

### Phase 5 — Outpatient rehab and community reintegration (weeks 4-16)

Active agents: PT, OT, SLP (outpatient context), Behavioral Health,
Case Manager (transition oversight), VA Primary Care Provider (week 6
onward)

Outpatient therapy continues. Goals are reassessed at week 8 and
week 12. The driving evaluation question becomes active around week
10 — OT-led, but PT contributes balance and visual scanning
observations. Behavioral health follow-up begins to taper as the
depression responds to treatment.

This is where the cross-care-setting memory continuity really pays
off — outpatient clinicians read what the inpatient team learned
without re-deriving it.

### Phase 6 — Long-term primary care followup (months 4+)

Active agents: VA Primary Care Provider (primary), Behavioral Health
(intermittent), Case Manager (case closure)

PCP assumes longitudinal management. Monitors for late functional
decline. Continues secondary prevention. Behavioral Health follow-up
tapers further. Case Manager closes the case but documents
reactivation triggers in shared memory for future episodes.

## Memory touchpoints

These are the specific memory operations the demo will showcase.
Every example below is **narrative context, care team tribal
knowledge, agent-operational state, or cross-encounter narrative
continuity** — none of it duplicates the EHR or CDS.

### Touchpoint 1: Patient-stated goals (Phase 2)

Case Manager writes a memory at project scope capturing the patient's
goals in his own words, with a `provenance` branch citing the
admission conversation:

> "Wants to return home. Wants to walk independently with a cane.
> Wants to drive again. Wants to coach his grandson's little league
> team next spring."

**Why it's narrative, not structured**: the EHR holds a structured
"functional goal" field and the team will populate it. But the
structured field can't hold the *meaning* — that the driving goal
matters because of the grandson's little league, that the
independence goal matters because of his identity as a coach. Every
therapy discipline reads this memory and frames their interventions
to support those personal goals, not just the structured ones.

**Why it pulls its weight in the demo**: this is the memory the
audience will most easily understand. "If you can't articulate your
patient's actual goals beyond the structured fields, you can't
deliver person-centered care."

### Touchpoint 2: Patient narrative context (Phase 3)

Inpatient Rehab Nurse writes memory:

> "Patient mentioned during morning care that he doesn't want to
> bother the staff and won't use the call light unless he's
> 'really desperate.' Team practice for this patient: round on
> him every 90 minutes regardless. He won't ask, but he wants the
> contact."

**Why it's narrative context**: nothing in the EHR captures
"patient won't use call light because he doesn't want to bother
anyone." The fall-risk score in CDS would flag him as fall risk
based on structured factors; this memory is the team's *response*
to that risk that adapts to who this particular patient is.

**Why it pulls its weight**: this is the kind of soft knowledge that
walks out the door when nursing staff turn over. The PCT on Tuesday
night might never encounter this fact unless someone tells her —
and "someone tells her" is exactly what MemoryHub does.

### Touchpoint 3: Team tribal knowledge (Phase 3)

PM&R agent holds a memory written by Dr. Patel last month, before
this patient ever arrived:

> "On this unit, we initiate SSRIs over SNRIs for post-stroke
> depression in patients with hypertension. Reasoning: SNRIs can
> elevate blood pressure and most of our post-stroke patients are on
> antihypertensive regimens that we don't want to fight. Not formal
> protocol — clinical judgment learned from this population."

When the patient develops post-stroke depression in week 2,
Behavioral Health reads this memory before recommending an
antidepressant. The recommendation lands consistently with team
practice without anyone having to look it up.

**Why it's narrative**: this is *not* a guideline-based recommendation
that CDS would surface. The guideline doesn't prefer SSRIs over SNRIs
for this indication. It's a team practice based on the specific
patient population this unit serves — the kind of judgment that lives
in the heads of the unit's senior clinicians and never makes it into
formal documentation.

### Touchpoint 4: Cross-encounter narrative continuity (Phase 4 → Phase 5)

PT agent writes a memory at the end of inpatient rehab:

> "Patient does best with task-specific gait training when the task
> is framed around little league coaching ('walk to the pitcher's
> mound and back'). Generic gait drills bore him and he disengages.
> Outpatient PT should know this — same patient, same motivation
> dynamics."

The outpatient PT, six weeks later, reads this memory before the
first outpatient session. The session opens with task-specific
training framed around coaching activities. The patient engages
immediately. The clinician didn't have to spend three sessions
re-discovering what the inpatient team already knew.

**Why it's the heart of the demo**: this is the cross-care-setting
continuity that's *exactly* what existing tooling fails at. The
inpatient team's discharge summary has structured PT goals and
recommendations. It does not have "patient is bored by generic
drills, frame everything around coaching." That's the soft knowledge
that disappears at every handoff in current practice.

### Touchpoint 5: Agent-operational memory (Phase 3)

Inpatient Rehab Nurse agent writes a memory about how the agent fleet
itself works:

> "When the SLP agent updates the dysphagia diet trajectory, the
> update lands at approximately 7am, not 6:30am as I was originally
> reading. Adjust handoff read schedule accordingly to avoid stale
> diet information at start of shift."

This is a memory the *agent fleet* writes about its own operational
patterns. No human clinician would write this. But the next time the
nursing agent is initialized for a similar patient, it inherits the
operational lesson.

**Why it's novel and interesting**: this is the most unfamiliar
memory category for the audience and the one that's most clearly
*not* something CDS or EHR would ever do. It's also the strongest
demonstration of why an agent fleet needs *its own* memory layer, not
just access to the existing clinical record.

### Touchpoint 6: Goal reassessment via update_memory (Phase 5)

At week 8, OT determines from the formal driving evaluation that the
patient's driving goal is achievable in approximately four more
months. OT calls `update_memory` on the original goals memory
(touchpoint 1), preserving the version history:

> Updated: "Driving goal: now estimated achievable by month 5
> post-stroke based on week-8 driving evaluation results. Original
> goal preserved in version history."

The team can read the current state ("achievable by month 5") and the
history ("at admission, was an aspirational goal with no timeline").
A future audit can reconstruct exactly when the team's understanding
shifted and why.

**Why it's a good MemoryHub hygiene demo**: shows the difference
between *revising* a memory (preserving history, single canonical
source) and *proliferating* memories (writing a new "actually..."
memory each time, leaving the team unsure which one to trust).

### Touchpoint 7: Late functional decline trigger (Phase 6)

At month 6, PCP notes a small regression in gait at the routine
follow-up. PCP writes a memory at user scope (her own observation,
not yet team-shared) and creates a relationship to the original
baseline memory from inpatient discharge:

> "Mild gait regression at month-6 followup compared to discharge
> baseline. Could be deconditioning, could be early late-functional
> decline per Sidebar 7. Want to watch over next 2 visits before
> escalating to PT consult."

**Why it's narrative continuity**: the structured gait assessment
score is in the EHR. The *clinical reasoning* about whether to act on
it now or watch over time is the kind of thing PCPs hold in their
heads or in unstructured note narrative. MemoryHub holds it
explicitly so the next visit's PCP (who might be a different person
covering the panel) inherits the watching-and-waiting context.

## Contradiction moments

Two specific moments where one agent's memory conflicts with another's,
and the team uses MemoryHub's contradiction detection to surface and
resolve the disagreement. Both are about *narrative interpretation*,
not structured clinical assessment.

### Contradiction 1: PT vs. OT on the cane

**Setup** (Phase 3, week 2): PT writes memory at project scope:

> "Patient seemed hesitant about using the cane during gait training
> today. Body language read like reluctance. Might be a confidence or
> acceptance issue — OT might want to address it during ADL work."

**Contradiction** (Phase 3, week 2, two days later): OT writes a
memory and calls `report_contradiction` against PT's earlier memory:

> "Talked with patient about the cane during ADL session. He's not
> hesitant about using it functionally — he's worried about how he'll
> look at his grandson's ballgames using a cane. It's an emotional
> issue tied to his identity as a coach, not a functional acceptance
> issue. Different intervention needed: peer support group and a
> conversation about how other coaches manage with assistive devices,
> not more confidence-building during gait training."

**Resolution**: the team reads OT's correction in the next morning
huddle. The rehab plan adjusts: PT continues gait training with the
cane normally, OT incorporates the emotional dimension into ADL work,
and Case Manager looks into peer support resources. PT's original
memory is preserved in the contradiction history but is no longer the
team's working interpretation.

**Why this contradiction is good for the demo**: it's a *narrative
interpretation* disagreement, not a structured clinical disagreement.
CDS and the EHR have no way to surface or resolve this kind of
conflict — the disagreement isn't even visible in structured data.
And the resolution doesn't require throwing out the original
observation; it requires understanding it differently.

### Contradiction 2: Inpatient PM&R vs. outpatient team on plateau prediction

**Setup** (Phase 4, discharge): PM&R writes a discharge memory:

> "Expect motor function gains to plateau in 8-12 weeks based on
> typical recovery curves for this stroke severity and the patient's
> baseline conditioning."

**Contradiction** (Phase 5, week 10): Outpatient interdisciplinary
team writes memory and calls `report_contradiction`:

> "At week 10, patient is showing continued measurable gains in motor
> function — not yet plateauing. Original 8-12 week plateau
> prediction is being superseded by observed trajectory. Adjust
> long-term goal expectations upward."

The outpatient team also calls `update_memory` on the original
plateau prediction, supersedng it with the new estimate.

**Why this contradiction is good for the demo**: it's a *prognosis
revision* based on actual observation contradicting an earlier
prediction. This kind of revision happens constantly in clinical
practice but is rarely captured explicitly — the new prognosis
quietly replaces the old one in conversation, and the original
prediction is forgotten. MemoryHub makes the revision explicit and
auditable.

## PHI moments

Two specific moments where an agent attempts to write a memory
containing PHI and the curation pipeline catches it. Both are
narrative-context memories slipping in patient identifiers, not
structured clinical data.

### PHI moment 1: Goals memory leaks identifiers

When the Case Manager agent attempts to write touchpoint 1 (the
patient-stated goals memory), it tries:

> "Marcus wants to return to driving his grandson Tyler to little
> league practice in Manassas."

The curation pipeline catches the combination of patient first name +
grandson's first name + city. Each individually is a quasi-identifier;
in combination, they're a re-identification risk. The pipeline
quarantines the memory and the agent rewrites:

> "Patient wants to return to driving family members to recreational
> activities. Specifically, the patient identifies coaching his
> grandson's youth sports team as a key motivator and wants to be able
> to drive to those activities."

The clinical content is preserved. The identifying combination is
removed. The patient's narrative motivation is still in the memory.
A clinician reading this (in production) would still understand
exactly what to support; the memory just doesn't carry the
re-identification risk.

### PHI moment 2: Behavioral health note leaks Veteran-identifying details

When the Behavioral Health agent attempts to write a memory about the
patient's emerging depression, it tries:

> "Patient mentioned his Vietnam tour at Khe Sanh in 1968 came up in
> dreams since the stroke. Discussed referral for trauma-informed
> care."

The curation pipeline catches the combination of military service +
specific battle + year. For a Veteran, this combination is a
quasi-identifier triple — the population of Marines who were at Khe
Sanh in 1968 is small enough that combined with other context this
patient could be identified. The pipeline quarantines and the agent
rewrites:

> "Patient reported combat-related dreams resurfacing post-stroke.
> Discussed referral for trauma-informed care."

The clinical action item is preserved (referral for trauma-informed
care). The combat-related context is preserved (it's the reason for
the referral). The specific battle, year, and unit details are
removed.

**Why these PHI moments are the right ones for the demo**: they're
realistic. They're the kind of natural-language-bleeding-into-memory
slip that any human clinician might write into a note without
thinking. They're not contrived "oops the agent wrote a Social
Security Number" moments. The audience will see them and recognize
the pattern from their own practice.

## What's drawn from the source vs. what's invented

Honest disclosure of what the demo invents beyond the source guideline.

**Drawn from the VA/DoD Stroke Rehab CPG (2024)**:

- The structure of post-acute rehabilitation as moving across multiple
  care settings (inpatient rehab → outpatient → community → primary
  care)
- The roles enumerated in Sidebar 5a and their jurisdictions in
  Sidebar 5b
- The depression screening recommendation and the timing (post-stroke
  depression often emerges in the inpatient rehab phase)
- The case management recommendation at every transition
- The functional impairment categories and which roles assess them
- The general shape of the inpatient → outpatient → community → PCP
  arc

**Invented for this scenario, consistent with the guideline but not
specified in it**:

- The patient archetype (Marcus Reeves) — entirely synthetic
- The community-hospital-to-VA transfer specifics (the source
  guideline mentions Veterans may receive acute care outside the VA
  but doesn't detail the handoff)
- The specific cane-acceptance contradiction (the kind of disagreement
  the structural overlap in Sidebar 5b makes likely, but the specific
  example is invented)
- Dr. Patel's tribal knowledge about SSRIs over SNRIs (an invented
  example of the kind of practice memory MemoryHub is designed to
  hold)
- The dysphagia diet timing rule about "never Friday after 3pm" (an
  invented example of unit-level tribal knowledge)
- The specific therapy session content and protocols (the guideline
  endorses task-specific practice but doesn't prescribe protocols)

**Drawn from AHA/ASA stroke guidelines** (which the VA/DoD CPG
references but doesn't detail):

- The acute hospital phase content
- The secondary prevention regimen general shape

**Sidestepped entirely**:

- VA eligibility, TRICARE prior authorization, and other administrative
  details that would distract from the memory story
- Specific anticoagulation dosing decisions (CDS territory)
- Specific therapy session protocols and intervention parameters

## Open questions

1. **Should the patient's wife be modeled as an agent?** Sidebar 5b
   lists "family and caregiver support" as a needs category. The
   patient focus group findings in the source guideline emphasize
   caregiver burden heavily. There's a real question of whether the
   wife is an agent (who can read certain memories), a stakeholder
   the agents write *about*, or both. For the demo, we're treating
   her as a stakeholder (mentioned in memories, not an agent
   herself). Open to revisiting if it strengthens the narrative.

2. **How do we model the EHR in the demo?** We need *some*
   representation of the EHR so the audience understands MemoryHub is
   alongside it, not replacing it. Options: a stub "EHR" service that
   the agents reference but the demo doesn't show; a visible "EHR"
   panel in the harness that shows what's in structured data and
   what's in memory; or just verbal narration ("the EHR holds the
   structured assessment scores; the memories you're seeing are
   alongside that"). Probably verbal narration is sufficient.

3. **Demo length and pacing.** The scenario above could be told in 5
   minutes (cherry-pick the killer moments) or 30 minutes (walk
   through every phase). The first demo should aim for 15-20 minutes
   of scenario walkthrough plus introduction and Q&A, totaling
   25-30 minutes. We should pre-pick which 4-5 memory touchpoints
   land in the live demo and which we mention in passing.

4. **How explicit do we make the agent-operational memories?**
   Touchpoint 5 (the agent learning when to read SLP updates) is the
   most novel category but also the most abstract. There's a risk it
   confuses the audience or feels like inside baseball. Counter-risk:
   leaving it out misses the strongest "this is something only an
   agent fleet needs" demo moment. Likely answer: include it but
   frame it carefully ("this is the agent fleet learning about
   itself, the way human teams learn about each other").

5. **Animation visualization of agent coordination.** Stretch item per
   `../README.md` — circles with pulses going to and from
   the central core, agents talking to each other. If it's working,
   it'll dramatically improve the demo's emotional landing for
   non-technical audience members. If it's not, plain harness output
   plus narration is sufficient.

6. **Clinical SME validation.** This scenario was assembled from the
   source guideline and a worker's research, not from a clinician.
   Before we demo this to actual healthcare audiences, **we should
   have a clinician review the scenario for plausibility**. Errors
   that a clinician would immediately catch will undermine the entire
   demo's credibility. Even an informal review by one experienced
   rehab clinician would be enough to catch the most obvious
   problems.
