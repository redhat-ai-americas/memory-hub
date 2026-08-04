#!/usr/bin/env python3
"""SOC Demo Orchestration Harness.

Drives 4 SOC agents through a 7-phase incident response scenario,
producing rich terminal output suitable for recording with asciinema.

Each agent is identified by its framework (Claude Code, FIPS-Agent,
OpenClaw, Hermes) and SOC role. All agents share memory through
MemoryHub, demonstrating cross-framework memory interoperability.

Usage:
    cd memory-hub
    python demos/soc-demo/harness.py
"""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../sdk/src"))

import logging
logging.basicConfig(level=logging.CRITICAL)
for _logger_name in ("memoryhub", "httpx", "httpcore", "fastmcp", "mcp", "anyio"):
    logging.getLogger(_logger_name).setLevel(logging.CRITICAL)

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from memoryhub import MemoryHubClient

console = Console(width=132)

PROJECT_ID = "midwest-financial-soc"

AGENTS = {
    "tier1": {
        "name": "Tier 1 SOC Analyst",
        "framework": "Claude Code",
        "color": "cyan",
        "actor_id": "soc-tier1-analyst",
    },
    "forensics": {
        "name": "Forensics Specialist",
        "framework": "FIPS-Agent",
        "color": "green",
        "actor_id": "soc-forensics",
    },
    "threatintel": {
        "name": "Threat Intel Analyst",
        "framework": "Hermes",
        "color": "yellow",
        "actor_id": "soc-threatintel",
    },
    "ic": {
        "name": "Incident Commander",
        "framework": "OpenClaw",
        "color": "magenta",
        "actor_id": "soc-ic",
    },
}

PHASE_PAUSE = float(os.environ.get("HARNESS_PHASE_PAUSE", "2.0"))
ACTION_PAUSE = float(os.environ.get("HARNESS_ACTION_PAUSE", "1.0"))


def agent_label(agent_key: str) -> Text:
    agent = AGENTS[agent_key]
    label = Text()
    label.append(f"[{agent['framework']}]", style=f"bold {agent['color']}")
    label.append(f" {agent['name']}", style=f"{agent['color']}")
    return label


def print_phase(number: int, title: str, time_str: str, detail: str):
    console.print()
    header = Text()
    header.append(f"PHASE {number}", style="bold white on blue")
    header.append(f"  {title}", style="bold white")
    header.append(f"  [{time_str}]", style="dim white")
    console.rule(header, style="blue")
    console.print(f"  {detail}", style="dim")
    console.print()
    time.sleep(PHASE_PAUSE)


def print_action(agent_key: str, action: str, detail: str = ""):
    label = agent_label(agent_key)
    action_text = Text()
    action_text.append(label)
    action_text.append(f"  {action}", style="white")
    if detail:
        action_text.append(f"  {detail}", style="dim")
    console.print(action_text)


def print_memory_found(agent_key: str, content: str, source: str = ""):
    agent = AGENTS[agent_key]
    title = f"Memory recalled by {agent['name']}"
    if source:
        title += f" (from {source})"
    panel = Panel(
        content,
        title=title,
        title_align="left",
        border_style=agent["color"],
        width=120,
        padding=(1, 2),
    )
    console.print(panel)
    time.sleep(ACTION_PAUSE)


def print_memory_written(agent_key: str, content: str, memory_id: str):
    agent = AGENTS[agent_key]
    panel = Panel(
        content,
        title=f"{agent['name']} writes memory",
        subtitle=f"id: {memory_id}  |  framework: {agent['framework']}",
        title_align="left",
        subtitle_align="right",
        border_style=f"bold {agent['color']}",
        width=120,
        padding=(1, 2),
    )
    console.print(panel)
    time.sleep(ACTION_PAUSE)


def print_contradiction(reporter_key: str, target_content: str, reason: str):
    agent = AGENTS[reporter_key]
    inner = Text()
    inner.append("ORIGINAL ASSESSMENT:\n", style="dim")
    inner.append(target_content[:200] + "...\n\n", style="white")
    inner.append("CONTRADICTION:\n", style="bold red")
    inner.append(reason, style="white")
    panel = Panel(
        inner,
        title=f"CONTRADICTION REPORTED by {agent['name']}",
        title_align="left",
        border_style="bold red",
        width=120,
        padding=(1, 2),
    )
    console.print(panel)
    time.sleep(ACTION_PAUSE)


def print_quarantine(agent_key: str, rejected: str, rewritten: str):
    agent = AGENTS[agent_key]
    inner = Text()
    inner.append("REJECTED (quarantined):\n", style="bold red")
    inner.append(rejected + "\n\n", style="red")
    inner.append("REWRITTEN (accepted):\n", style="bold green")
    inner.append(rewritten, style="green")
    panel = Panel(
        inner,
        title=f"SENSITIVE DATA QUARANTINE — {agent['name']}",
        title_align="left",
        border_style="bold red on white",
        width=120,
        padding=(1, 2),
    )
    console.print(panel)
    time.sleep(ACTION_PAUSE)


def print_shift_change(role: str, old_driver: str, new_driver: str, actor_id: str):
    table = Table(
        title="SHIFT CHANGE",
        box=box.DOUBLE,
        border_style="yellow",
        title_style="bold yellow",
        width=80,
    )
    table.add_column("Field", style="dim")
    table.add_column("Before", style="red")
    table.add_column("After", style="green")
    table.add_row("Role (actor_id)", actor_id, actor_id)
    table.add_row("Human (driver_id)", old_driver, new_driver)
    table.add_row("Shift", "Night shift", "Day shift")
    console.print(table)
    time.sleep(ACTION_PAUSE)


def print_audit_query(title: str, rows: list[dict]):
    table = Table(
        title=title,
        box=box.ROUNDED,
        border_style="bright_white",
        title_style="bold white",
        width=120,
    )
    table.add_column("Timestamp", style="dim", width=12)
    table.add_column("Action", width=20)
    table.add_column("Actor (agent)", style="cyan", width=25)
    table.add_column("Driver (human)", style="yellow", width=25)
    for row in rows:
        table.add_row(row["time"], row["action"], row["actor"], row["driver"])
    console.print(table)
    time.sleep(ACTION_PAUSE)


async def run_scenario():
    url = os.environ.get("MEMORYHUB_URL", "")
    api_key = os.environ.get("MEMORYHUB_API_KEY", "")

    if not url or not api_key:
        import configparser
        config = configparser.ConfigParser()
        config.read(os.path.expanduser("~/.config/memoryhub/credentials"))
        section = os.environ.get("MEMORYHUB_CONTEXT", "mcp-rhoai")
        if section not in config:
            section = "default"
        api_key = api_key or config.get(section, "api_key", fallback="")
        url = url or config.get(section, "url", fallback="")

    if not url or not api_key:
        console.print("[red]Error: Set MEMORYHUB_URL and MEMORYHUB_API_KEY[/]")
        return 1

    # Title card
    console.print()
    title = Panel(
        Text.from_markup(
            "[bold white]MemoryHub: the context that makes security decisions go well.[/]\n\n"
            "[dim]A demonstration with a realistic mid-severity SOC incident.[/]\n"
            "[dim]Four agent frameworks. One shared memory. Ten minutes.[/]\n\n"
            "[cyan]Claude Code[/]  ·  [green]FIPS-Agent[/]  ·  [magenta]OpenClaw[/]  ·  [yellow]Hermes[/]"
        ),
        title="SOC INCIDENT RESPONSE DEMO",
        title_align="center",
        border_style="bold blue",
        width=120,
        padding=(1, 4),
    )
    console.print(title)
    time.sleep(PHASE_PAUSE)

    # Agent fleet registration
    console.rule("[bold white]Agent Fleet Registration[/]", style="blue")
    console.print()
    reg_table = Table(box=box.SIMPLE, width=100)
    reg_table.add_column("Role", style="bold")
    reg_table.add_column("Framework", style="dim")
    reg_table.add_column("actor_id", style="cyan")
    reg_table.add_column("driver_id", style="yellow")
    for key, agent in AGENTS.items():
        reg_table.add_row(
            Text(agent["name"], style=agent["color"]),
            agent["framework"],
            agent["actor_id"],
            "jason-park (night shift)",
        )
        time.sleep(0.3)
    console.print(reg_table)
    console.print()
    time.sleep(PHASE_PAUSE)

    async with MemoryHubClient(url=url, api_key=api_key) as client:

        # ── PHASE 1: Detection ──────────────────────────────────────
        print_phase(1, "DETECTION", "02:14 AM",
                    "CrowdStrike behavioral SIEM alert: unusual logon for svc-reporting")

        print_action("tier1", "search_memory",
                     "query='unusual service account logon off-hours SMB enumeration'")
        sr = await client.search(
            "unusual service account logon off-hours SMB enumeration",
            scope="project", project_id=PROJECT_ID,
        )

        if sr.results:
            top = sr.results[0]
            print_memory_found("tier1", top.content, "IR-2024-117")

        # Tier 1 heuristic
        sr2 = await client.search(
            "service account alerts off-hours escalation heuristic",
            scope="project", project_id=PROJECT_ID,
        )
        for r in sr2.results:
            if "80%" in r.content:
                print_memory_found("tier1", r.content, "Team practice")
                break

        # Tier 1 escalation
        esc = await client.write(
            "IR-2024-184 triage decision: Escalating to Tier 2 at 02:38 AM. "
            "Pattern matches IR-2024-117 (phishing-derived credential, off-hours "
            "service account anomaly, SMB enumeration). Team heuristic confirms: "
            "off-hours service account alerts are 80% worth escalating. "
            "Recommending full investigation.",
            scope="project", project_id=PROJECT_ID, weight=0.9,
            metadata={"incident_id": "IR-2024-184", "role": "tier1-analyst",
                       "framework": "claude-code"},
            force=True,
        )
        esc_id = esc.memory.id if esc.memory else "pending"
        print_memory_written("tier1", (
            "IR-2024-184 triage decision: Escalating to Tier 2 at 02:38 AM. "
            "Pattern matches IR-2024-117. Team heuristic confirms escalation."
        ), esc_id)

        # ── PHASE 2: Triage & Escalation ────────────────────────────
        print_phase(2, "TRIAGE & ESCALATION", "02:14 — 02:55",
                    "Tier 1 → Tier 2 escalation. IR team paged at 02:55.")

        print_action("tier1", "escalate_to_tier2",
                     "Confirmed unauthorized access. Paging IR team.")
        time.sleep(ACTION_PAUSE)

        # ── PHASE 3: Investigation ──────────────────────────────────
        print_phase(3, "INVESTIGATION", "02:55 — 06:00",
                    "Parallel investigation: Forensics, Threat Intel, IC activated")

        # Forensics: ai.exe filter
        print_action("forensics", "search_memory",
                     "query='outlook.exe child processes false positive'")
        sr3 = await client.search(
            "outlook.exe ai.exe false positive forensics",
            scope="project", project_id=PROJECT_ID,
        )
        for r in sr3.results:
            if "ai.exe" in r.content:
                print_memory_found("forensics", r.content, "Self-authored operational memory")
                break

        print_action("forensics", "apply_filter",
                     "Filtering ai.exe from outlook.exe child process queries (3 prior incidents)")

        # Forensics: staging paths
        sr4 = await client.search(
            "staging paths attacker file server directory",
            scope="project", project_id=PROJECT_ID,
        )
        for r in sr4.results:
            if "staging" in r.content.lower() and "admin$" in r.content:
                print_memory_found("forensics", r.content, "IR-2024-117 technique pattern")
                break

        # Forensics writes timeline
        timeline_content = (
            "IR-2024-184 forensic timeline: Attacker first accessed WKSTN-FIN-082 "
            "at 15:22 on March 4 using svc-reporting credential harvested via "
            "phishing 11 days prior. Enumeration phase (March 4-14) stayed within "
            "business hours to blend with normal traffic. Staging began at 20:47 "
            "on March 14 with 47 GB copied to \\\\FILESVR-CORP-03\\admin$\\TEMP\\reports2024\\. "
            "CrowdStrike behavioral rule fired at 02:14 March 15 when staging "
            "volume crossed 30 GB threshold."
        )
        fw = await client.write(
            timeline_content, scope="project", project_id=PROJECT_ID,
            weight=0.9,
            metadata={"incident_id": "IR-2024-184", "role": "forensics",
                       "framework": "fips-agent"},
            force=True,
        )
        fw_id = fw.memory.id if fw.memory else "pending"
        print_memory_written("forensics", timeline_content, fw_id)

        # Threat Intel: attribution
        attr_content = (
            "IR-2024-184 initial attribution assessment: TTPs partially match "
            "CC2024-Q3-Opportunistic campaign. Phishing initial access, 9-14 day "
            "dwell time, file server staging all consistent. Recommend handling "
            "as a known campaign. Confidence: MEDIUM."
        )
        attr = await client.write(
            attr_content, scope="project", project_id=PROJECT_ID,
            weight=0.85,
            metadata={"incident_id": "IR-2024-184", "role": "threat-intel",
                       "framework": "hermes"},
            force=True,
        )
        attr_id = attr.memory.id if attr.memory else "pending"
        print_memory_written("threatintel", attr_content, attr_id)

        # ── PHASE 4: Scoping ────────────────────────────────────────
        print_phase(4, "SCOPING", "04:00 — 06:30",
                    "Determining scope: systems affected, data exposure, attacker next move")

        # Shift change at 06:00
        print_shift_change("Tier 2 SOC Analyst",
                           "jason-park", "maya-chen", "soc-tier2-analyst")

        # Network Analyst contradicts attribution
        contra_reason = (
            "Looked at the C2 traffic. The beaconing pattern doesn't match "
            "CC2024-Q3-Opportunistic. The known campaign uses 90-second beacon "
            "intervals with jitter; this incident shows no consistent beaconing "
            "pattern at all -- the attacker is using interactive sessions rather "
            "than implant beacons. Either this is a different attacker reusing "
            "some of the same TTPs, or the campaign has evolved its tooling. "
            "Either way, don't assume the rest of the campaign's playbook applies."
        )

        if attr_id != "pending":
            try:
                await client.report_contradiction(
                    memory_id=attr_id,
                    observed_behavior=contra_reason,
                )
            except Exception:
                pass

        print_contradiction("threatintel", attr_content, contra_reason)

        # Sensitive data quarantine: executive identification
        print_quarantine(
            "tier1",
            "The phishing email that started this incident was sent to Pat M. "
            "(CFO of MidWest Financial Services). Pat opened it from her phone "
            "at 8:14 PM on March 15.",
            "The phishing email that started this incident was sent to a finance "
            "department user. The email was opened from a mobile device on the "
            "evening of March 15. Specific user identity is documented in the "
            "case management system, not in shared memory.",
        )

        # ── PHASE 5: Containment ────────────────────────────────────
        print_phase(5, "CONTAINMENT", "06:00 — 08:00",
                    "Credential rotation, endpoint isolation, stakeholder notification")

        # Breakglass lesson
        print_action("ic", "search_memory",
                     "query='breakglass credential rotation backup impact'")
        sr5 = await client.search(
            "breakglass credential rotation backup Veeam incident",
            scope="project", project_id=PROJECT_ID,
        )
        for r in sr5.results:
            if "breakglass" in r.content.lower():
                print_memory_found("ic", r.content, "IR-2024-103 operational lesson")
                break

        print_action("ic", "coordinate_containment",
                     "Paging backup admin BEFORE breakglass rotation. Notifying NOC.")

        # CISO notification preference
        print_action("ic", "search_memory",
                     "query='CISO notification preference PII exposure'")
        sr6 = await client.search(
            "CISO notification PII exposure preference early",
            scope="project", project_id=PROJECT_ID,
        )
        for r in sr6.results:
            if "Lindstrom" in r.content or "notification" in r.content.lower():
                print_memory_found("ic", r.content, "Stakeholder preference")
                break

        print_action("ic", "notify_ciso",
                     "Early notification at 07:00 -- potential PII exposure (finance documents staged)")

        # Credential quarantine
        print_quarantine(
            "forensics",
            "Rotated svc-reporting credential. Old password was Welcome2024!Q3, "
            "new password is Tk7$mNp2#vR9wQ4z. Documenting for handoff.",
            "Rotated svc-reporting credential at 06:42 per IR-2024-184 containment "
            "plan. New credential stored in privileged access management vault per "
            "standard procedure. Old credential is now invalid.",
        )

        # IC synthesis
        synth_content = (
            "IR-2024-184 IC synthesis (06:00 shift handoff brief): "
            "Confirmed credential compromise via phishing, 11-day dwell. "
            "47 GB staged on FILESVR-CORP-03, no exfiltration confirmed. "
            "Attribution to CC2024-Q3 is LOW confidence per Threat Intel -- "
            "beaconing pattern mismatch. Containment in progress: WKSTN-FIN-082 "
            "isolated, svc-reporting rotated. Coordinated with backup admin "
            "before breakglass rotation per IR-2024-103 lesson. CISO notified "
            "at 07:00 per standing preference."
        )
        sw = await client.write(
            synth_content, scope="project", project_id=PROJECT_ID,
            weight=0.95,
            metadata={"incident_id": "IR-2024-184", "role": "incident-commander",
                       "framework": "openclaw"},
            force=True,
        )
        sw_id = sw.memory.id if sw.memory else "pending"
        print_memory_written("ic", synth_content, sw_id)

        # ── PHASE 6: Audit Trail ────────────────────────────────────
        print_phase(6, "AUDIT TRAIL", "Post-containment",
                    "Chain of evidence: who did what, and on whose behalf")

        print_audit_query(
            "Query 1: Everything the Tier 2 role did during IR-2024-184",
            [
                {"time": "02:38", "action": "escalation_received", "actor": "soc-tier2-analyst", "driver": "jason-park"},
                {"time": "03:15", "action": "hypothesis_formed", "actor": "soc-tier2-analyst", "driver": "jason-park"},
                {"time": "04:30", "action": "scope_assessment", "actor": "soc-tier2-analyst", "driver": "jason-park"},
                {"time": "06:01", "action": "shift_handoff_recv", "actor": "soc-tier2-analyst", "driver": "maya-chen"},
                {"time": "07:42", "action": "containment_confirm", "actor": "soc-tier2-analyst", "driver": "maya-chen"},
            ],
        )

        print_audit_query(
            "Query 2: Everything done on behalf of Maya Chen across all roles",
            [
                {"time": "06:01", "action": "shift_handoff_recv", "actor": "soc-tier2-analyst", "driver": "maya-chen"},
                {"time": "06:15", "action": "search_memory", "actor": "soc-threat-hunter", "driver": "maya-chen"},
                {"time": "06:30", "action": "containment_review", "actor": "soc-tier2-analyst", "driver": "maya-chen"},
                {"time": "07:00", "action": "ciso_notification", "actor": "soc-comms-liaison", "driver": "maya-chen"},
                {"time": "07:42", "action": "containment_confirm", "actor": "soc-tier2-analyst", "driver": "maya-chen"},
            ],
        )

        # ── PHASE 7: Post-Incident ──────────────────────────────────
        print_phase(7, "POST-INCIDENT LEARNING", "24-72 hours later",
                    "Lessons captured into shared memory for future incidents")

        lesson1 = (
            "IR-2024-184 confirms the IR-2024-117 attacker pattern is still active. "
            "Two things we learned: (1) the attacker waited 11 days between credential "
            "harvest and first lateral movement, longer than the 9 days in IR-2024-117. "
            "Our default 'go back 14 days' assumption needs to extend to 21 days. "
            "(2) The attacker used normal working hours during enumeration, then "
            "switched to off-hours during staging. Hunting hypothesis: when "
            "investigating service account anomalies, also pull the human user's "
            "recent access patterns and look for time-of-day shifts."
        )
        l1 = await client.write(
            lesson1, scope="project", project_id=PROJECT_ID, weight=0.95,
            metadata={"incident_id": "IR-2024-184", "role": "incident-commander",
                       "framework": "openclaw", "category": "post-incident-lesson"},
            force=True,
        )
        l1_id = l1.memory.id if l1.memory else "pending"
        print_memory_written("ic", lesson1, l1_id)

    # ── Closing ─────────────────────────────────────────────────
    console.print()
    closing = Panel(
        Text.from_markup(
            "[bold white]What you just saw:[/]\n\n"
            "1. Tier 1 escalated at 02:38 because the agent fleet remembered "
            "IR-2024-117 [cyan](Claude Code)[/]\n"
            "2. Forensics filtered ai.exe false positives from self-authored "
            "operational memory [green](FIPS-Agent)[/]\n"
            "3. Threat Intel's attribution was contradicted and the investigation "
            "adjusted [yellow](Hermes)[/]\n"
            "4. Breakglass rotation didn't break backup because an 8-month-old "
            "lesson surfaced [magenta](OpenClaw)[/]\n"
            "5. Audit trail answers both 'what did this role do?' and 'what was "
            "done on behalf of this analyst?'\n\n"
            "[bold]Four frameworks. One shared memory. Zero integration code "
            "beyond pointing each agent at the same MCP server.[/]"
        ),
        title="MEMORYHUB: THE CONTEXT THAT MAKES SECURITY DECISIONS GO WELL",
        title_align="center",
        border_style="bold blue",
        width=120,
        padding=(1, 4),
    )
    console.print(closing)
    console.print()
    return 0


def main():
    return asyncio.run(run_scenario())


if __name__ == "__main__":
    sys.exit(main())
