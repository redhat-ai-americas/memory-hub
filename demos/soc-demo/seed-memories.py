#!/usr/bin/env python3
"""Seed MemoryHub with pre-incident memories for the SOC demo.

Creates a 'midwest-financial-soc' project and populates it with the six
memory touchpoints from demos/scenarios/cybersecurity/threat-hunting-incident-response.md.

Usage:
    cd memory-hub
    python demos/soc-demo/seed-memories.py

Requires MEMORYHUB_URL and MEMORYHUB_API_KEY env vars, or a
~/.config/memoryhub/credentials file with a [mcp-rhoai] section.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../sdk/src"))

from memoryhub import MemoryHubClient

PROJECT_ID = "midwest-financial-soc"

MEMORIES = [
    {
        "label": "IR-2024-117 cross-incident pattern",
        "content": (
            "IR-2024-117. Started with a similar alert pattern: svc-reporting "
            "account used from a non-standard workstation, followed by file server "
            "enumeration. Initial hypothesis was credential reuse from a dev "
            "environment. Real cause: phishing email 9 days prior, attacker had "
            "been enumerating since. Lesson: don't dismiss off-hours service "
            "account anomalies even if a benign explanation seems plausible. "
            "Spend the 20 minutes verifying."
        ),
        "scope": "project",
        "weight": 0.95,
        "metadata": {
            "incident_id": "IR-2024-117",
            "author": "maya-chen",
            "role": "tier2-analyst",
        },
    },
    {
        "label": "Tier 1 team practice: off-hours service account heuristic",
        "content": (
            "Tier 1 team practice: alerts on service accounts during business "
            "hours are usually maintenance and rarely worth escalating. Alerts "
            "on service accounts after 8pm are 80% worth escalating per our "
            "own tracking from Q1 and Q2 2024. Not a formal SIEM rule because "
            "it's heuristic, but it's how we've been operating."
        ),
        "scope": "project",
        "weight": 0.8,
        "content_type": "behavioral",
        "metadata": {
            "category": "team-heuristic",
            "confidence": "empirical-tracking",
        },
    },
    {
        "label": "Breakglass rotation operational lesson (IR-2024-103)",
        "content": (
            "Last time we rotated the breakglass credential during an active "
            "incident (IR-2024-103), the rotation broke our Veeam backup "
            "service for 6 hours because the backup service uses the breakglass "
            "credential for restore operations and we hadn't documented that "
            "dependency. We had a separate near-miss when network monitoring "
            "alerted but ops didn't know it was related to our incident "
            "response. Operational lesson: coordinate breakglass rotation with "
            "backup admin BEFORE execution, and notify NOC of expected service "
            "impact during IR. Standard practice now."
        ),
        "scope": "project",
        "weight": 0.95,
        "metadata": {
            "incident_id": "IR-2024-103",
            "author": "marcus-wong",
            "role": "ir-lead",
            "category": "operational-lesson",
        },
    },
    {
        "label": "CISO notification preference (Pat Lindstrom)",
        "content": (
            "MidWest Financial CISO Pat Lindstrom prefers notification of any "
            "potential PII exposure within 2 hours, even if uncertain. "
            "Background: her previous role at a regional credit union had a "
            "delayed-notification incident in 2022 that resulted in regulatory "
            "action. She has personally said in two incident reviews that "
            "'erring on the side of early notification is always the right "
            "call.' Default to notifying her early during any potential PII "
            "incident."
        ),
        "scope": "project",
        "weight": 0.85,
        "metadata": {
            "category": "stakeholder-preference",
            "stakeholder_role": "ciso",
        },
    },
    {
        "label": "ai.exe false positive (Forensics agent operational memory)",
        "content": (
            "When investigating outlook.exe child processes during a "
            "phishing-related incident, ignore ai.exe. This is the Microsoft "
            "365 Copilot integration. It triggers suspicious-spawn rules "
            "because the parent-child relationship looks unusual, but it's "
            "always benign in our environment. We re-derived this three times "
            "across IR-2024-091, IR-2024-094, and IR-2024-105 before writing "
            "it down. Forensics agent should filter ai.exe from "
            "outlook.exe-spawned-process queries during phishing investigations "
            "by default."
        ),
        "scope": "project",
        "weight": 0.9,
        "metadata": {
            "category": "agent-operational",
            "agent_role": "forensics",
            "incidents": ["IR-2024-091", "IR-2024-094", "IR-2024-105"],
        },
    },
    {
        "label": "Staging path patterns from IR-2024-117",
        "content": (
            "When the IR-2024-117 attacker had access to file servers, they "
            "staged data in \\\\fileserver\\admin$\\TEMP\\reports2024\\. The "
            "directory name was deliberately chosen to look like a legitimate "
            "reporting directory. Other staging paths to check based on "
            "attacker preferences from this campaign: "
            "\\\\<server>\\admin$\\PerfLogs\\Admin\\, "
            "\\\\<server>\\Public\\Documents\\templates\\, "
            "\\\\<server>\\IT\\backup_temp\\. "
            "Forensics agent should query these paths as part of standard "
            "staging-search during incidents matching this campaign profile."
        ),
        "scope": "project",
        "weight": 0.85,
        "metadata": {
            "incident_id": "IR-2024-117",
            "category": "technique-pattern",
            "mitre_technique": "T1074-Data-Staging",
        },
    },
]


async def main():
    url = os.environ.get("MEMORYHUB_URL")
    api_key = os.environ.get("MEMORYHUB_API_KEY")

    if not url or not api_key:
        try:
            import configparser

            config = configparser.ConfigParser()
            config.read(os.path.expanduser("~/.config/memoryhub/credentials"))
            section = os.environ.get("MEMORYHUB_CONTEXT", "mcp-rhoai")
            if section not in config:
                section = "default"
            url = url or config.get(section, "url", fallback=None)
            api_key = api_key or config.get(section, "api_key", fallback=None)
        except Exception:
            pass

    if not url or not api_key:
        print("Error: Set MEMORYHUB_URL and MEMORYHUB_API_KEY, or configure "
              "~/.config/memoryhub/credentials with a [mcp-rhoai] section.")
        sys.exit(1)

    print(f"Connecting to {url}")

    async with MemoryHubClient(url=url, api_key=api_key) as client:
        # Create the project (idempotent -- ignores if exists)
        try:
            result = await client.create_project(
                PROJECT_ID,
                description="MidWest Financial Services Group SOC team shared memory",
            )
            print(f"Created project: {PROJECT_ID}")
        except Exception as e:
            if "already exists" in str(e).lower():
                print(f"Project already exists: {PROJECT_ID}")
            else:
                raise

        # Write each memory
        for i, mem in enumerate(MEMORIES, 1):
            kwargs = {
                "content": mem["content"],
                "scope": mem["scope"],
                "weight": mem["weight"],
                "project_id": PROJECT_ID,
                "metadata": mem.get("metadata"),
                "force": True,
            }
            if "content_type" in mem:
                kwargs["content_type"] = mem["content_type"]

            result = await client.write(**kwargs)

            if result.curation and result.curation.gated:
                print(f"  [{i}/6] GATED (duplicate): {mem['label']}")
            elif result.memory:
                print(f"  [{i}/6] Written: {mem['label']} -> {result.memory.id}")
            else:
                print(f"  [{i}/6] Written: {mem['label']}")

        # Verify by searching
        print("\nVerification search: 'service account anomaly off-hours'")
        search_result = await client.search(
            "service account anomaly off-hours",
            scope="project",
            project_id=PROJECT_ID,
        )
        print(f"  Found {len(search_result.results)} memories")
        for r in search_result.results[:3]:
            preview = r.content[:80] + "..." if len(r.content) > 80 else r.content
            print(f"  - [{r.relevance_score:.2f}] {preview}")

    print("\nDone. SOC demo memories seeded.")


if __name__ == "__main__":
    asyncio.run(main())
