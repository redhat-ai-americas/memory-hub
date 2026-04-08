# SOC Threat Hunting and Incident Response: The Compromised Service Account

A working scenario for MemoryHub's second clinical demo, targeting a
technical security audience. Built around a realistic mid-severity
incident at a mid-sized organization, with a fleet of ten agents that
help the SOC team hold their accumulated experience across investigators,
shifts, and prior incidents.

## The phrase

> **MemoryHub holds the context that makes security decisions go well.**

Same shape as the clinical scenario, intentionally. The platform's value
proposition is consistent across domains: the decisions are made by
humans using their judgment, the existing tooling makes recommendations,
and MemoryHub holds the surrounding context — the cross-incident
patterns, the analyst tribal knowledge, the operational lessons, and
the agent fleet's own learning — that determines whether security
decisions land well.

## Agents support humans, they don't replace them

Critical to read before the rest of the scenario.

**In production, every agent in this fleet is operated by a human
analyst or responder.** The Tier 1 agent is the interface a working
Tier 1 analyst uses to compare notes with the team's accumulated
experience. The Forensics agent is the interface a working forensics
specialist uses to recall how the team has approached similar artifacts
in past incidents. The Incident Commander agent is the interface a
working IC uses during a war room to surface what the team learned in
prior incidents that's relevant right now.

For the demo, Claude (or whoever is running the harness) plays the
role of all the analysts. This is because we are demoing the *agent
fleet and its memory*, not the analysts themselves. **It is not a
product claim that AI replaces SOC staff.** The audience for a
cybersecurity demo is unusually attuned to this — SOC managers are
desperate for *more* effective analysts, not for fewer analysts, and
any pitch that smells like "AI replaces tier 1" will lose the room
in 30 seconds.

The opposite framing is exactly what the audience wants to hear: AI
that helps analysts retain hard-won institutional knowledge, recall
prior incident lessons in the moment, and onboard junior staff faster
by giving them access to the team's accumulated experience.

Specific language to use during the demo:

- "The Tier 1 agent helps the analyst on shift recall what the team
  learned from similar alerts last quarter"
- "The Forensics agent surfaces the artifacts the team has historically
  found valuable for this kind of investigation"
- "Each agent is the analyst's interface to the SOC's accumulated
  operational memory"

Specific language to avoid:

- "The agent decides..."
- "The agent contains..."
- "The agent automatically remediates..."
- "Auto-containment" (the third rail of SOC demos — never propose
  unattended containment actions)
- "Reduces headcount" / "fewer analysts needed"

## MemoryHub vs. Detection and Response Tooling

The audience for this demo has a stack. They have a SIEM. They have
EDR. They probably have SOAR. They have threat intelligence feeds.
They've spent millions on this stack and they trust it. Trying to
compete with any of it loses the room immediately. The pitch must be
unambiguous that MemoryHub is *complementary* to the existing stack.

### What the existing detection-and-response stack does

In a modern SOC, the stack handles:

- **SIEM** (Splunk, Sentinel, Chronicle, Elastic): log aggregation,
  correlation rules, behavioral anomaly detection, alerting
- **EDR/XDR** (CrowdStrike, SentinelOne, Defender for Endpoint): host
  telemetry, behavioral detection, response actions
- **NDR** (Darktrace, ExtraHop, Vectra): network detection, lateral
  movement identification
- **SOAR** (Splunk SOAR, Cortex XSOAR, Tines): playbook automation,
  case management, ticket integration
- **Threat Intelligence Platforms** (Recorded Future, Mandiant,
  Anomali): IOC feeds, attribution data, campaign tracking
- **Vulnerability Management** (Tenable, Qualys): exposure surface
  management

These do detection, alerting, response automation, and structured
threat data. They're well-funded, well-understood, and well-monetized.
**MemoryHub does not try to be any of them.**

### What MemoryHub holds in this scenario

The experience layer the existing stack can't easily hold:

- **Incident-to-incident pattern memory** — "We've seen this initial
  access pattern before. IR-2024-117. Phishing email with an Office
  365 lure, lateral movement via Service Principal abuse. Check for
  similar SP creation events in the same timeframe even before the
  alert fires." Threat intel feeds carry IOCs and campaign attribution;
  MemoryHub carries the *story* of how *this team* responded last time
  and what *they* learned.
- **Analyst tribal knowledge** — "Tier 1 has learned: alerts on
  `svc-backup` during business hours are usually maintenance, but
  alerts after 8pm are 80% worth escalating. Not a formal rule, just
  team experience." This kind of soft knowledge gets passed during
  shift handoff and walks out the door when staff leave. It's exactly
  what an AI memory layer should hold.
- **Operational lessons across incidents** — "Last time we rotated the
  breakglass credential during an incident, the rotation broke our
  backup system for 6 hours. Coordinate with the backup admin BEFORE
  rotation, not after." The lesson is in the postmortem document, but
  postmortems get filed and forgotten. MemoryHub keeps them
  operationally accessible at the moment of decision.
- **Per-customer context** (especially for MSSPs serving multiple
  organizations) — "This client's CISO prefers notification of any
  potential PII exposure within 2 hours, even if uncertain. Her
  previous company had a delayed-notification incident and she's
  sensitive about it." The kind of context that's not appropriate
  to bake into a SOAR playbook but is critical for getting the
  notification right.
- **Agent fleet operational state** — "When investigating
  `outlook.exe` child processes, the Forensics agent has learned to
  ignore `ai.exe` — it's the Microsoft Copilot integration, not
  malicious despite triggering suspicious-spawn rules. We re-derived
  this three times before we wrote it down."

The relationship is **complementary**. The EDR fires the alert.
MemoryHub holds the memory that says "we ruled this kind of alert as
benign three months ago after an 8-hour investigation — here's the
hunting query we built then, run it before opening a new case."

## Source material

This scenario is designed against published incident response frameworks
rather than a single document:

- **NIST SP 800-61 Rev. 2** (Computer Security Incident Handling Guide)
  for the phase structure
- **CISA Federal Government Cybersecurity Incident and Vulnerability
  Response Playbooks** for response activity vocabulary
- **MITRE ATT&CK** for the technique vocabulary the agents reference
- **SANS SEC504** (Hacker Tools, Techniques, and Incident Response)
  course outlines for the analyst-skill assumptions

The incident archetype is synthetic but designed to be realistic for a
mid-sized organization (not a Fortune 50 with a 50-person SOC, not a
small business with no SOC at all — somewhere in between).

## Incident archetype

**Organization**: MidWest Financial Services Group, a regional bank with
~3,000 employees and a 12-person SOC. Relevant tooling: Splunk SIEM,
CrowdStrike EDR, ProofPoint email security, Active Directory with Azure
AD hybrid identity, file servers running on Windows Server. The SOC
operates 24/7 with 3 shifts plus an on-call IR team.

**The incident**:

At 02:14 AM on a Tuesday, a Tier 1 analyst sees a SIEM alert: "Unusual
logon pattern for service account `svc-reporting`." The account is used
for an automated nightly reporting job that runs at 23:00 every day.
The current alert shows the account being used at 02:14 from a
workstation (`WKSTN-FIN-082`) that does not normally use this credential.

Initial Tier 1 investigation in the next 20 minutes finds:

- The svc-reporting credential was used from `WKSTN-FIN-082` to
  authenticate to `FILESVR-CORP-03`
- 4 minutes later, the same credential was used to enumerate shares on
  `FILESVR-CORP-03`
- 11 minutes after that, the same credential was used to copy files to
  a directory `\\FILESVR-CORP-03\admin$\TEMP\reports2024\`

Tier 1 escalates to Tier 2 at 02:38 AM. The on-call IR team is paged
at 02:55 AM. Over the next several hours of investigation, the team
discovers:

- The credential was harvested via a targeted phishing email 11 days
  ago. The user (a finance department analyst whose account is used
  by the service) opened a Microsoft 365 lure and entered her
  credentials in a fake login page.
- The attacker has been quietly enumerating the environment for 11
  days, primarily Active Directory queries and SMB share enumeration,
  blending into normal traffic.
- 6 hours before the alert fired, the attacker started staging
  approximately 47 GB of finance documents in the TEMP directory.
- The detection was a CrowdStrike behavioral rule that fired when the
  staging volume crossed a 30 GB threshold. Earlier activity stayed
  below detection thresholds.
- No data has been exfiltrated yet — the staging is in progress, the
  attacker hasn't moved the data out of the network.
- The attacker's tooling pattern matches an opportunistic
  credential-theft-to-extortion campaign that the team's threat intel
  feed has been tracking for the past quarter.

**Why this archetype**: it's mid-severity (not catastrophic, not trivial),
realistic for a regional bank, doesn't require APT-grade sophistication
to follow, naturally activates ten distinct SOC roles, includes a clean
"we've seen this before" cross-incident learning moment, and has
natural points for narrative-interpretation contradictions.

## The agent fleet (10 roles)

Each agent is the human analyst's interface to the SOC's accumulated
memory. The "In production" sidebar on each role makes explicit who
operates the agent in real deployment.

### 1. Tier 1 SOC Analyst

Owns initial alert triage and basic investigation. Decides whether to
escalate, close as benign, or assign for further investigation. The
alert at 02:14 lands on this agent first.

> **In production**: the working Tier 1 analyst on the night shift
> chats with this agent during alert triage to recall how the team has
> handled similar alerts in the past, and to surface the team's
> heuristics about when to escalate vs. when to close.

### 2. Tier 2 SOC Analyst

Owns deep investigation after Tier 1 escalation. Forms initial
hypotheses about scope, attacker behavior, and potential impact.
Hands off to incident response when the investigation confirms a
real incident.

> **In production**: the Tier 2 analyst on shift chats with this
> agent during investigation to recall similar past investigations,
> compare hypothesis paths, and surface what worked and what didn't
> in those cases.

### 3. Threat Intelligence Analyst

Owns correlation with known campaigns, IOC enrichment, and
attribution analysis. The threat intel agent surfaces "have we seen
this attacker pattern before" both from external feeds and from the
team's own past incidents.

> **In production**: the on-call threat intel analyst chats with this
> agent during incidents to surface campaign-level context that
> connects the current incident to broader trends.

### 4. Threat Hunter

Owns proactive hunting for related compromise activity that might not
have triggered alerts. During the current incident, the Threat Hunter
agent runs hypothesis-driven searches for other affected systems.

> **In production**: the threat hunter on the team chats with this
> agent to recall hunting hypotheses from prior shifts and to surface
> patterns the team has been tracking.

### 5. Forensics Specialist

Owns host-level artifact collection and timeline reconstruction. For
this incident, the Forensics agent helps reconstruct the 11-day
attacker activity timeline from EDR telemetry, Windows event logs,
and file system artifacts.

> **In production**: the forensics specialist chats with this agent
> to recall the team's standard artifact collection patterns and the
> "gotchas" the team has encountered in past forensic investigations
> (e.g., the `ai.exe` false positive).

### 6. Network Analyst

Owns network traffic analysis, command-and-control identification,
and lateral movement tracing. For this incident, the Network agent
helps determine whether the attacker has any active C2 channels and
whether data has been exfiltrated.

> **In production**: the network analyst on shift chats with this
> agent to recall the team's standard analysis approaches and to
> surface prior C2 patterns that match the current incident.

### 7. Incident Commander

Owns the overall response coordination. Manages stakeholder
communication, decision-making cadence, and resource allocation
during the incident. Activates when the IR team is paged at 02:55.

> **In production**: the on-call incident commander chats with this
> agent throughout the incident to recall how the team handled
> similar incidents, what the standard escalation paths look like,
> and what stakeholder management approach has worked in past
> incidents.

### 8. Endpoint/EDR Admin

Owns containment actions on affected endpoints. Has the authority
(and the EDR tooling integration) to isolate hosts, kill processes,
quarantine files, and disable accounts at the endpoint level.
**Containment actions are always confirmed by a human before
execution** — the agent surfaces options, the human approves.

> **In production**: the endpoint admin on the team chats with this
> agent during containment to recall the operational lessons from
> past containment actions (the breakglass credential rotation
> backup-system breakage being a key example).

### 9. Identity/IAM Admin

Owns credential and access management actions. Credential rotations,
account disables, MFA enforcement, AD investigation, privileged
access audits. Activates as soon as the team confirms a credential
has been compromised.

> **In production**: the IAM admin chats with this agent to recall
> the team's standard credential-rotation playbook and the
> per-customer notification preferences.

### 10. Communications and Legal Liaison

Owns external notifications, regulatory communication, legal review,
and executive briefings. For this incident, the Comms agent helps
the team navigate the question of whether and when to notify the
finance department, executives, the bank's compliance team, and
potentially regulators.

> **In production**: the communications lead and the legal liaison
> chat with this agent during incidents to recall the organization's
> notification preferences, prior incident communications that
> worked or didn't work, and the regulatory landscape.

## Workflow phases

Seven phases, mapped loosely to NIST SP 800-61 incident response
lifecycle (Detection → Analysis → Containment → Eradication →
Recovery → Post-Incident Activity).

### Phase 1 — Detection (02:14 AM)

Active agents: Tier 1 SOC Analyst

The CrowdStrike behavioral alert fires. The Tier 1 agent helps the
analyst triage. The first memory-driven moment of the demo: the
agent recalls a similar pattern from 4 months ago that turned out to
be a real incident, surfaces it, and recommends escalation rather
than auto-close.

### Phase 2 — Initial triage and escalation (02:14 - 02:55)

Active agents: Tier 1 SOC Analyst, Tier 2 SOC Analyst

Tier 1 escalates to Tier 2 at 02:38. Tier 2 conducts deeper
investigation. The team confirms unauthorized access. The IR team is
paged at 02:55. The Threat Intel agent is also activated to begin
correlation work.

### Phase 3 — Investigation (02:55 - 06:00)

Active agents: Tier 2, Threat Intel, Forensics, Network, Threat
Hunter, Incident Commander (joins at 03:15)

Investigation runs in parallel across forensics, network, and threat
intel workstreams. The Threat Hunter agent runs proactive searches
for related compromise. The Incident Commander agent coordinates and
holds the synthesized picture.

This is the phase where the cross-incident memory pays off most: the
team rapidly recognizes patterns from the prior IR-2024-117 incident
and uses what they learned then to direct the current investigation.

### Phase 4 — Scoping (04:00 - 06:30, overlapping with investigation)

Active agents: Forensics, Network, Threat Hunter, Threat Intel, IC

The team determines: how deep does this go? How many systems are
affected? Has data been exfiltrated? What credentials are
compromised? What's the attacker's likely next move? Hypothesis
formation and revision happens rapidly here.

### Phase 5 — Containment (06:00 - 08:00)

Active agents: Endpoint Admin, Identity Admin, IC, Comms

The team executes containment. Credentials are rotated. Affected
endpoints are isolated. Network paths are blocked. The Comms agent
begins drafting notifications for executives.

This phase is where the "last time we rotated the breakglass
credential it broke backup for 6 hours" memory pays off — the team
coordinates with the backup admin BEFORE rotation, not after.

### Phase 6 — Eradication and recovery (08:00 - 18:00)

Active agents: Forensics, Endpoint Admin, Identity Admin, IC, Comms

Attacker tooling is removed from affected systems. Compromised
accounts are reset. Affected systems are rebuilt or remediated.
Stakeholder notifications go out. The team begins planning the
return to normal operations.

### Phase 7 — Post-incident activity (24-72 hours later)

Active agents: All agents, especially Threat Intel, Forensics, IC

The team conducts the post-incident review. Lessons learned are
captured *into shared memory* — this is the phase where the demo
shows MemoryHub being explicitly used to preserve what was learned
for future incidents. The team writes memories that will be read by
the agents in the next incident.

## Memory touchpoints

Specific memory operations the demo will showcase. Every example is
narrative context, analyst tribal knowledge, agent-operational state,
or cross-incident learning — none duplicate SIEM, EDR, or threat intel
feed functionality.

### Touchpoint 1: Cross-incident pattern recognition (Phase 1)

When the Tier 1 agent triages the initial alert, it searches shared
memory for patterns matching "unusual service account logon, off-hours,
followed by SMB enumeration." It finds a high-relevance memory written
by Tier 2 analyst Maya Chen four months ago:

> "IR-2024-117. Started with a similar alert pattern: svc-reporting
> account used from a non-standard workstation, followed by file
> server enumeration. Initial hypothesis was credential reuse from a
> dev environment. Real cause: phishing email 9 days prior, attacker
> had been enumerating since. Lesson: don't dismiss off-hours service
> account anomalies even if a benign explanation seems plausible.
> Spend the 20 minutes verifying."

Tier 1 reads this memory at 02:18 AM and decides to escalate at 02:38
AM rather than close as benign. **This is the demo's killer first
moment**: the team's prior experience with this exact pattern caused
the right decision tonight.

**Why it works as a demo**: the audience instantly recognizes the
value. Every SOC has had the experience of "we saw something like
this before but I couldn't remember the details." MemoryHub is the
answer to that experience.

### Touchpoint 2: Tier 1 tribal knowledge (Phase 1)

The Tier 1 agent surfaces a related memory from team practice:

> "Tier 1 team practice: alerts on service accounts during business
> hours are usually maintenance and rarely worth escalating. Alerts
> on service accounts after 8pm are 80% worth escalating per our
> own tracking from Q1 and Q2 2024. Not a formal SIEM rule because
> it's heuristic, but it's how we've been operating."

This is the kind of soft heuristic that lives in senior analyst heads
and gets passed during shift handoff. New Tier 1 analysts take 6-12
months to internalize it. MemoryHub makes it available from day one.

### Touchpoint 3: Operational lessons memory (Phase 5)

When the Endpoint Admin agent prepares to execute containment
actions, it surfaces a memory written 8 months ago by then-IR-lead
Marcus Wong:

> "Last time we rotated the breakglass credential during an active
> incident (IR-2024-103), the rotation broke our Veeam backup
> service for 6 hours because the backup service uses the breakglass
> credential for restore operations and we hadn't documented that
> dependency. We had a separate near-miss when network monitoring
> alerted but ops didn't know it was related to our incident
> response. Operational lesson: coordinate breakglass rotation with
> backup admin BEFORE execution, and notify NOC of expected service
> impact during IR. Standard practice now."

The current Endpoint Admin reads this memory before clicking the
rotation button. The backup admin is paged. NOC is notified.
Containment proceeds without breaking backup.

**Why it works**: this is the kind of lesson that's in a postmortem
document somewhere but nobody has read in 8 months. MemoryHub
surfaces it at the exact moment of decision, when it actually
matters.

### Touchpoint 4: Per-customer context (Phase 5/6)

Comms agent surfaces a memory about the organization's CISO:

> "MidWest Financial CISO Pat Lindstrom prefers notification of any
> potential PII exposure within 2 hours, even if the team is still
> uncertain about exposure. Background: her previous role at a
> regional credit union had a delayed-notification incident in 2022
> that resulted in regulatory action. She has personally said in two
> incident reviews that 'erring on the side of early notification is
> always the right call.' Default to notifying her early during any
> potential PII incident."

The Comms team sees this memory at 06:30 and decides to notify the
CISO at 07:00 about the potential PII exposure (finance documents
were staged), even though they're not yet certain whether
exfiltration occurred.

**Why it works**: this is the kind of stakeholder-specific context
that doesn't belong in a SOAR playbook (too soft, too
context-dependent), doesn't belong in a runbook (changes per CISO
turnover), but absolutely matters for getting the response right.

### Touchpoint 5: Agent-operational memory (Phase 3)

The Forensics agent holds a memory written by itself a few months
ago:

> "When investigating `outlook.exe` child processes during a
> phishing-related incident, ignore `ai.exe`. This is the Microsoft
> 365 Copilot integration. It triggers suspicious-spawn rules
> because the parent-child relationship looks unusual, but it's
> always benign in our environment. We re-derived this three times
> across IR-2024-091, IR-2024-094, and IR-2024-105 before writing
> it down. Forensics agent should filter `ai.exe` from
> outlook.exe-spawned-process queries during phishing investigations
> by default."

When the current investigation queries Outlook child processes, the
Forensics agent automatically filters `ai.exe` and notes in its
output that it did so, citing the prior memory.

**Why it's the most novel touchpoint**: this is the agent fleet
literally writing operational lessons about itself, for itself. No
human analyst is involved in writing or reading this memory directly.
This is the demo moment that shows "an AI fleet needs its own memory
layer, separate from the human team's records."

### Touchpoint 6: Cross-incident technique pattern (Phase 3)

The Forensics agent surfaces another memory from IR-2024-117:

> "When the IR-2024-117 attacker had access to file servers, they
> staged data in `\\fileserver\admin$\TEMP\reports2024\`. The
> directory name was deliberately chosen to look like a legitimate
> reporting directory. Other staging paths to check based on
> attacker preferences from this campaign:
> `\\<server>\admin$\PerfLogs\Admin\`,
> `\\<server>\Public\Documents\templates\`,
> `\\<server>\IT\backup_temp\`.
> Forensics agent should query these paths as part of standard
> staging-search during incidents matching this campaign profile."

The Forensics agent uses this memory to direct the current
investigation. The team finds the staging directory in 12 minutes
instead of an hour-plus of manual search.

### Touchpoint 7: Post-incident lesson capture (Phase 7)

After the incident is resolved, the IC agent helps the team write
memories capturing what was learned. The team writes:

> "IR-2024-184 (the current incident) confirms the IR-2024-117
> attacker pattern is still active in our environment. Two things
> we learned this time that weren't in IR-2024-117's lessons:
> (1) the attacker waited 11 days between credential harvest and
> first lateral movement, longer than the 9 days seen in
> IR-2024-117. Our default 'go back 14 days when we see this
> pattern' assumption needs to extend to 21 days.
> (2) The attacker used the legitimate user's normal working hours
> to blend in during the enumeration phase, then switched to
> off-hours during the staging phase. Hunting hypothesis: when
> investigating a service account anomaly, also pull the human
> user's recent access patterns and look for time-of-day shifts."

This memory is read by the Threat Hunter agent the next time a
similar pattern emerges.

**Why this touchpoint matters**: it shows MemoryHub being used
explicitly *as* the post-incident learning capture mechanism. The
team isn't just running through a postmortem document — they're
writing memories that will actively shape future incident responses.

## Contradiction moments

Two specific narrative-interpretation contradictions, mirroring the
clinical scenario's pattern. Both are about disagreement on what the
evidence means, not on what the evidence is.

### Contradiction 1: Threat Intel vs. Network Analyst on attribution

**Setup** (Phase 3, around 04:30): Threat Intel agent writes a memory:

> "Initial assessment: this incident's TTPs match the campaign we've
> been tracking as 'CC2024-Q3-Opportunistic'. Phishing initial
> access, 9-14 day dwell, file server staging, behavior consistent
> with prior incidents in this campaign. Recommend handling as a
> known campaign."

**Contradiction** (Phase 3, around 05:15): Network Analyst writes a
memory and calls `report_contradiction` on the threat intel
attribution:

> "Looked at the C2 traffic. The beaconing pattern doesn't match
> CC2024-Q3-Opportunistic. The known campaign uses 90-second
> beacon intervals with jitter; this incident shows no consistent
> beaconing pattern at all — the attacker is using interactive
> sessions rather than implant beacons. Either this is a different
> attacker reusing some of the same TTPs, or the campaign has
> evolved its tooling. Either way, don't assume the rest of the
> campaign's playbook applies."

**Resolution**: the team treats the original attribution as a
possibility but doesn't *rely* on it. The investigation continues
without assuming the campaign's full playbook applies. Threat Intel
agent updates its memory to note the contradiction and the team's
revised stance.

**Why it works as a demo**: this is a classic SOC contradiction.
Attribution is hard, threat intel correlations are often partial,
and over-reliance on early attribution leads investigators down wrong
paths. The demo shows MemoryHub holding both interpretations and the
team's reasoning, so future incidents can revisit the question.

### Contradiction 2: Endpoint forensics says "contained" vs. Threat Hunter sees more

**Setup** (Phase 5, around 07:30): Endpoint Admin writes a memory:

> "Containment complete on the affected hosts. WKSTN-FIN-082
> isolated, malicious processes killed, credentials rotated.
> FILESVR-CORP-03 access revoked for the compromised credential.
> No further attacker activity observed on these hosts as of 07:30."

**Contradiction** (Phase 5, around 09:00): Threat Hunter writes a
memory and calls `report_contradiction`:

> "Disagree that containment is complete. I'm seeing the attacker's
> lateral movement TTPs (specifically the same SMB enumeration
> pattern from the original recon phase) coming from a *different*
> workstation, WKSTN-FIN-117. Same finance department, different
> user. Hypothesis: the attacker had also harvested this user's
> credentials in the original phishing wave but hadn't used them
> until tonight when the original credential was rotated. We need
> to expand containment to this second user immediately."

**Resolution**: containment is expanded. The team rotates the second
user's credentials, isolates the second workstation, and discovers
that the original phishing campaign had hit three users in the
finance department, not one. The Endpoint Admin's "containment
complete" memory is updated with the corrected scope.

**Why it works**: this contradiction is about *scope*. The Endpoint
Admin was right that the *known* affected systems were contained;
the Threat Hunter was right that there were *more* affected systems
than were known. Both observations were valid; the disagreement was
about what "containment complete" meant. MemoryHub surfaces the
disagreement and the team resolves it before the attacker can
exploit the gap.

## Sensitive-data moments

Two specific moments where an agent attempts to write a memory
containing sensitive data and the curation pipeline catches it.
These are realistic, the kind of natural slip an analyst might make
while taking notes during a fast-moving incident.

### Sensitive moment 1: Credentials in plaintext

The Identity Admin agent tries to write a memory during the
credential rotation activity:

> "Rotated svc-reporting credential. Old password was
> `Welcome2024!Q3`, new password is `Tk7$mNp2#vR9wQ4z`. Documenting
> for handoff."

The curation pipeline catches both the old and new password values.
Old passwords are sensitive (they shouldn't be reused, and writing
them down extends the risk window). New passwords are catastrophically
sensitive (they're active credentials). The pipeline quarantines and
the agent rewrites:

> "Rotated svc-reporting credential at 06:42 per IR-2024-184
> containment plan. New credential stored in privileged access
> management vault per standard procedure. Old credential is now
> invalid."

The operational fact is preserved (the credential was rotated, when,
and why). The actual credential values are not. The new credential
lives in the PAM vault, not in shared memory.

### Sensitive moment 2: Executive identification

The Tier 2 agent tries to write a memory during the early
investigation:

> "The phishing email that started this incident was sent to Pat M.
> (CFO of MidWest Financial Services). Pat opened it from her phone
> at 8:14 PM on March 15. The email impersonated the company's
> external auditor."

The curation pipeline catches the combination: an executive's name +
title + organization + specific date + behavior. This is multiply
sensitive — it identifies a specific executive as the victim of a
successful phishing attack, which is professionally embarrassing,
potentially legally sensitive, and the kind of information that
should not propagate beyond the immediate investigation team.

The pipeline quarantines and the agent rewrites:

> "The phishing email that started this incident was sent to a
> finance department user. The email was opened from a mobile
> device on the evening of March 15. The email impersonated the
> organization's external auditor. Specific user identity is
> documented in the case management system, not in shared memory."

The investigative facts are preserved (phishing email, auditor
impersonation, mobile device, evening of March 15). The
identification of the specific executive is not. The case management
system (which has appropriate access controls) holds the identity
linkage; MemoryHub holds the case learnings without the
re-identification risk.

## What's drawn from the source material vs. invented

Honest disclosure.

**Drawn from real frameworks and practices**:

- The phase structure (Detection → Triage → Investigation → Scoping →
  Containment → Eradication/Recovery → Post-Incident) is loosely
  mapped to NIST SP 800-61 Rev. 2's incident response lifecycle
- The role list reflects real SOC organizational structures across
  enterprises and MSSPs
- The MITRE ATT&CK technique names are real
- The general attacker behavior (phishing → credential theft →
  enumeration → lateral movement → data staging) is a realistic
  pattern that occurs in actual incidents
- The containment-rotation-breaks-backup operational lesson is a
  realistic class of operational gotcha

**Invented for this scenario**:

- The organization (MidWest Financial Services Group) and its
  staffing details
- Every analyst name, every prior incident ID, every specific
  filename and path
- The specific behavioral SIEM rule that fires
- The CC2024-Q3-Opportunistic campaign attribution
- The dwell time and staging volume specifics
- All quoted memories
- The specific contradictions and their resolutions
- The CISO's preference for early notification

The point is not technical fidelity to a specific real incident; the
point is realistic *shape* that a SOC professional would recognize
without finding any single detail wrong.

**Sidestepped entirely**:

- Specific SIEM query syntax (Splunk SPL, Sentinel KQL, etc.) — would
  date the demo and may differ across audience environments
- Specific EDR vendor capabilities — would inadvertently advertise or
  disadvantage specific products
- Compliance and regulatory specifics — would require domain
  expertise to get right

## Open questions

1. **How much MITRE ATT&CK vocabulary should the demo use?** The
   audience knows ATT&CK and using it correctly is a credibility
   signal. Using it incorrectly is anti-credibility. Likely answer:
   use only the technique names that are unambiguous (e.g., T1078
   Valid Accounts, T1083 File and Directory Discovery) and avoid
   sub-technique specifics.

2. **Should the demo show the SIEM/EDR alerts directly, or just
   refer to them?** Showing actual alert UI is risky (screenshots
   date the demo, vendor lock-in concerns). Referring to them
   abstractly works but loses some "this is realistic" credibility.
   Likely answer: refer abstractly with "the alert that fires here
   would look something like this" placeholder text.

3. **Demo length and pacing.** The full incident as described above
   would take 12+ hours to play out in real time. The demo
   compresses this to 15-20 minutes by jumping between phases. We
   should pre-pick which 4-5 memory touchpoints are demoed live and
   which are mentioned in passing.

4. **Should we model the SOC manager / CISO as agents?** They're
   stakeholders the IC interacts with throughout the incident. The
   "in production" framing says clinicians/analysts chat with the
   agents — does that extend to executives chatting with agents
   during incidents? Probably for the *briefing prep* phase
   (executives chat with the IC agent to recall what's happened),
   but not for in-line decision-making during the incident itself.

5. **SOC SME validation.** Same concern as the clinical scenario:
   we should have a working SOC analyst or IR practitioner review
   this scenario for plausibility before demoing it. Mistakes that
   a SOC professional would catch immediately will undermine the
   demo's credibility.

6. **Animation visualization.** Stretch item per
   `../README.md`. For the cybersec scenario, the
   animation could show alerts firing into the central core, then
   pulses going out to the relevant agents, then agents pulsing to
   each other as they share findings. The rapid back-and-forth
   pattern would land particularly well in a security context where
   "the team converges on a hypothesis" is the central operational
   moment.

7. **Multi-tenant / MSSP framing.** The scenario as written is for
   a single organization's internal SOC. An MSSP version would have
   stronger demo moments around per-customer context (touchpoint 4)
   and would target a different audience (MSSPs specifically). Worth
   considering whether to develop both versions or pick one.
