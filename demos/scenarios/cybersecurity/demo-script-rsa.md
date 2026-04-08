# RSA Conference Demo Script — SOC Threat Hunting Scenario

A 10-15 minute presentation outline for delivering the SOC threat
hunting and incident response scenario to an RSA Conference-style
audience (SOC managers, CISOs, threat hunters, IR responders, security
architects, security tooling vendors and integrators).

This is an **outline** with talking points, not a word-for-word script.
The presenter ad-libs the actual language; the script tells you what
to cover, in what order, and which agent fleet milestones to highlight
when.

The presenter is doing live voiceover. Behind the voiceover plays a
recorded session of the agent fleet running on a real cluster, edited
into clips that match the segment structure below. The presenter
plays the role of the entire SOC team in the recording — this is a
demo necessity, and the script repeatedly reinforces that in
production every agent is operated by a working analyst or responder.

Throughout the script, **footnote markers** like `[^cross-incident]`
mark the specific MemoryHub feature each statement, segment, or
moment demonstrates. The full feature reference key is at the bottom
of the document, with each footnote linking to the relevant design
doc and GitHub issue.

## Audience and framing

**Who they are**: RSA attendees are security decision-makers,
practitioners, and influencers. SOC managers and CISOs are the
buyers. Tier 2 analysts, threat hunters, and IR responders are the
users. Security tooling vendors and integrators are the partners.
They have a stack already — SIEM (probably Splunk, Sentinel, or
Chronicle), EDR (probably CrowdStrike, SentinelOne, or Defender),
SOAR, threat intel feeds, vulnerability management. They've spent
millions on it. They trust it.

They are also **deeply allergic** to "AI security" hype. Every booth
at RSA claims AI-powered threat detection. The audience has seen the
demos, bought the products, and been disappointed. To break through,
the demo must be unambiguously different from what they've seen
before — and it must be technically credible. Snake oil pitches lose
the room in 30 seconds.

The good news: SOC people are *desperate* for analyst burnout
relief, institutional memory across staff turnover, and faster
incident response. The "AI helps analysts retain hard-won knowledge"
framing is exactly what they want to hear, as long as you don't
overpromise.

**What they need to hear in the first 60 seconds**:

1. This is not another SIEM/EDR/SOAR pitch.[^detection-boundary]
2. This is not auto-containment.[^humans-in-loop]
3. This is something they don't already have in their stack.
4. There's a specific incident scenario being shown (not a generic
   abstraction).

**What they need to leave with**:

1. The phrase: "MemoryHub holds the context that makes security
   decisions go well."[^value-prop]
2. A clear understanding of the detection-stack boundary —
   MemoryHub sits alongside SIEM/EDR/SOAR, doesn't compete with
   them.[^detection-boundary]
3. The cross-incident pattern recognition moment as the most
   memorable demonstration of value.[^cross-incident]
4. The operational lesson moment (breakglass-rotation breaking
   backup) as the second-strongest landing.[^cross-incident]
5. The audit-trail-with-driver-id moment as the chain-of-evidence
   compliance hook.[^audit][^driver-id]
6. Confidence that this is real software running real agents on
   real infrastructure, not a vaporware mockup.

## Recording strategy

The default delivery is **a recorded session of the harness running,
edited into clips that play behind the live voiceover** at the
conference. Live cluster execution is the backup plan if conference
WiFi is reliable enough to risk it.

This decision shapes every "Harness operator notes" section below.
Each one doubles as a **shot list** for the recording session — the
list of moments that need to be captured and made visible on screen
when that segment plays back.

### How to record the session

1. Capture the harness output as a single long-form recording (not
   multiple takes spliced together). The agent fleet runs end to
   end through the full incident scenario in real time. This is
   the source material; clips get cut from it in post.
2. The recorded session does not need to match the demo's 13-minute
   target — it can be 30-45 minutes long if the agent fleet runs
   through the full scenario at realistic pace. Pacing happens at
   the editing stage.
3. Capture every "shot list" item from the per-segment Harness
   operator notes. If something on the shot list isn't visible in
   the recording, that segment's clip won't work.
4. After the recording session, cut the source material into
   segment-aligned clips. Each clip's runtime should match the
   "Time" column from the time budget table below, with a few
   seconds of padding on either end so the voiceover can lead and
   trail naturally.
5. Voiceover is delivered **live at the conference**, in sync with
   the playback. Do not pre-record the voiceover — the presenter
   needs to be able to ad-lib, respond to audience cues, and adjust
   pacing in real time.

### Visual style for the recording

- Clean structured terminal output (not a UI mockup) so the audience
  sees the real thing — security audiences are particularly
  sensitive to "demo polish that hides what's really happening"
- Role labels prominent — "Tier 1 SOC Analyst" not "agent-3"
- `actor_id` and `driver_id` rendered in distinct colors so the
  identity distinction is visible from the back of the
  room[^identity-triple][^driver-id]
- Sensitive-data quarantine notifications must be impossible to miss
  (red, bordered, animated, ideally all three)[^data-curation]
- Contradiction markers visually distinct from normal memory
  writes[^contradiction]
- Cross-incident memory references should visually link to the
  prior incident ID (e.g., "from IR-2024-117") so the audience
  understands they're seeing actual recall, not generic
  output[^cross-incident]
- Resolution: at minimum 1920x1080, ideally 2560x1440 or higher if
  conference projection supports it
- Terminal font: large enough to read from the back row of a
  conference session room (think 18pt+ at recording resolution)

### Live cluster fallback

If WiFi at the conference is observably reliable in the 30 minutes
before the talk, live execution becomes Plan A and recorded clips
become Plan B. The decision happens just before the session starts.
**The recorded clips must always be ready as the default**, not as a
last-minute scramble. Test the playback path on the conference's
actual A/V setup at least 15 minutes before showtime regardless of
which plan is in effect.

The harness used for the live execution path is the same one that
generated the recording — there are no two harnesses to maintain.
Switching from recorded to live means starting the same harness,
pointed at a real cluster with the agent fleet preloaded, instead of
playing back the saved video.

**Security-audience-specific warning**: if going live, do not
connect to a production-looking environment over conference WiFi.
The audience will assume your "demo cluster" is a real production
SOC and any visible details (network topology, IP ranges, hostnames,
attacker tooling) will be screenshotted and shared. Use a clearly
fake environment with synthetic data and obviously-made-up hostnames.

## Time budget

Total: 13 minutes (gives you 2-minute cushion against the 15-minute
hard cap; can compress to 10 minutes by trimming Phases 6-7
walkthrough if running long).

| Segment | Time | What's on screen |
|---|---|---|
| 1. Opening hook and framing | 1:30 | Title slide → incident archetype slide |
| 2. Meet the incident and team | 1:30 | Incident intro → agent fleet startup |
| 3. Detection & "we've seen this before" | 2:00 | Recorded clip: alert fires, cross-incident pattern recognition, escalation decision |
| 4. Investigation & on-call rotation | 3:00 | Recorded clip: parallel investigation, shift change, attribution contradiction, agent-operational memory |
| 5. Containment with operational lessons | 2:00 | Recorded clip: breakglass coordination, per-customer context, sensitive-data quarantine |
| 6. Audit trail and chain of evidence | 1:30 | Recorded clip: audit query showing actor/driver split |
| 7. Post-incident learning capture | 0:30 | Brief retrospective scene, memories written for next incident |
| 8. Closing pitch | 1:00 | Recap slide → call to action |

Buffer: 30 seconds for transitions and audience reactions.

## Segment 1 — Opening hook and framing (1:30)

### What's on screen

Title slide: **"MemoryHub: the context that makes security decisions go well."**[^value-prop]

Below the phrase, a small subtitle: *"A demonstration with a
realistic mid-severity SOC incident."*

### Talking points

**The hook (30 seconds)**: Open with a relatable SOC moment.
Something like:

> "Every SOC analyst in this room has had this experience. It's
> 02:14 AM. You're on shift. An alert fires. And in the back of
> your mind something is telling you — *you've seen this before*.
> Maybe it was that incident in Q2. Maybe it was the one where it
> turned out to be benign. You can't quite place it. So you spend
> 40 minutes trying to remember while the attacker is doing
> whatever they're doing in the background. Sometimes you find
> the prior incident in time. Sometimes you don't. When you don't,
> the patient — sorry, the *organization* — pays for it."

**The framing (30 seconds)**: Establish what we're showing and what
we're NOT showing.[^detection-boundary]

> "What I'm about to show you is not another SIEM. It's not
> another EDR. It's not a SOAR replacement. It's not a threat
> intel feed. You already have all of those things, and they're
> doing their jobs. Your SIEM is correlating logs. Your EDR is
> detecting endpoint behavior. Your SOAR is automating playbooks.
> Your threat intel feed is delivering IOCs."
>
> "What you're about to see lives *alongside* all of those. It
> holds what they don't: the cross-incident patterns your team has
> seen, the operational lessons you learned from past incidents,
> the analyst tribal knowledge that walks out the door when staff
> turn over, and the per-customer or per-tenant context that
> doesn't fit cleanly in a SOAR playbook."

**The agent disclaimer (30 seconds)**: Get this in early. Don't let
the audience misread the demo as auto-containment.[^humans-in-loop]

> "I'll be playing the role of the entire SOC team during this
> demo. Every agent you see is operated by a human analyst in
> production. The Tier 1 agent? In production, that's your Tier 1
> analyst on shift, chatting with her team's accumulated memory
> the way she'd compare notes with a more experienced colleague.
> The Forensics agent is a working forensics specialist. The
> Incident Commander agent is your IC during a war room. **These
> agents help analysts; they don't replace them. They emphatically
> do not auto-execute containment actions.** When you see me
> typing, picture the analyst in your SOC who would be doing that
> job."

### Milestones demonstrated

None yet — this is setup. But you've planted three things:

- The phrase[^value-prop]
- The detection-stack boundary[^detection-boundary]
- The agents-support-analysts framing (and the explicit
  no-auto-containment disclaimer)[^humans-in-loop]

### Harness operator notes / shot list

- No harness footage in this segment. Stay on slides.
- Have the recorded clip queued up to begin on the cue at the
  start of Segment 2.

## Segment 2 — Meet the incident and team (1:30)

### What's on screen

Slide: incident archetype. MidWest Financial Services Group, the
SOC team composition, the alert that started everything (timestamp,
account name, behavioral indicator).

Then transition to the recorded clip showing the agent fleet
registering with MemoryHub.[^identity-triple][^cli-provisioning]

### Talking points

**Incident introduction (45 seconds)**: Make the incident concrete,
not abstract.

> "MidWest Financial Services Group. Regional bank, three thousand
> employees, twelve-person SOC running 24/7 across three shifts.
> They've got a real stack — Splunk, CrowdStrike, ProofPoint,
> Active Directory hybrid identity. Standard mid-market posture.
> Not a Fortune 50 with a fifty-person SOC. Not a small business
> with no SOC at all. The kind of organization most of us actually
> work for or sell to."
>
> "02:14 AM on a Tuesday morning. A behavioral SIEM alert fires:
> unusual logon pattern for the `svc-reporting` service account.
> That account runs an automated nightly reporting job at 23:00.
> Right now, four hours after the job should have ended, the
> account is being used from a workstation that does not
> normally use this credential, and it's enumerating shares on a
> file server."
>
> "Over the next several hours of investigation, the team is
> going to discover this is a real incident — phishing-derived
> credential, eleven-day attacker dwell time, data being staged
> for exfiltration. Today, on screen, you're going to watch the
> SOC team respond to it. Ten roles, working in parallel,
> sharing what they know, learning from what the team has
> learned in past incidents."

**Why this scenario (15 seconds)**:

> "This scenario is built against NIST SP 800-61, the Computer
> Security Incident Handling Guide. The phase structure, the
> roles, the response activities — all consistent with the
> framework your IR team is already trained on. We're not making
> up incident response. We're showing how an agent fleet with
> shared memory can help your SOC do incident response better."

**Agent fleet startup (30 seconds)**: Cue the recorded clip. Show
the ten SOC agents registering with MemoryHub.[^identity-triple][^project-scope]

> "On screen now you'll see the SOC fleet starting up. Each agent
> is registering with MemoryHub and being authenticated. Watch
> the role names — Tier 1, Tier 2, Threat Intel, Threat Hunter,
> Forensics, Network Analyst, Incident Commander, Endpoint Admin,
> Identity Admin, Communications and Legal Liaison. Ten roles.
> In production, each one is the interface a working analyst or
> responder uses to chat with the SOC's accumulated experience."

### Milestones demonstrated

- **Identity model**[^identity-triple]: ten agents come online,
  each with its own identity. The recorded clip shows each agent's
  `actor_id` as it registers.
- **Project membership**[^project-scope]: all ten agents are
  members of a shared project (`midwest-financial-soc`). The
  audit trail will hang off this project membership later.
- **Fleet provisioning**[^cli-provisioning]: implicit — the fleet
  was generated from a manifest by the agent generation CLI.

### Harness operator notes / shot list

- **Capture**: each agent's `register_session` call landing in the
  harness output, with the role name and `actor_id` clearly
  visible. Hold for 1-2 seconds per agent so the audience can
  read the role names.
- **Capture**: a confirmation line showing all ten agents are
  members of the `midwest-financial-soc` project.
- The driver_id at this point is set to the demo presenter (e.g.,
  `wjackson-rsa-demo-1`). Make sure it's visible in the
  registration output — it will be referenced later in the audit
  trail segment.[^driver-id]

## Segment 3 — Detection & "we've seen this before" (2:00)

### What's on screen

Recorded clip showing the alert firing, Tier 1 triage, and the
cross-incident pattern recognition moment that drives the escalation
decision.[^cross-incident]

### Talking points

**The alert fires (30 seconds)**:

> "Here we go. 02:14 AM. The behavioral SIEM rule in CrowdStrike
> fires on the `svc-reporting` account anomaly. The Tier 1
> analyst on the night shift sees the alert in the SOC queue.
> What you're watching on screen now is the Tier 1 agent
> beginning its triage."
>
> "Triage at 02:14 in the morning is hard. There's no senior
> analyst at the next desk to ask. The alert could be a real
> incident or it could be the third false positive of the night
> on a service account doing legitimate maintenance. The
> decision the analyst has to make in the next 20 minutes is:
> escalate or close."

**The killer moment (1:00)**: This is the demo's first major
landing. Slow down. Make it land.[^cross-incident]

> "Watch this. The Tier 1 agent is searching shared memory for
> patterns matching this alert. It's looking for: unusual
> service account logon, off-hours, followed by SMB
> enumeration. And look at what it finds."
>
> "A memory written four months ago by a Tier 2 analyst named
> Maya Chen. Here's what it says: 'IR-2024-117. Started with a
> similar alert pattern: svc-reporting account used from a
> non-standard workstation, followed by file server
> enumeration. Initial hypothesis was credential reuse from a
> dev environment. Real cause: phishing email nine days prior,
> attacker had been enumerating since. Lesson: don't dismiss
> off-hours service account anomalies even if a benign
> explanation seems plausible. Spend the twenty minutes
> verifying.'"
>
> "Tier 1 reads this memory at 02:18 AM. The decision shifts.
> Instead of closing this as another night-shift false
> positive, Tier 1 escalates to Tier 2 at 02:38."
>
> "Now I want you to think about what just happened. Your team
> has institutional memory of an incident from four months ago.
> In current practice, that memory is in a postmortem document
> nobody has read since the day it was filed, in the head of
> Maya Chen who is currently on PTO, and in the Slack channel
> from August that nobody can find. Tonight, at 02:18 AM, with
> nobody senior in the room, that memory caused the right
> decision. *That* is what we mean by the context that makes
> security decisions go well."[^value-prop]

**The tribal knowledge moment (30 seconds)**:[^tribal-knowledge]

> "While the Tier 1 agent is making the escalation decision,
> watch what else it surfaces — a piece of team practice that
> isn't in any formal SIEM rule. The memory says: 'Tier 1 team
> practice — alerts on service accounts during business hours
> are usually maintenance, but alerts on service accounts after
> 8pm are 80% worth escalating per our own tracking from Q1 and
> Q2 2024. Heuristic, not formal rule.'"
>
> "This is the kind of soft heuristic that lives in senior
> Tier 2 analyst heads. New Tier 1 analysts take six to twelve
> months to internalize it. Here, it's available from day one.
> Your new hires inherit the team's accumulated experience the
> moment they start chatting with the agent."

### Milestones demonstrated

- **Cross-incident pattern recognition**[^cross-incident] (the
  killer moment)
- **Project-scope reads**[^project-scope] (Tier 1 reading the
  team's shared memory)
- **Analyst tribal knowledge**[^tribal-knowledge] (the off-hours
  service account heuristic)
- **Value prop landing**[^value-prop]: the headline phrase gets
  its first strong demonstration here

### Harness operator notes / shot list

- **The cross-incident memory recall is the most important shot
  in this segment.** The Tier 1 agent's `search_memory` call
  must be visible, the IR-2024-117 memory text must be on
  screen, and the camera needs to hold on it for at least 4
  seconds — long enough that even the slowest reader can take
  it in.
- **Capture**: the linkage between the Tier 1 agent's recall and
  its escalation decision. The audience needs to see "the
  agent surfaced this memory at 02:18; the analyst escalated at
  02:38" with timestamps visible.
- **Capture**: the tribal knowledge memory being read in the
  same flow.
- The visual styling should make the prior incident reference
  ("IR-2024-117") clickable-looking, even if it's just text —
  the audience should understand "this is a real recall of a
  real prior incident."[^cross-incident]

## Segment 4 — Investigation & on-call rotation (3:00)

### What's on screen

The longest segment. Multiple moments compressed into a fast-paced
walkthrough of the investigation phase. Key beats:

- Tier 2 escalation, IR team paged, parallel investigation begins
- The on-call rotation moment (different person taking over the
  same role)[^role-vs-person][^driver-id]
- A threat intelligence vs network analyst contradiction over
  attribution[^contradiction]
- The Forensics agent applying agent-operational memory (the
  ai.exe filter)[^operational-memory]
- A second sensitive-data quarantine moment (executive
  identification)[^data-curation]

### Talking points

**Investigation begins (30 seconds)**:

> "Skipping ahead to 02:55 AM. Tier 2 has confirmed unauthorized
> access. The on-call IR team is paged. Investigation begins in
> parallel — Forensics is reconstructing the attacker timeline,
> Network is analyzing C2 traffic, Threat Intel is correlating
> with known campaigns, Threat Hunter is running proactive
> searches for related compromise. The Incident Commander
> agent activates and starts holding the synthesized picture."

**The on-call rotation moment (1:00)**: This is where you make the
role-vs-person distinction land.[^role-vs-person][^driver-id][^audit]

> "Here's something that's going to happen at 06:00 AM, when
> the night shift hands off to day shift. Watch the Tier 2
> agent right now."
>
> "The Tier 2 *role* persists across the shift change. Same
> actor identity, same accumulated memory of the night's
> investigation. What changes is the *driver* — the human on
> whose behalf the agent is now acting. At 05:59, Tier 2 is
> being driven by Jason Park, the night-shift senior analyst.
> At 06:01, Tier 2 is being driven by Maya Chen, the day-shift
> senior analyst. The agent's `driver_id` updates. Same role,
> different human."
>
> "This is intentional and it matters. In production, your SOC
> staff turns over every 8 to 12 hours. Your IR team rotates
> on-call weekly. The role persists across the rotation; the
> people change. MemoryHub's identity model captures that
> distinction natively. The role has continuity of memory; the
> audit trail captures which specific human was driving the
> role at any given moment. Both questions matter — 'what does
> the Tier 2 role know about this incident?' and 'who was
> Tier 2 on duty when the containment decision was made at
> 07:42?' — and MemoryHub answers both."
>
> "Why does this matter beyond compliance? Because Maya Chen,
> at 06:01, has the complete context Jason Park built up
> overnight — every observation, every hypothesis, every
> 'we ruled out this theory at 04:30 because of these
> indicators' note — without any handoff loss. The shift
> changed. The institutional memory of the incident did not."

**The contradiction moment (45 seconds)**:[^contradiction]

> "Now in parallel, watch this. The Threat Intel agent has
> written an attribution memory: 'Initial assessment — this
> incident's TTPs match the campaign we've been tracking as
> CC2024-Q3-Opportunistic. Phishing initial access, nine to
> fourteen day dwell, file server staging. Recommend handling
> as a known campaign.'"
>
> "About 45 minutes later, the Network Analyst writes a
> contradicting memory: 'Looked at the C2 traffic. The
> beaconing pattern doesn't match CC2024-Q3-Opportunistic.
> The known campaign uses 90-second beacon intervals with
> jitter; this incident shows no consistent beaconing pattern
> at all — the attacker is using interactive sessions rather
> than implant beacons. Either this is a different attacker
> reusing some of the same TTPs, or the campaign has evolved
> its tooling. Either way, don't assume the rest of the
> campaign's playbook applies.'"
>
> "Network Analyst calls `report_contradiction`. MemoryHub
> surfaces the conflict. The Incident Commander reads both
> memories. The investigation continues without assuming the
> known campaign's full playbook applies. **This is critical.**
> Attribution is hard. Over-reliance on early attribution
> takes investigators down wrong paths. The original
> attribution isn't *deleted* — it's preserved as a possibility
> with the network observation as a contradicting view. Future
> incidents can revisit the question."

**Agent-operational memory and sensitive-data quarantine (45 seconds)**:[^operational-memory][^data-curation]

> "Two quick things to point out before we move on. First,
> watch the Forensics agent. It just ran a query for
> `outlook.exe` child processes — standard phishing
> investigation step. And it automatically filtered out
> `ai.exe` from the results. Why? Because it's reading a
> memory it wrote *to itself* a few months ago: 'When
> investigating outlook.exe child processes, ignore ai.exe.
> It's the Microsoft Copilot integration. Triggers
> suspicious-spawn rules but is always benign in our
> environment. We re-derived this three times across
> IR-2024-091, IR-2024-094, and IR-2024-105 before writing it
> down.' That's the agent fleet learning about its own
> operational patterns and applying that learning
> automatically."
>
> "Second — and this is a governance moment — the Tier 2 agent
> just attempted to write a memory containing 'the phishing
> email was sent to Pat M., CFO of MidWest Financial.' The
> curation pipeline caught it. Executive name, title, and
> organization in combination is a quasi-identifier. The memory
> is quarantined. The agent rewrites it as 'the phishing
> email was sent to a finance department user' — preserving
> the investigative fact without identifying the executive.
> The original quarantined attempt is in the audit trail. Your
> compliance team can reconstruct exactly what was attempted."

### Milestones demonstrated

- **Driver_id distinction across on-call rotation**[^driver-id]:
  same role, different humans across shift handoff. The role
  persists; the audit trail captures who was driving when.
- **Role-vs-person identity model**[^role-vs-person]: actor (the
  Tier 2 role) is stable across shift changes; driver (the human
  on shift) changes per session.
- **Project-scope reads**[^project-scope]: agents reading from
  the shared incident memory.
- **Contradiction detection**[^contradiction]: report_contradiction
  in action over an attribution disagreement.
- **Agent-operational memory**[^operational-memory]: the
  Forensics agent applying its own self-written operational
  lessons (the ai.exe filter).
- **Sensitive-data quarantine**[^data-curation] on executive
  identification.
- **Audit trail of the quarantined attempt**[^audit].

### Harness operator notes / shot list

- **The shift change moment must be visually obvious in the
  recording.** Show the `driver_id` value changing in the
  harness output while the `actor_id` stays constant. If the
  harness doesn't natively highlight this, add a callout in
  post-production editing.
- **Capture both memories of the attribution
  contradiction**: Threat Intel's original attribution and
  Network Analyst's contradicting view. When
  `report_contradiction` is called, the relationship between
  the two memories should be visually rendered. Side-by-side
  display preferred.
- **Capture**: the Forensics agent's query results showing
  `ai.exe` being filtered out, with the agent-operational
  memory that explains the filter visible nearby.
- **Capture both halves of the executive-identification PHI
  moment**: the rejected attempt with "Pat M., CFO" text
  visibly marked as quarantined, and the rewritten successful
  version with the executive identification removed.
- The investigation phase has a lot happening in parallel.
  The recording should make it visually clear which agent is
  doing what — color-coding by role, side-by-side panes, or
  similar.

## Segment 5 — Containment with operational lessons (2:00)

### What's on screen

The second killer moment lives here: the breakglass-rotation
operational lesson that prevents the team from breaking their own
backup system. Plus per-customer context for executive notification
and the credential-quarantine moment.

### Talking points

**Containment begins (15 seconds)**:

> "By 06:00 AM the team has scoped the incident. They know
> the affected accounts, the affected hosts, the staging
> path. Containment begins. Endpoint Admin will isolate the
> affected workstations. Identity Admin will rotate the
> compromised credentials, including the breakglass account
> the attacker may have touched."

**The killer second moment (1:00)**:[^cross-incident]

> "Watch this. The Endpoint Admin agent is preparing to
> execute the breakglass credential rotation. Standard
> containment step. And before it pulls the trigger, look
> at what it surfaces."
>
> "A memory from eight months ago, written by the IR lead
> after IR-2024-103. Here's what it says: 'Last time we
> rotated the breakglass credential during an active
> incident, the rotation broke our Veeam backup service for
> six hours. Backup uses the breakglass credential for
> restore operations and we hadn't documented that
> dependency. We had a near-miss incident response situation
> when network monitoring alerted but ops didn't know it was
> related to our IR. Operational lesson: coordinate
> breakglass rotation with backup admin BEFORE execution,
> and notify NOC of expected service impact during IR.
> Standard practice now.'"
>
> "The Endpoint Admin agent reads this *before* clicking the
> rotation button. The backup admin is paged. NOC is notified.
> Containment proceeds without breaking backup."
>
> "Now think about what just happened. The team had a hard
> lesson eight months ago. They wrote it down. Today, in the
> middle of a different incident, that lesson surfaces at
> the exact moment of decision — when it actually matters,
> not in a postmortem document nobody has read since it was
> filed. Every SOC in this room has had a 'we broke our own
> systems during incident response' experience. *This* is
> what stops it from happening twice."

**Per-customer context (30 seconds)**:[^narrative-context][^cross-incident]

> "While containment is happening, the Communications agent is
> preparing executive notifications. Watch what it surfaces."
>
> "A memory about MidWest Financial's CISO: 'Pat Lindstrom
> prefers notification of any potential PII exposure within
> two hours, even if uncertain. Background: her previous role
> at a regional credit union had a delayed-notification
> incident in 2022 that resulted in regulatory action. She
> has personally said in two prior incident reviews that
> erring on the side of early notification is always the
> right call. Default to notifying her early during any
> potential PII incident.'"
>
> "The Comms team sees this at 06:30. They notify the CISO at
> 07:00 about the potential PII staging exposure, even though
> the team isn't certain whether exfiltration occurred. This
> kind of stakeholder-specific context doesn't belong in a
> SOAR playbook — it's too soft, too specific to a person who
> may move to a different role next quarter. But it absolutely
> matters for getting the response right."

**The credential quarantine moment (15 seconds)**:[^data-curation]

> "And one quick governance moment — the Identity Admin
> agent just attempted to write a memory containing the
> actual rotated password values. Curation pipeline caught
> it instantly. Old credentials and new credentials never
> persist into shared memory. The operational fact is
> preserved — credential was rotated at 06:42 — without the
> actual credential values. The new credential lives in the
> PAM vault, where it should be."

### Milestones demonstrated

- **Cross-incident operational lesson**[^cross-incident] (the
  breakglass-backup lesson — the second killer moment)
- **Per-customer narrative context**[^narrative-context] (the
  CISO notification preference)
- **Sensitive-data curation**[^data-curation] catching credentials
  in plaintext
- **Audit trail of curation event**[^audit]
- **Agents-support-humans framing**[^humans-in-loop]: the
  containment actions are confirmed by humans, not auto-executed

### Harness operator notes / shot list

- **The breakglass-rotation moment is the second most
  important shot in the entire recording.** The Endpoint Admin
  agent's `read_memory` call surfacing the IR-2024-103 lesson
  must be visible, the memory text must be on screen, and the
  camera needs to hold on it for at least 4 seconds. After
  that, capture the visible coordination action (paging the
  backup admin) so the audience sees the lesson driving real
  behavior.
- **Capture**: the CISO preference memory being read by the
  Comms agent, with the full memory text visible.
- **Capture both halves of the credential quarantine**: the
  rejected attempt with the actual passwords visible in the
  rejected text (you can use obviously fake passwords like
  `Welcome2024!Q3` and `Tk7$mNp2#vR9wQ4z`), visibly marked as
  quarantined, and the rewritten successful version.
- The visual styling for the credential quarantine should make
  it obvious that the curation pipeline is doing real-time
  detection — this is a security audience, they will notice if
  it looks fake.

## Segment 6 — Audit trail and chain of evidence (1:30)

### What's on screen

The recorded clip shifts to a query mode. Two queries are run:

1. "Show me everything Tier 2 did during the IR-2024-184
   investigation, with attribution to the analyst on duty."
2. "Show me everything done on behalf of Maya Chen across all
   roles during this incident."

The two queries return different result sets, both correctly
attributed.[^audit][^driver-id][^role-vs-person]

### Talking points

**The chain-of-evidence hook (45 seconds)**: SOC audiences love
audit trails when framed as evidence chains. Lean
in.[^audit][^identity-triple][^driver-id]

> "Let me switch from the response narrative for a moment and
> talk to the IR managers and CISOs in the room. Everything
> we just walked through — every memory written, every memory
> read, every contradiction reported, every quarantine event
> — is recorded in MemoryHub's audit log. Every operation has
> two identities attached: the *actor* (which agent did it)
> and the *driver* (the human on whose behalf it was done)."
>
> "This is your **chain of evidence**. When this incident gets
> a postmortem next week — or worse, when it gets a regulatory
> review next quarter — you need to be able to reconstruct who
> made which decision and why. Not 'the SOC did this,' but
> 'Tier 2 made this call at 07:42, on the basis of these
> memories, while being driven by Maya Chen.' MemoryHub gives
> you that reconstruction by default, not as an after-the-fact
> manual exercise."

**Query 1 (20 seconds)**:[^role-vs-person][^audit]

> "Watch this. I'm going to ask: 'Show me everything the
> Tier 2 agent did during the IR-2024-184 investigation.' On
> screen now you're seeing every action that role took —
> across both Jason Park's night shift and Maya Chen's day
> shift, because the role spans the boundary. Every read,
> every write, every contradiction reported, every memory
> consulted."

**Query 2 (20 seconds)**:[^driver-id][^audit]

> "Now I'm going to ask a different question: 'Show me
> everything done on behalf of Maya Chen across the entire
> SOC fleet during this incident.' Different result set. This
> shows me what Maya was driving — not just the Tier 2 role,
> but any other role she touched while she was on shift.
> Maybe she covered for the Threat Hunter when Jason was
> swamped. Maybe she ran an Identity Admin query on her own
> initiative. All of it attributed to her."

**The point landing (5 seconds)**:

> "Both questions are answerable in seconds. In your current
> postmortem process, that's a multi-day project of correlating
> Splunk queries, ticket histories, Slack timestamps, and
> half-remembered shift handoff notes."

### Milestones demonstrated

- **Audit log with actor/driver split**[^audit][^identity-triple]
- **Driver_id queryability**[^driver-id] — both directions (by
  role, by human-on-whose-behalf)
- **Role-vs-person identity model in
  action**[^role-vs-person]
- **Chain of evidence use case** — the cybersec-specific framing
  of the compliance hook

### Harness operator notes / shot list

- **Capture both queries running** with their distinct result
  sets visible. This is one of the few segments where the
  on-screen content is dense — the audience needs to see actual
  rows of audit data, not just a summary.
- Result rows must clearly show the `actor_id` and `driver_id`
  columns so the distinction between the two queries is
  visible.[^identity-triple][^driver-id]
- For the recording: ensure the queries are pre-baked and
  produce well-formatted output, not raw JSON dumps. A
  three-column or four-column table (timestamp, action, actor,
  driver) is the right shape.
- **If running live as Plan A**: the two queries must be in a
  prepared script that the presenter triggers with a single
  keystroke each, so there's no typing latency on stage.

## Segment 7 — Post-incident learning capture (0:30)

### What's on screen

A brief moment from the post-incident review phase. The team
explicitly writes new memories that will be read by the agent
fleet during the next incident.[^cross-incident][^narrative-context]

### Talking points

**Closing the loop (30 seconds)**:[^cross-incident][^narrative-context]

> "Two days later, the team holds the post-incident review.
> And here's what's different from your current process —
> the lessons learned aren't just going into a document
> nobody will read. They're being written to MemoryHub
> directly, by the Incident Commander agent, as memories
> that the SOC fleet will read during the next incident."
>
> "Two specific lessons get captured. First: 'The attacker
> in this incident waited eleven days between credential
> harvest and first lateral movement, longer than the nine
> days seen in IR-2024-117. Our default go-back-fourteen-days
> assumption needs to extend to 21 days for this attacker
> profile.' Second: 'When investigating service account
> anomalies, also pull the human user's recent access
> patterns and look for time-of-day shifts. This attacker
> blended into business hours during enumeration, then
> switched to off-hours during staging.'"
>
> "Next time the SOC sees a service account anomaly, the
> Threat Hunter agent will read these memories before
> recommending the hunting hypothesis. The lessons from
> tonight will shape tomorrow's investigation. *That* is
> what 'institutional memory' looks like when an agent fleet
> is the surface for it."

### Milestones demonstrated

- **Explicit cross-incident learning capture**[^cross-incident]
  via post-incident memory writes
- **Narrative context category**[^narrative-context]: the
  lessons are written as narrative, not as structured
  detection rules

### Harness operator notes / shot list

- **Capture**: the IC agent writing the two lesson memories
  with timestamps. Hold for 2 seconds each so the audience
  can read the lesson text.
- This segment is the closing beat of the substantive demo.
  Keep it short but make sure both memories are readable on
  screen.

## Segment 8 — Closing pitch (1:00)

### What's on screen

Recap slide with the phrase, the detection-stack boundary, and
five bullets covering what the audience just saw. End slide with
contact info / call to action.

### Talking points

**The phrase, one more time (15 seconds)**:[^value-prop][^detection-boundary]

> "MemoryHub holds the context that makes security decisions
> go well. That phrase is the entire pitch. Your SIEM
> correlates the logs. Your EDR detects on the endpoints.
> Your SOAR runs the playbooks. Your threat intel feed
> delivers the IOCs. MemoryHub holds everything around them
> — the cross-incident patterns, the team's tribal knowledge,
> the operational lessons from prior incidents, and the
> agent fleet's own learning."

**What you saw (30 seconds)**: Recap the moments that mattered
most.

> "What you saw in the last 12 minutes:
>
> One. Tier 1 escalated an alert at 02:38 AM because the agent
> fleet remembered a similar pattern from a real incident four
> months ago.[^cross-incident]
>
> Two. The Tier 2 role's accumulated investigation memory
> survived a shift change at 06:00 AM with the audit trail
> capturing both shifts independently.[^role-vs-person][^driver-id]
>
> Three. An attribution contradiction was surfaced and the
> investigation continued without over-relying on an early
> hypothesis.[^contradiction]
>
> Four. The breakglass credential rotation didn't break the
> backup system because an operational lesson from eight
> months ago surfaced at the moment of
> decision.[^cross-incident]
>
> Five. An audit trail that answers both 'what did this role
> do?' and 'what was done on behalf of this analyst?' in
> seconds — your chain of evidence for postmortems and
> regulatory review.[^audit]"

**The call to action (15 seconds)**:

> "MemoryHub runs on Red Hat OpenShift AI. It complements
> your existing detection stack — it doesn't compete with
> it.[^detection-boundary] We're looking for SOC teams and
> MSSPs who want to pilot it with their own incidents and
> their own analyst experience. Come find us at booth [X],
> or reach out at [contact]. Thank you."

### Milestones demonstrated

None new — this is recap.

### Harness operator notes / shot list

- No recorded clip in this segment. Stay on the recap slide
  for the full 30 seconds while the presenter delivers the
  "what you saw" beats. Don't transition too fast.

## Demo flow at a glance

For rehearsal purposes, the milestone tie-ins are easier to scan as
a single table:

| Time | Segment | Primary milestone | Secondary milestone | Footnotes |
|---|---|---|---|---|
| 0:00-1:30 | Opening hook & framing | (None — setup) | Phrase, detection boundary, no-auto-containment | `[^value-prop]` `[^detection-boundary]` `[^humans-in-loop]` |
| 1:30-3:00 | Incident & team intro | Identity model (10 agents register) | Project membership, fleet provisioning | `[^identity-triple]` `[^project-scope]` `[^cli-provisioning]` |
| 3:00-5:00 | Detection & "we've seen this before" | Cross-incident pattern recognition (KILLER MOMENT 1) | Tribal knowledge | `[^cross-incident]` `[^tribal-knowledge]` `[^value-prop]` |
| 5:00-8:00 | Investigation & on-call rotation | Driver_id distinction + role-vs-person | Contradiction detection, agent-operational memory, sensitive-data quarantine | `[^role-vs-person]` `[^driver-id]` `[^contradiction]` `[^operational-memory]` `[^data-curation]` |
| 8:00-10:00 | Containment with operational lessons | Cross-incident operational lesson (KILLER MOMENT 2) | Per-customer context, credential curation | `[^cross-incident]` `[^narrative-context]` `[^data-curation]` |
| 10:00-11:30 | Audit trail | Driver_id audit query | Role-vs-person + chain of evidence | `[^audit]` `[^driver-id]` `[^role-vs-person]` `[^identity-triple]` |
| 11:30-12:00 | Post-incident learning capture | Explicit cross-incident learning | Narrative context | `[^cross-incident]` `[^narrative-context]` |
| 12:00-13:00 | Closing pitch | Recap of all milestones | Call to action | (all of the above) |

## Trim plan if running long

If at the 8-minute mark you're noticeably behind, here are the
specific cuts in priority order:

1. **First cut**: trim Segment 7 entirely. Skip the post-incident
   learning capture moment. Save 30 seconds. **Lost milestones**:
   the explicit "writing memories for the next incident" demo.
   The general `[^cross-incident]` concept stays demonstrated in
   Segments 3 and 5.
2. **Second cut**: shorten the agent-operational memory mention
   in Segment 4 to a single sentence ("the Forensics agent also
   filters known false positives based on its own learned
   patterns — we'll talk about that in Q&A"). Save 25 seconds.
   **Lost milestones**: `[^operational-memory]` is reduced to a
   mention, not a demonstration.
3. **Third cut**: drop the second sensitive-data quarantine
   (executive identification) in Segment 4. Keep the credential
   quarantine in Segment 5. Save 20 seconds. **Lost milestones**:
   one of two `[^data-curation]` demonstrations.
4. **Fourth cut**: drop one of the two audit queries in Segment 6
   (keep the role-based one, drop the human-based one, mention
   the second briefly in narration). Save 30 seconds. **Lost
   milestones**: half of `[^driver-id]`'s demonstration. Keep
   query 1 (which still demonstrates `[^role-vs-person]`) and
   describe query 2 verbally without running it.

Total trimmable: ~1:45. This brings worst-case 13-minute target
down to ~11:15, well inside the 15-minute hard cap.

## Trim plan if running short

If you finish at 11 minutes and want to fill to 13, the easy
extensions are:

1. Spend more time on Segment 3's "we've seen this before" moment.
   Let the audience really sit with the IR-2024-117 memory and
   what it would mean for their own SOC.
2. Spend more time on Segment 5's breakglass moment. The
   "we broke our own backup during IR" experience is universal in
   this audience and the recognition will land.
3. Add an aside in Segment 6 about how the chain of evidence
   integrates with their existing incident review processes.
4. Pause for one audience question in the Q&A position before
   closing.

Don't try to add new material on the fly — rehearsed material
delivers better than improvised expansion.

## What you absolutely cannot say

Words and phrases that will lose the room:[^humans-in-loop][^detection-boundary]

- "Auto-containment" or "automated response"
- "Replaces" anything human (Tier 1, Tier 2, threat hunter, IR
  responder)
- "Reduces alert fatigue automatically" (sounds like SOAR
  positioning, which competes with their existing investment)
- "Reduces headcount" or "fewer analysts needed" (the SOC
  industry has a hiring crisis, not an oversupply)
- "AI threat hunting" / "AI security" (these phrases are
  burned at RSA)
- "Better than [SIEM/EDR/SOAR vendor]" or any direct comparison
  that implies competition
- "Decision-making AI" (you can say "AI agents that hold the
  team's accumulated experience" — that's not the same thing)
- Confident attribution ("it's APT29!") — attribution is hard,
  and the audience will recognize false confidence as a tell
- "Self-healing security" (vendor cliché)

If a question in Q&A pushes toward any of these, deflect:

> "Great question. The agents don't make response decisions —
> the analysts do. What the agents do is make sure the analyst
> is making that decision with the full context the team has
> built up. Same decision authority, better information."

## Open questions for rehearsal

1. **Visual style for the harness output**: same recommendation
   as the clinical script — clean structured terminal output,
   distinct colors for `actor_id` vs `driver_id`, obvious
   quarantine notifications. For cybersec specifically, the
   visual style should *not* look like an existing SIEM dashboard
   — the audience will instantly compare it to whatever they
   already use, and we'll lose. Stay terminal-style.

2. **Synthetic environment details**: the demo references
   MidWest Financial Services, the `svc-reporting` account,
   workstation `WKSTN-FIN-082`, file server `FILESVR-CORP-03`,
   and a CISO named Pat Lindstrom. All synthetic. The recording
   needs to use obviously-fake values throughout so no audience
   member can mistake them for real production references.

3. **Booth presence**: the call to action assumes we have a
   physical booth at RSA. If we don't, the close needs to
   change.

4. **Q&A preparation**: the most likely Q&A questions for a
   security audience are:
   - "How does this integrate with Splunk / Sentinel / Chronicle?"
   - "What's the security and access control story for the
     memory layer itself?" (the audience will worry about
     MemoryHub being a new attack surface)
   - "How is this different from a SOAR platform?"
   - "What about MSSPs serving multiple customers?"
   - "How do you prevent the AI from hallucinating fake
     historical incidents?" (this is a real concern — the
     agent fleet must only surface memories that were actually
     written, never invented)
   - "What does this cost?"
   - "How long does deployment take?"
   - "Who else is using this?"
   These should have prepared one-line answers.

5. **The "MemoryHub as attack surface" concern**: this is going
   to come up. The audience will instantly recognize that an
   agent memory layer holding tribal knowledge, prior incidents,
   and per-customer context is itself a high-value target. The
   prepared answer should cover: project-scope membership
   enforcement, audit trail integrity, RBAC on read/write,
   curation pipeline preventing credential persistence, and the
   eventual LlamaStack telemetry integration for the audit
   layer. Pre-write a paragraph for this.

6. **The "hallucinated incident" concern**: closely related.
   Security audiences are sensitive to LLMs making things up.
   The answer is: MemoryHub agents only surface memories that
   were actually written to the store. The retrieval layer is
   not generative — it's search and recall. Any "hallucinated"
   memory would have to have been written by an authenticated
   actor and be in the audit trail. Pre-write a one-liner for
   this.

7. **Recording session logistics**: when does the recording
   session happen? Who runs the harness? Where is it captured?
   The recording session is its own production task and needs
   its own scheduling and rehearsal time, separate from the
   talk itself. Suggest blocking 2-3 hours for the recording
   session including reshoots, plus another 2-3 hours for cut
   and edit. Same as the clinical script.

8. **Live cluster Plan A readiness**: if going live, the cluster
   must be reachable, the agent fleet preloaded, the queries
   pre-baked, and a 1-keystroke trigger for each segment ready.
   This requires the same harness as the recording, just running
   in real time. Validate end-to-end at least the day before.

## Feature reference key

Each footnote below maps a moment in the demo to the MemoryHub
feature it demonstrates, the design doc that defines it, and the
GitHub issue (if any) tracking the implementation.

[^value-prop]: **The headline phrase**: "MemoryHub holds the
    context that makes security decisions go well." This is the
    one-line value prop that anchors the entire cybersecurity
    scenario. It's not a feature — it's the framing that makes
    the features legible to a security audience. The phrase is
    the same shape as the clinical version with one word changed
    ("clinical" → "security"), demonstrating platform messaging
    consistency across domains.
    *Defined in*: `README.md` ("The
    value proposition in one sentence" section).
    *Visible in the demo*: title slide (Segment 1), explicit
    callout in Segment 3 after the killer moment, recap slide in
    Segment 8.

[^detection-boundary]: **Detection-stack boundary positioning**:
    the explicit framing that MemoryHub is *complementary* to
    the existing detection-and-response stack (SIEM, EDR/XDR,
    SOAR, threat intel feeds), not competitive with it. The
    detection stack does detection, alerting, response
    automation, and structured threat data; MemoryHub holds the
    surrounding experience layer.
    *Defined in*: `README.md` ("The
    detection-paradigm boundary" section); reinforced in
    `threat-hunting-incident-response.md`
    ("MemoryHub vs. Detection and Response Tooling" section).
    *Visible in the demo*: framing block in Segment 1, closing
    pitch in Segment 8.
    *Not a tracked feature* — this is positioning, not code.

[^humans-in-loop]: **Agents-support-analysts framing**: every
    agent in the fleet is operated by a human analyst or
    responder in production. The demo presenter plays the role
    of the entire SOC team as a demo necessity, not as a product
    claim about automated response. Critically, this framing
    includes the explicit no-auto-containment disclaimer — SOC
    audiences are particularly sensitive to vendors implying AI
    will execute response actions unattended.
    *Defined in*: `../README.md` ("AI supports
    humans, it doesn't replace them" section);
    `README.md` ("The 'humans in
    production' framing" section); each role description in
    `threat-hunting-incident-response.md`
    has an "In production" sidebar.
    *Visible in the demo*: agent disclaimer in Segment 1; "what
    you cannot say" section is the verbal discipline that keeps
    this framing intact.
    *Not a tracked feature* — this is positioning, not code.

[^identity-triple]: **The owner/actor/driver identity model**:
    every memory operation involves three distinct identities.
    `owner_id` (who the memory belongs to, determines scope),
    `actor_id` (which agent performed the operation, always
    derived from authenticated identity), `driver_id` (on whose
    behalf, may equal actor_id for autonomous operation).
    *Defined in*: `../../../docs/identity-model/data-model.md` ("The
    triple: owner, actor, driver" section). Maps to RFC 8693
    token exchange semantics and FHIR Provenance (the FHIR
    mapping is healthcare-specific but the underlying model
    is domain-agnostic).
    *Tracked in*: GitHub issue #65 (schema migration adding
    `actor_id` and `driver_id` columns to MemoryNode), #66
    (plumbing through tools).
    *Visible in the demo*: agent registration in Segment 2 (each
    agent's `actor_id` shown), audit trail queries in Segment 6
    (both columns visible in result rows).

[^driver-id]: **Driver_id specifically — the on-whose-behalf
    concept**: identifies the principal an agent is acting for.
    Equals `actor_id` for fully autonomous operation; differs
    when the agent is being driven by a human analyst (or
    another agent) on that human's behalf. Captured per-session
    (via `register_session(default_driver_id=...)`) or
    per-request (override parameter).
    *Defined in*: `../../../docs/identity-model/data-model.md` ("Tool API
    changes" section).
    *Tracked in*: GitHub issues #65, #66.
    *Visible in the demo*: on-call rotation moment in Segment 4
    (driver changes while actor stays constant), audit query 2
    in Segment 6 ("everything done on behalf of Maya Chen").

[^role-vs-person]: **Role-as-actor + person-as-driver
    distinction**: in cybersec specifically, this is the
    on-call rotation pattern. A role like "Tier 2 SOC Analyst"
    or "Incident Commander" persists across shift handoffs and
    on-call rotations as a stable `actor_id`; the human
    currently on shift is a rotating `driver_id`. The role's
    accumulated investigation memory survives every staff
    handoff, and the audit trail captures both "what did the
    role know about this incident?" and "who was driving the
    role at time T?" as separately answerable questions.
    *Defined in*: `../../../docs/identity-model/data-model.md`
    (implicitly, via the actor/driver split); the on-call
    rotation pattern is the cybersec parallel to the
    clinical-scenario shift change pattern.
    *Tracked in*: GitHub issues #65, #66 (the underlying
    capability); demonstrated as a SOC pattern by this scenario.
    *Visible in the demo*: on-call rotation moment in Segment 4
    is the central demonstration; audit query 1 in Segment 6
    payoffs the concept by showing the role's actions spanning
    both shifts.

[^project-scope]: **Project-scope membership enforcement**:
    agents are members of specific projects (in the demo,
    `midwest-financial-soc`). Project-scope memories are
    readable/writable only by members. For an MSSP, this is
    how per-customer isolation works — each customer is its
    own project, and an analyst working on Customer A's
    incident cannot accidentally read memories from Customer
    B's environment.
    *Defined in*: `../../../docs/identity-model/authorization.md`
    ("Project membership enforcement (critical path)" section).
    *Tracked in*: GitHub issue #64 (the critical-path
    implementation work).
    *Visible in the demo*: agent registration in Segment 2
    (project membership confirmed); every project-scope memory
    write/read in Segments 3-7 implicitly demonstrates the
    enforcement.

[^cross-incident]: **Cross-incident learning** — the central
    value-prop demonstration for the cybersecurity scenario.
    Two distinct manifestations in this demo:
    (1) **Pattern recognition**: when the Tier 1 agent
    surfaces the IR-2024-117 memory in Segment 3, allowing
    the analyst to recognize a similar pattern from a real
    prior incident.
    (2) **Operational lessons**: when the Endpoint Admin
    agent surfaces the breakglass-rotation-broke-backup
    lesson in Segment 5 at the exact moment of decision.
    Both are forms of "what we learned from past incidents
    that's relevant now," and both live in the same memory
    category.
    *Defined in*: `README.md`
    ("What MemoryHub holds in this scenario" — first and third
    bullets);
    `threat-hunting-incident-response.md`
    (touchpoints 1, 3, 6).
    *Tracked in*: emerges from project-scope membership (#64),
    schema (#65), tool plumbing (#66). No dedicated issue —
    this is the application-level pattern that the underlying
    features enable.
    *Visible in the demo*: **the killer moments in Segments 3
    and 5** — the IR-2024-117 recall and the breakglass
    operational lesson. Also the post-incident learning capture
    in Segment 7.

[^narrative-context]: **Analyst narrative context memory
    category**: the soft, unstructured knowledge that doesn't
    fit in structured detection rules and isn't appropriate
    for SOAR playbooks. Per-customer stakeholder preferences,
    the team's working interpretation of an attacker's
    behavior, the context around why a particular response
    decision was made.
    *Defined in*: `README.md`
    ("What MemoryHub holds in this scenario" — fourth bullet,
    "Per-customer context");
    `threat-hunting-incident-response.md`
    (touchpoint 4).
    *Tracked in*: not a discrete feature — emerges from generic
    `write_memory` + project-scope. The *category* is a
    positioning choice; the implementation is just memory
    storage.
    *Visible in the demo*: per-customer CISO preference memory
    in Segment 5 (the Pat Lindstrom early-notification context),
    post-incident lesson capture in Segment 7.

[^provenance]: **Provenance branches**: a memory can have a
    child branch with `branch_type: "provenance"` that records
    where the memory's content came from (a specific incident,
    a specific source, a specific analyst observation). Lets
    future readers understand the basis of a memory without
    re-deriving it. The "from IR-2024-117" linkage in the
    cross-incident memories is a provenance reference.
    *Defined in*: `../../../docs/memory-tree.md` (the underlying tree
    branch model).
    *Tracked in*: existing functionality, no new issue. The
    branch model is already implemented.
    *Visible in the demo*: implicit in the cross-incident
    memory references — every "from IR-2024-117" reference is a
    provenance link to a prior incident's memory tree.

[^data-curation]: **Sensitive-data curation pipeline**: when an
    agent attempts to write a memory containing sensitive data
    (credentials in plaintext, executive identification, source
    and method details), the curation pipeline catches the
    attempted write and quarantines it before persistence. The
    agent then reformulates the memory to preserve operational
    meaning without the sensitive details. Note: the pipeline
    itself is the same code as the healthcare PHI/PII pipeline,
    but the *patterns* are domain-specific. The cybersec
    patterns (credentials, exec identification, source/method
    redaction) are not yet built — they would be a future
    issue, separate from #68 (healthcare PHI patterns).
    *Defined in*: `threat-hunting-incident-response.md`
    ("Sensitive-data moments" section). The underlying pipeline
    is documented in `../clinical/demo-plan.md`.
    *Tracked in*: pipeline stub via #68 for healthcare; cybersec
    patterns are a future issue (not yet filed). The two
    quarantine moments in the demo would need this future work
    to land for real.
    *Visible in the demo*: executive identification quarantine
    in Segment 4 (Tier 2 attempts to write "Pat M., CFO");
    credential quarantine in Segment 5 (Identity Admin attempts
    to write rotated passwords).

[^audit]: **Audit log**: every memory operation (write, read,
    update, delete, contradiction report, quarantine) is
    captured by `audit.record_event(...)` with both `actor_id`
    and `driver_id` recorded. For the demo, the persistence
    layer is a stub that writes structured log lines; future
    work will route through LlamaStack telemetry (which RHOAI
    ships natively as a Tech Preview, avoiding the need to
    build a custom audit log).
    *Defined in*: `../../../docs/identity-model/authorization.md` ("Audit
    logging — stub now, persistence later" section).
    *Tracked in*: GitHub issue #67 (audit logging stub
    interface), #70 (persistent audit log via LlamaStack
    telemetry).
    *Visible in the demo*: quarantine attempts visible in audit
    in Segments 4 and 5; audit queries are the centerpiece of
    Segment 6.

[^tribal-knowledge]: **Analyst tribal knowledge memory
    category**: the practices a SOC team has developed that
    aren't formal SIEM rules or SOAR playbooks but are how the
    team actually works. The "service account alerts after 8pm
    are 80% worth escalating" heuristic in this scenario is
    the canonical example. This kind of knowledge lives in
    senior analyst heads and walks out the door when staff
    leave — exactly the kind of attrition impact a SOC manager
    cares about.
    *Defined in*: `README.md`
    ("What MemoryHub holds in this scenario" — second bullet);
    `threat-hunting-incident-response.md`
    (touchpoint 2).
    *Tracked in*: not a discrete feature — same emergence as
    narrative context. Category positioning, not separate code.
    *Visible in the demo*: tribal knowledge moment in Segment 3
    (Tier 1 agent surfaces the off-hours service account
    heuristic alongside the IR-2024-117 recall).

[^contradiction]: **Contradiction detection** via the
    `report_contradiction` tool. When one memory's
    interpretation conflicts with another's, an agent surfaces
    the conflict explicitly. Both memories are preserved; the
    contradiction relationship is queryable; the team uses the
    surfaced conflict to update their working interpretation
    without losing the original observation. In cybersec
    specifically, the most natural contradiction surface is
    attribution disagreements during investigation — different
    analysts reach different conclusions about the same
    evidence, and the team needs to track the disagreement
    explicitly rather than letting one view silently win.
    *Defined in*: `threat-hunting-incident-response.md`
    ("Contradiction moments" section). The
    `report_contradiction` tool already exists in the MCP
    server; this is reuse, not new feature work.
    *Tracked in*: existing tool. Demo scenario validation
    needed before this lands cleanly.
    *Visible in the demo*: attribution contradiction in
    Segment 4 (Threat Intel vs Network Analyst on
    CC2024-Q3-Opportunistic match).

[^operational-memory]: **Agent-operational memory category**:
    the agent fleet writes memories about *itself* —
    operational lessons it has learned about how it works. No
    human writes these; no human reads them directly. They're
    the AI fleet's self-correction layer. In cybersec,
    examples include false-positive filters the fleet has
    derived from prior investigations and operational
    heuristics about which queries to run when.
    *Defined in*: `README.md`
    ("What MemoryHub holds in this scenario" — fifth bullet);
    `threat-hunting-incident-response.md`
    (touchpoint 5).
    *Tracked in*: not a discrete feature — emerges from
    `write_memory` + scope/owner conventions. The *category*
    is novel positioning.
    *Visible in the demo*: brief mention in Segment 4 (the
    Forensics agent's `ai.exe` filter applied automatically
    based on a self-written prior memory). Most novel demo
    moment, but at risk of confusing the audience — frame
    carefully.

[^versioning]: **Memory versioning via `update_memory`**: when
    new information supersedes an existing memory, the agent
    calls `update_memory` (preserves version history with
    `isCurrent` flag) instead of writing a new "actually..."
    memory. Future readers see the current state and can
    inspect the history of how the team's understanding
    evolved. Not heavily demonstrated in the cybersec script
    (the central narrative is cross-incident learning rather
    than within-incident revision), but referenced in the
    contradiction-resolution flow.
    *Defined in*: `../../../docs/memory-tree.md` (versioning model with
    `isCurrent` flag, already implemented).
    *Tracked in*: existing functionality.
    *Visible in the demo*: implicit in the contradiction
    resolution in Segment 4 (the attribution contradiction's
    resolution preserves both views via the contradiction
    relationship rather than overwriting).

[^cli-provisioning]: **Agent generation CLI**: a static
    code-gen tool that takes a fleet manifest YAML and
    produces Kubernetes Secrets, the users ConfigMap, and the
    harness manifest needed to deploy and identify the demo's
    agent fleet. The CLI is the source of the ten SOC agents
    seen in the demo.
    *Defined in*: `../../../docs/identity-model/cli-requirements.md`
    (the full requirements doc for the CLI).
    *Tracked in*: GitHub issue #69 (build agent generation CLI
    for demo fleet provisioning).
    *Visible in the demo*: implicit in the agent fleet startup
    in Segment 2. Not directly demoed, but the existence of
    the fleet depends on it. Worth a one-liner mention if
    there's time and the audience is operationally curious
    ("the fleet you see was provisioned from a single YAML
    manifest, the same way you'd provision a SOC fleet for a
    new MSSP customer").
