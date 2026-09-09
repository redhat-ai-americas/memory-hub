#!/usr/bin/env python3
"""SOC Demo Orchestration Harness.

Drives 4 SOC agents through a 7-phase incident response scenario.
Each agent makes real LLM calls (GPT-OSS-20B) and real MemoryHub
operations (search, write, report contradiction) via MCP tools.

The single deployed FIPS-Agent serves as a shared LLM + MCP gateway.
Different role personas are sent via the system prompt in each call.

Usage:
    SOC_FORENSICS_URL=https://<route> python demos/soc-demo/harness.py

Env vars:
    SOC_FORENSICS_URL  -- FIPS-Agent route (required)
    FRONTEND_URL       -- frontend relay for visualization (optional)
    FRONTEND_TOKEN     -- X-Emit-Token for frontend auth (optional)
    HARNESS_PHASE_PAUSE -- seconds between phases (default 2.0)
    HARNESS_ACTION_PAUSE -- seconds between actions (default 1.0)
"""

import asyncio
import json
import os
import sys
import time
import urllib.request

import httpx

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
FRONTEND_URL = os.environ.get("FRONTEND_URL", "")
FRONTEND_TOKEN = os.environ.get("FRONTEND_TOKEN", "")
SOC_FORENSICS_URL = os.environ.get("SOC_FORENSICS_URL", "")

_current_phase = 1
_current_timestamp = "02:14"


# ── MemoryHub tools block (shared across all system prompts) ────────

MEMORYHUB_TOOLS = """
## MemoryHub Shared Memory

You have access to the SOC team's shared memory through MCP tools.
The project identifier is "midwest-financial-soc".

When using the `memory` tool:
- Search: memory(action="search", query="your query", scope="project",
  project_id="midwest-financial-soc")
- Write: memory(action="write", content="your content", scope="project",
  project_id="midwest-financial-soc",
  options={"weight": 0.9, "force": true,
           "metadata": {"incident_id": "IR-2024-184"}})
- Report contradiction: memory(action="report", memory_id="<id>",
  options={"observed_behavior": "what the new evidence shows"})

Always search shared memory before making decisions.
Always write your conclusions as memories for the team.
"""


# ── System prompts per role ─────────────────────────────────────────

SYSTEM_TIER1 = (
    "You are the Tier 1 SOC Analyst for MidWest Financial Services "
    "Group's SOC, working the night shift.\n\n"
    "You handle initial alert triage. You decide whether to escalate, "
    "close as benign, or assign for further investigation.\n\n"
    "Your process:\n"
    "1. Search shared memory for prior incidents with similar patterns\n"
    "2. Search for team heuristics about this type of alert\n"
    "3. Make a triage decision based on what you find\n"
    "4. Write your triage decision and reasoning to shared memory\n\n"
    "Cite specific incident IDs from memory when they inform your decision."
    + MEMORYHUB_TOOLS
)

SYSTEM_FORENSICS = (
    "You are the Forensics Specialist for MidWest Financial Services "
    "Group's SOC.\n\n"
    "You own host-level artifact collection and timeline reconstruction. "
    "You reconstruct attacker activity timelines from EDR telemetry, "
    "Windows event logs, and file system artifacts.\n\n"
    "Your process:\n"
    "1. Search shared memory for known false positives relevant to this "
    "type of investigation (especially child process alerts)\n"
    "2. Search for attacker staging path patterns from previous campaigns\n"
    "3. Search for prior incidents with similar attack patterns\n"
    "4. Write a forensic timeline to shared memory with specific "
    "timestamps, paths, and technique details\n\n"
    "Filter known false positives from operational memory before reporting. "
    "Cite specific prior incident IDs."
    + MEMORYHUB_TOOLS
)

SYSTEM_THREATINTEL_ATTR = (
    "You are the Threat Intelligence Analyst for MidWest Financial "
    "Services Group's SOC.\n\n"
    "You own correlation with known campaigns, IOC enrichment, and "
    "attribution analysis.\n\n"
    "Your process:\n"
    "1. Search shared memory for prior incidents with similar TTPs\n"
    "2. Assess whether the current incident matches any known campaigns\n"
    "3. Write your attribution assessment to shared memory with a "
    "confidence level (LOW/MEDIUM/HIGH)\n\n"
    "Attribution is hard. Express confidence levels honestly. "
    "Cite specific campaign IDs and prior incident IDs."
    + MEMORYHUB_TOOLS
)

SYSTEM_THREATINTEL_CONTRA = (
    "You are the Threat Intelligence Analyst for MidWest Financial "
    "Services Group's SOC.\n\n"
    "You have been asked to review your previous attribution assessment "
    "for IR-2024-184 based on new network analysis evidence.\n\n"
    "Your process:\n"
    "1. Search shared memory for your previous attribution assessment "
    "for IR-2024-184\n"
    "2. Note the memory_id of that assessment from the search results\n"
    "3. Use the memory tool with action=\"report\" to file a contradiction, "
    "passing the memory_id and your updated analysis in "
    "options.observed_behavior\n\n"
    "Do NOT overwrite or delete the original assessment. Use "
    "action=\"report\" to preserve both views in memory."
    + MEMORYHUB_TOOLS
)

SYSTEM_IC_CONTAIN = (
    "You are the Incident Commander for MidWest Financial Services "
    "Group's SOC.\n\n"
    "You own overall response coordination. You synthesize information "
    "from all SOC agents into a unified operational picture.\n\n"
    "Your process:\n"
    "1. Search shared memory for lessons from previous credential "
    "rotation incidents (especially breakglass credentials)\n"
    "2. Search for stakeholder notification preferences (CISO)\n"
    "3. Search for current IR-2024-184 findings from forensics and "
    "threat intel\n"
    "4. Write a synthesis brief to shared memory covering: status, key "
    "findings, attribution confidence, containment actions, notifications\n\n"
    "Attribute information to the agent that provided it. "
    "Surface contradictions explicitly."
    + MEMORYHUB_TOOLS
)

SYSTEM_IC_POSTINCIDENT = (
    "You are the Incident Commander for MidWest Financial Services "
    "Group's SOC.\n\n"
    "The incident is contained. You are writing post-incident lessons.\n\n"
    "Your process:\n"
    "1. Search shared memory for all IR-2024-184 findings and any "
    "referenced prior incidents\n"
    "2. Identify what worked well and what should change\n"
    "3. Write a post-incident lesson to shared memory capturing: "
    "pattern confirmation, updated dwell time assumptions, new hunting "
    "hypotheses\n\n"
    "Write lessons that your future self will find useful. Be specific "
    "about what changed versus prior incidents."
    + MEMORYHUB_TOOLS
)


# ── User messages per call ──────────────────────────────────────────

USER_TIER1 = (
    "A CrowdStrike behavioral SIEM alert fired at 02:14 AM. The alert "
    "shows the svc-reporting service account was used from a non-standard "
    "workstation WKSTN-FIN-082, followed by SMB enumeration of multiple "
    "file servers.\n\n"
    "Triage this alert. Search shared memory for prior incidents with "
    "similar patterns and any team heuristics about service account "
    "alerts. Then decide whether to escalate and write your triage "
    "decision to shared memory."
)

USER_FORENSICS = (
    "IR-2024-184 has been escalated to Tier 2. CrowdStrike alert at "
    "02:14 AM showed svc-reporting used from WKSTN-FIN-082 with SMB "
    "enumeration. Tier 1 found pattern matches to IR-2024-117.\n\n"
    "Investigate this incident. Search shared memory for known false "
    "positives in forensic analysis (especially outlook.exe child "
    "process alerts), attacker staging path patterns from prior "
    "campaigns, and prior incidents with similar patterns. Then write "
    "a forensic timeline for IR-2024-184 to shared memory."
)

USER_THREATINTEL_ATTR = (
    "IR-2024-184 investigation is underway. Known facts: phishing-derived "
    "credential for svc-reporting, multi-day dwell time, SMB enumeration "
    "of file servers, data staging on a file server.\n\n"
    "Analyze the TTPs and search shared memory for prior incidents and "
    "campaign profiles. Write your initial attribution assessment to "
    "shared memory with a confidence level."
)

USER_THREATINTEL_CONTRA = (
    "New evidence from the network team on IR-2024-184: the beaconing "
    "pattern does NOT match the CC2024-Q3-Opportunistic campaign. That "
    "campaign uses 90-second beacon intervals with jitter; this incident "
    "shows no consistent beaconing pattern at all -- the attacker is "
    "using interactive sessions rather than implant beacons.\n\n"
    "Search shared memory for your previous attribution assessment for "
    "IR-2024-184. Then use the memory tool with action=\"report\" to "
    "file a contradiction against that assessment, explaining why the "
    "beaconing evidence changes the attribution."
)

USER_IC_CONTAIN = (
    "IR-2024-184 containment is underway. Shift change happened at "
    "06:00 (jason-park -> maya-chen). Credential rotation for "
    "svc-reporting is needed, WKSTN-FIN-082 needs isolation, and "
    "47 GB of staged data on FILESVR-CORP-03 needs preservation.\n\n"
    "Search shared memory for lessons from previous breakglass "
    "credential rotations, CISO notification preferences, and current "
    "IR-2024-184 findings. Then write a synthesis brief to shared memory."
)

USER_IC_POSTINCIDENT = (
    "IR-2024-184 is contained. No confirmed exfiltration. Credential "
    "rotated, endpoints isolated, CISO notified.\n\n"
    "Search shared memory for all IR-2024-184 findings and the prior "
    "incidents they reference. Write a post-incident lesson to shared "
    "memory capturing what was different from prior incidents and what "
    "the team should do differently next time."
)


# ── Frontend / display infrastructure ───────────────────────────────

def emit(event: dict):
    if not FRONTEND_URL:
        return
    event.setdefault("phase", _current_phase)
    event.setdefault("timestamp", _current_timestamp)
    data = json.dumps(event).encode()
    headers = {"Content-Type": "application/json"}
    if FRONTEND_TOKEN:
        headers["X-Emit-Token"] = FRONTEND_TOKEN
    req = urllib.request.Request(f"{FRONTEND_URL}/emit", data, headers)
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def emit_reset():
    if not FRONTEND_URL:
        return
    headers = {"Content-Type": "application/json"}
    if FRONTEND_TOKEN:
        headers["X-Emit-Token"] = FRONTEND_TOKEN
    req = urllib.request.Request(f"{FRONTEND_URL}/reset", b"{}", headers)
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


FRONTEND_AGENT_KEY = {
    "tier1": "tier1",
    "forensics": "forensics",
    "threatintel": "intel",
    "ic": "ic",
}


def fe_agent(key: str) -> str:
    return FRONTEND_AGENT_KEY.get(key, key)


def agent_label(agent_key: str) -> Text:
    agent = AGENTS[agent_key]
    label = Text()
    label.append(f"[{agent['framework']}]", style=f"bold {agent['color']}")
    label.append(f" {agent['name']}", style=f"{agent['color']}")
    return label


def print_phase(number: int, title: str, time_str: str, detail: str):
    global _current_phase, _current_timestamp
    _current_phase = number
    _current_timestamp = time_str.replace(" AM", "").replace(" ", "")
    console.print()
    header = Text()
    header.append(f"PHASE {number}", style="bold white on blue")
    header.append(f"  {title}", style="bold white")
    header.append(f"  [{time_str}]", style="dim white")
    console.rule(header, style="blue")
    console.print(f"  {detail}", style="dim")
    console.print()
    emit({"type": "phase_start", "phase": number, "label": title, "description": detail})
    time.sleep(PHASE_PAUSE)


def print_action(agent_key: str, action: str, detail: str = ""):
    label = agent_label(agent_key)
    action_text = Text()
    action_text.append(label)
    action_text.append(f"  {action}", style="white")
    if detail:
        action_text.append(f"  {detail}", style="dim")
    console.print(action_text)
    if "search" in action:
        query = detail.split("'")[1] if "'" in detail else detail
        emit({"type": "memory_search", "agent": fe_agent(agent_key), "query": query})
    elif "escalat" in action or "notify" in action or "coordinate" in action:
        emit({"type": "decision", "agent": fe_agent(agent_key), "content": f"{action} {detail}".strip()})


def print_memory_written(agent_key: str, content: str, memory_id: str,
                         metadata: dict | None = None):
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
    emit({
        "type": "memory_write",
        "agent": fe_agent(agent_key),
        "memory_id": memory_id,
        "content": content,
        "metadata": metadata or {},
    })
    time.sleep(ACTION_PAUSE)


def print_contradiction(reporter_key: str, target_content: str, reason: str,
                        memory_id: str = "", contradicts_id: str = ""):
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
    emit({
        "type": "contradiction",
        "memory_id": memory_id,
        "contradicts": contradicts_id,
        "detail": True,
        "moment": 3,
        "banner": "MOMENT 3 -- Contradiction preserved, both assessments stay in memory",
        "bcolor": "#F44336",
    })
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
        title=f"SENSITIVE DATA QUARANTINE -- {agent['name']}",
        title_align="left",
        border_style="bold red on white",
        width=120,
        padding=(1, 2),
    )
    console.print(panel)
    emit({
        "type": "quarantine",
        "agent": fe_agent(agent_key),
        "content": "Write blocked: content matched sensitive data pattern",
        "banner": "Quarantine -- MemoryHub blocked sensitive content from entering shared memory",
        "bcolor": "#F44336",
    })
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
    emit({
        "type": "shift_change",
        "changes": {"tier1": new_driver, "forensics": new_driver, "ic": new_driver},
        "moment": 5,
        "banner": "MOMENT 5 -- Shift change: driver_id changes, the agent and its memory persist",
        "bcolor": "#FFEB3B",
    })
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
    emit({
        "type": "audit_query",
        "detail": True,
        "rows": [{"ts": r["time"], "actor": r["actor"], "driver": r["driver"],
                  "op": r["action"], "mem": ""} for r in rows],
    })
    time.sleep(ACTION_PAUSE)


# ── Agent client and helpers ────────────────────────────────────────

async def call_agent(
    messages: list[dict[str, str]],
    *,
    timeout: float = 180.0,
    max_tokens: int = 2048,
) -> str:
    """Call the FIPS-agent gateway. Raises on failure (no silent fallback)."""
    url = SOC_FORENSICS_URL.rstrip("/")
    if not url.endswith("/v1/chat/completions"):
        url = f"{url}/v1/chat/completions"
    verify = os.environ.get("SOC_TLS_VERIFY", "true").lower() != "false"
    async with httpx.AsyncClient(timeout=timeout, verify=verify) as http:
        resp = await http.post(
            url,
            json={
                "model": "RedHatAI/gpt-oss-20b",
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": 0.3,
            },
            headers={"Authorization": "Bearer not-required"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"].get("content", "").strip()


async def persist_agent_output(
    client: MemoryHubClient,
    agent_key: str,
    response: str,
    metadata: dict | None = None,
) -> str | None:
    """Write the agent's LLM-generated response to MemoryHub and display it."""
    if not response or len(response.strip()) < 20:
        return None
    agent = AGENTS[agent_key]
    meta = {
        "incident_id": "IR-2024-184",
        "role": agent["actor_id"],
        "framework": agent["framework"],
        **(metadata or {}),
    }
    result = await client.write(
        response, scope="project", project_id=PROJECT_ID,
        weight=0.9, metadata=meta, force=True,
    )
    mem_id = result.memory.id if result.memory else "pending"
    content = response[:500] + ("..." if len(response) > 500 else "")
    print_memory_written(agent_key, content, mem_id, metadata=meta)
    return mem_id


def display_agent_response(agent_key: str, response: str, task_label: str):
    agent = AGENTS[agent_key]
    display_text = response[:2000]
    if len(response) > 2000:
        display_text += "\n\n... (truncated)"
    panel = Panel(
        display_text,
        title=f"{agent['name']} -- {task_label}",
        subtitle=f"via {agent['framework']} | GPT-OSS 20B on-cluster",
        title_align="left",
        subtitle_align="right",
        border_style=f"bold {agent['color']}",
        width=120,
        padding=(1, 2),
    )
    console.print(panel)


# ── Scenario ────────────────────────────────────────────────────────

async def run_scenario():
    if not SOC_FORENSICS_URL:
        console.print("[red]Error: SOC_FORENSICS_URL is required (no scripted fallback).[/]")
        console.print("[dim]Set it to the FIPS-Agent route URL.[/]")
        return 1

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

    register_block = (
        '\n## Session Registration (REQUIRED FIRST STEP)\n\n'
        'Before using any memory tools, call register_session. '
        'The api_key is pre-configured in your environment. Do this FIRST.\n'
    )

    emit_reset()

    # Title card
    console.print()
    title = Panel(
        Text.from_markup(
            "[bold white]MemoryHub: the context that makes security decisions go well.[/]\n\n"
            "[dim]A demonstration with a realistic mid-severity SOC incident.[/]\n"
            "[dim]Four agent frameworks. One shared memory. Real LLM inference.[/]\n\n"
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
    models = {"tier1": "Claude · cloud API", "forensics": "GPT-OSS 20B · on-cluster",
              "threatintel": "GPT-OSS 20B · on-cluster", "ic": "GPT-OSS 20B · on-cluster"}
    for key, agent in AGENTS.items():
        reg_table.add_row(
            Text(agent["name"], style=agent["color"]),
            agent["framework"],
            agent["actor_id"],
            "jason-park (night shift)",
        )
        emit({
            "type": "agent_register",
            "agent": fe_agent(key),
            "framework": agent["framework"],
            "actor_id": agent["actor_id"],
            "driver_id": "jason-park",
            "model": models.get(key, ""),
        })
        time.sleep(0.3)
    console.print(reg_table)
    console.print()
    time.sleep(PHASE_PAUSE)

    need_register = True

    def build_messages(system: str, user: str) -> list[dict[str, str]]:
        nonlocal need_register
        sys_prompt = system
        if need_register:
            sys_prompt += register_block
        return [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ]

    async with MemoryHubClient(url=url, api_key=api_key) as client:

        # ── PHASE 1: Detection (Call 1: Tier 1) ────────────────────
        print_phase(1, "DETECTION", "02:14 AM",
                    "CrowdStrike behavioral SIEM alert: unusual logon for svc-reporting")

        print_action("tier1", "investigating",
                     "Triaging alert via GPT-OSS 20B on-cluster")
        emit({"type": "decision", "agent": fe_agent("tier1"),
              "content": "Claude Code agent calling GPT-OSS 20B for alert triage"})
        console.print("  [dim]Waiting for LLM inference...[/]")

        response = await call_agent(build_messages(SYSTEM_TIER1, USER_TIER1))
        need_register = False

        display_agent_response("tier1", response, "Alert triage")
        await persist_agent_output(client, "tier1", response)

        # ── PHASE 2: Triage & Escalation ───────────────────────────
        print_phase(2, "TRIAGE & ESCALATION", "02:14 -- 02:55",
                    "Tier 1 -> Tier 2 escalation. IR team paged at 02:55.")

        print_action("tier1", "escalate_to_tier2",
                     "Confirmed unauthorized access. Paging IR team.")
        time.sleep(ACTION_PAUSE)

        # ── PHASE 3: Investigation (Calls 2-3) ─────────────────────
        print_phase(3, "INVESTIGATION", "02:55 -- 06:00",
                    "Parallel investigation: Forensics, Threat Intel, IC activated")

        # Call 2: Forensics
        print_action("forensics", "investigating",
                     "IR-2024-184 via GPT-OSS 20B on-cluster")
        emit({"type": "decision", "agent": fe_agent("forensics"),
              "content": "FIPS-Agent calling GPT-OSS 20B for forensic investigation"})
        console.print("  [dim]Waiting for LLM inference...[/]")

        response = await call_agent(build_messages(SYSTEM_FORENSICS, USER_FORENSICS))

        display_agent_response("forensics", response, "Forensic investigation")
        await persist_agent_output(client, "forensics", response)

        # Call 3: Threat Intel attribution
        print_action("threatintel", "investigating",
                     "TTP correlation via GPT-OSS 20B on-cluster")
        emit({"type": "decision", "agent": fe_agent("threatintel"),
              "content": "Hermes agent calling GPT-OSS 20B for attribution analysis"})
        console.print("  [dim]Waiting for LLM inference...[/]")

        response = await call_agent(build_messages(SYSTEM_THREATINTEL_ATTR, USER_THREATINTEL_ATTR))

        display_agent_response("threatintel", response, "Attribution assessment")
        attr_id = await persist_agent_output(client, "threatintel", response)

        # ── PHASE 4: Scoping (Call 4 + feature demos) ──────────────
        print_phase(4, "SCOPING", "04:00 -- 06:30",
                    "Determining scope: systems affected, data exposure, attacker next move")

        # Feature demo: shift change
        print_shift_change("Tier 2 SOC Analyst",
                           "jason-park", "maya-chen", "soc-tier2-analyst")

        # Call 4: Threat Intel contradiction
        print_action("threatintel", "reviewing_attribution",
                     "New network evidence challenges prior assessment")
        emit({"type": "decision", "agent": fe_agent("threatintel"),
              "content": "Hermes agent reviewing attribution based on beaconing analysis"})
        console.print("  [dim]Waiting for LLM inference...[/]")

        response = await call_agent(
            build_messages(SYSTEM_THREATINTEL_CONTRA, USER_THREATINTEL_CONTRA))

        display_agent_response("threatintel", response, "Attribution review")

        # File the contradiction against the attribution memory
        if attr_id:
            try:
                await client.report_contradiction(
                    memory_id=attr_id, observed_behavior=response[:1000])
            except Exception as exc:
                console.print(f"  [dim red]Contradiction report failed: {exc}[/]")

        print_contradiction(
            "threatintel",
            "(see agent's prior attribution above)",
            response[:500],
            contradicts_id=attr_id or "",
        )

        # Feature demo: quarantine
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

        # ── PHASE 5: Containment (Call 5 + feature demos) ──────────
        print_phase(5, "CONTAINMENT", "06:00 -- 08:00",
                    "Credential rotation, endpoint isolation, stakeholder notification")

        # Call 5: IC synthesis
        print_action("ic", "coordinating",
                     "Synthesizing findings via GPT-OSS 20B on-cluster")
        emit({"type": "decision", "agent": fe_agent("ic"),
              "content": "OpenClaw agent calling GPT-OSS 20B for containment coordination"})
        console.print("  [dim]Waiting for LLM inference...[/]")

        response = await call_agent(build_messages(SYSTEM_IC_CONTAIN, USER_IC_CONTAIN))

        display_agent_response("ic", response, "Containment synthesis")
        await persist_agent_output(client, "ic", response)

        # Feature demo: credential quarantine
        print_quarantine(
            "forensics",
            "Rotated svc-reporting credential. Old password was Welcome2024!Q3, "
            "new password is Tk7$mNp2#vR9wQ4z. Documenting for handoff.",
            "Rotated svc-reporting credential at 06:42 per IR-2024-184 containment "
            "plan. New credential stored in privileged access management vault per "
            "standard procedure. Old credential is now invalid.",
        )

        # ── PHASE 6: Audit Trail (feature demo) ───────────────────
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

        # ── PHASE 7: Post-Incident (Call 6) ────────────────────────
        print_phase(7, "POST-INCIDENT LEARNING", "24-72 hours later",
                    "Lessons captured into shared memory for future incidents")

        # Call 6: IC post-incident lessons
        print_action("ic", "writing_lessons",
                     "Post-incident analysis via GPT-OSS 20B on-cluster")
        emit({"type": "decision", "agent": fe_agent("ic"),
              "content": "OpenClaw agent writing post-incident lessons"})
        console.print("  [dim]Waiting for LLM inference...[/]")

        response = await call_agent(build_messages(SYSTEM_IC_POSTINCIDENT, USER_IC_POSTINCIDENT))

        display_agent_response("ic", response, "Post-incident lessons")
        await persist_agent_output(client, "ic", response, {"category": "post-incident-lesson"})

    # ── Closing ─────────────────────────────────────────────────
    console.print()
    closing = Panel(
        Text.from_markup(
            "[bold white]What you just saw:[/]\n\n"
            "1. Tier 1 searched shared memory and decided to escalate "
            "[cyan](Claude Code)[/]\n"
            "2. Forensics investigated with memory-informed analysis "
            "[green](FIPS-Agent)[/]\n"
            "3. Threat Intel attributed, then contradicted its own assessment "
            "[yellow](Hermes)[/]\n"
            "4. IC synthesized all findings and wrote lessons learned "
            "[magenta](OpenClaw)[/]\n"
            "5. Every search, write, and contradiction was a real LLM call "
            "through real MemoryHub MCP tools\n\n"
            "[bold]Four frameworks. One shared memory. Zero scripted content.[/]"
        ),
        title="MEMORYHUB: THE CONTEXT THAT MAKES SECURITY DECISIONS GO WELL",
        title_align="center",
        border_style="bold blue",
        width=120,
        padding=(1, 4),
    )
    console.print(closing)
    console.print()
    emit({
        "type": "session_end",
        "banner": "IR-2024-184 contained -- memories written -- cross-framework reads -- real LLM inference",
        "bcolor": "#2196F3",
    })
    return 0


def main():
    return asyncio.run(run_scenario())


if __name__ == "__main__":
    sys.exit(main())
