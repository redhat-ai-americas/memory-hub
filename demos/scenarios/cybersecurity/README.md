# Cybersecurity Scenarios

This folder holds cybersecurity scenarios for MemoryHub demos. The first
scenario (SOC threat hunting and incident response) is the **second
demo** MemoryHub is being built toward, after the clinical scenario.

## The value proposition in one sentence

> **MemoryHub holds the context that makes security decisions go well.**

It's the same shape as the clinical value prop, and that's intentional —
the framing is consistent across domains. In a SOC, security decisions
are made by analysts and incident responders using their judgment.
Detection systems make recommendations. EDR and SIEM platforms hold the
structured data. MemoryHub holds the surrounding context that determines
whether a security decision goes well or poorly: what the team has
learned from past incidents, which tribal practices the on-call analyst
needs to know, and what the agent fleet has discovered about its own
operational patterns.

## The detection-paradigm boundary

Every cybersecurity scenario doc in this folder must include an
explicit "MemoryHub vs. Detection and Response Tooling" boundary
section, for the same reason the clinical scenarios must address CDS:
the audience already has detection tools deployed and trusts them.
Trying to compete is a losing position.

### What detection and response tools do (don't try to do this)

The cybersecurity detection-and-response stack is large and well-funded:

- **SIEM platforms** (Splunk, Sentinel, Chronicle, Elastic) — log
  aggregation, correlation rules, alerting
- **EDR/XDR platforms** (CrowdStrike, SentinelOne, Defender for
  Endpoint, Carbon Black) — endpoint detection, telemetry, response
  actions
- **NDR platforms** (Darktrace, ExtraHop, Vectra) — network detection
- **SOAR platforms** (Splunk SOAR, XSOAR, Tines) — playbook automation
- **Threat intelligence platforms** (Recorded Future, Mandiant, Anomali)
  — IOC feeds, attribution data
- **Vulnerability management** (Tenable, Qualys, Rapid7) — exposure
  surface management

These do detection, alerting, response automation, and structured
threat data. **MemoryHub does not.**

### What MemoryHub does (this is where the value lives)

The things detection tools can't easily hold or don't try to hold:

- **Incident-to-incident pattern memory** — "We've seen this initial
  access pattern before in IR-2024-117. Phishing email with an
  Office 365 lure, lateral movement via Service Principal abuse. Check
  for similar SP creation events even before the alert fires." Threat
  intel feeds carry IOCs; MemoryHub carries the *story* of how the
  team responded last time.
- **Analyst tribal knowledge** — "Tier 1 has learned: alerts on
  `svc-backup` during business hours are usually maintenance, but
  alerts after 8pm are 80% worth escalating. Not a formal rule, just
  team experience." This kind of practice gets whispered between
  analysts on shift handoff and walks out the door when staff leave.
- **Operational lessons across incidents** — "Last time we rotated the
  breakglass credential during an incident, the rotation broke our
  backup system for 6 hours. Coordinate with backup admin BEFORE
  rotation, not after." The lesson is in the incident postmortem, but
  postmortems get filed and forgotten. MemoryHub keeps them
  operationally accessible.
- **Customer/tenant context** (for MSSPs) — "This client's leadership
  prefers notification of any potential PII exposure within 2 hours,
  even if uncertain. Their CISO's previous company had a delayed
  notification incident and she's sensitive about this." Per-customer
  context that's not appropriate to bake into a SOAR playbook.
- **Agent fleet operational state** — same as the clinical scenario, but
  for the SOC's own AI fleet. "When investigating `outlook.exe` child
  processes, ignore `ai.exe` — it's the Copilot integration, not
  malicious despite triggering suspicious-spawn rules. Forensics agent
  has learned this pattern."

The relationship is **complementary**. The EDR fires the alert.
MemoryHub holds the memory that says "we ruled this kind of alert as
benign three months ago after an 8-hour investigation — here's the
playbook we wrote based on what we learned, check it before opening a
new investigation."

## The "humans in production" framing

Every cybersecurity scenario doc must be explicit, repeatedly, that
**the agents are operated by analysts and incident responders in
production**. The demo will have Claude playing the role of all the
analysts, but in real deployment:

- A Tier 1 analyst chats with the Tier 1 agent the way she might compare
  notes with a more experienced colleague who's been at the firm longer
- An incident commander chats with the IR Commander agent during a war
  room to surface what the team learned in past incidents
- A threat hunter chats with the Threat Hunter agent to recall hunting
  hypotheses from prior shifts

The agents are the analysts' interface to the SOC's accumulated
operational memory. They're not autonomous decision-makers, they're not
replacing the SOC team, and **they emphatically do not** auto-execute
containment actions. (Auto-containment is the third rail of SOC
demos — the audience will check out the moment they think you're
proposing it.)

This framing should appear in two places in every cybersecurity
scenario doc:

1. A dedicated section near the top of the scenario doc
2. Sidebars in each role description with a one-line note about who
   chats with that agent in production

## Why cybersecurity is a strong second demo

Three reasons cybersecurity is the right follow-up to the clinical
demo:

1. **Different audience, same value prop language.** The clinical demo
   and the cybersecurity demo can use literally the same one-line
   value prop with one word changed ("clinical" → "security"). That
   consistency is platform messaging gold.
2. **Technical audience understands the shape immediately.** SOC
   analysts and IR responders intuitively grasp "we've seen this before
   and here's what worked." It's the kind of insight that takes
   explanation in clinical scenarios but lands instantly in security.
3. **No human-replacement anxiety.** Nobody in the security industry is
   worried about replacing tier-1 analysts — the shortage is so severe
   that everybody wants to make existing analysts more effective. The
   "AI supports humans" framing isn't a defensive positioning move
   here; it's exactly what the audience wants to hear.

## Audience

- SOC managers and CISOs at enterprise organizations
- Managed security service providers (MSSPs)
- CISA, defense contractors, and federal/state security operations
- SOC tooling vendors and integrators
- Threat intelligence providers
- Security training and certification organizations

## Scenario inventory

| File | Status | Incident archetype |
|---|---|---|
| [threat-hunting-incident-response.md](threat-hunting-incident-response.md) | **In active development** | Credential-theft compromise → lateral movement → data staging → SOC response across 7 phases |

Future cybersecurity scenarios will be added here as they're developed.
Likely candidates for future demos: insider threat detection, supply
chain compromise response, ransomware response, threat hunting hypothesis
campaigns.
