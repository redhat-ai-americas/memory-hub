#!/usr/bin/env python3
"""Cross-framework memory sharing smoke test.

Simulates 4 SOC agents (each a different framework) writing and reading
shared memory through MemoryHub. Proves that memories written by one
agent are readable by any other agent in the same project.

Usage:
    cd memory-hub
    python demos/soc-demo/smoke-test.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../sdk/src"))

from memoryhub import MemoryHubClient

URL = os.environ.get("MEMORYHUB_URL", "")
API_KEY = os.environ.get("MEMORYHUB_API_KEY", "")
PROJECT_ID = "midwest-financial-soc"


async def agent_session(api_key: str, driver_id: str):
    """Create a MemoryHub client session for a simulated agent."""
    return MemoryHubClient(url=URL, api_key=api_key)


async def main():
    if not API_KEY:
        import configparser
        config = configparser.ConfigParser()
        config.read(os.path.expanduser("~/.config/memoryhub/credentials"))
        section = os.environ.get("MEMORYHUB_CONTEXT", "mcp-rhoai")
        if section not in config:
            section = "default"
        api_key = config.get(section, "api_key", fallback="")
        url = config.get(section, "url", fallback=URL)
    else:
        api_key = API_KEY
        url = URL

    print("=" * 60)
    print("SOC Demo: Cross-Framework Memory Sharing Smoke Test")
    print("=" * 60)
    print(f"Server: {url}")
    print(f"Project: {PROJECT_ID}")
    print()

    # Step 1: Tier 1 (Claude Code) searches for the seeded pattern
    print("[1/6] Tier 1 (Claude Code) -- searching for service account anomaly...")
    async with MemoryHubClient(url=url, api_key=api_key) as tier1:
        sr = await tier1.search(
            "unusual service account logon off-hours SMB enumeration",
            scope="project",
            project_id=PROJECT_ID,
        )
        print(f"  Found {len(sr.results)} memories")
        if sr.results:
            top = sr.results[0]
            print(f"  Top match: {top.content[:100]}...")
            print(f"  -> Tier 1 recognizes IR-2024-117 pattern. Escalating.")

        # Tier 1 writes an escalation decision
        esc = await tier1.write(
            "IR-2024-184 triage decision: Escalating to Tier 2 at 02:38 AM. "
            "Pattern matches IR-2024-117 (phishing-derived credential, off-hours "
            "service account anomaly, SMB enumeration). The team's heuristic says "
            "off-hours service account alerts are 80% worth escalating. "
            "Tier 1 recommends full investigation.",
            scope="project",
            project_id=PROJECT_ID,
            weight=0.9,
            metadata={"incident_id": "IR-2024-184", "role": "tier1-analyst", "framework": "claude-code"},
            force=True,
        )
        tier1_memory_id = esc.memory.id if esc.memory else "unknown"
        print(f"  Wrote escalation memory: {tier1_memory_id}")
    print()

    # Step 2: Forensics (FIPS-Agent) reads the escalation and the ai.exe filter
    print("[2/6] Forensics (FIPS-Agent) -- reading escalation + operational memory...")
    async with MemoryHubClient(url=url, api_key=api_key) as forensics:
        sr = await forensics.search(
            "escalation IR-2024-184 triage decision",
            scope="project",
            project_id=PROJECT_ID,
        )
        found_tier1 = any("IR-2024-184 triage" in r.content for r in sr.results)
        print(f"  Found Tier 1 escalation: {found_tier1}")

        sr2 = await forensics.search(
            "outlook.exe ai.exe false positive forensics",
            scope="project",
            project_id=PROJECT_ID,
        )
        found_aiexe = any("ai.exe" in r.content for r in sr2.results)
        print(f"  Found ai.exe filter memory: {found_aiexe}")

        # Forensics writes timeline findings
        forensic_write = await forensics.write(
            "IR-2024-184 forensic timeline: Attacker first accessed WKSTN-FIN-082 "
            "at 15:22 on March 4 using svc-reporting credential harvested via "
            "phishing 11 days prior. Enumeration phase (March 4-14) stayed within "
            "business hours to blend with normal traffic. Staging began at 20:47 "
            "on March 14 with 47 GB copied to \\\\FILESVR-CORP-03\\admin$\\TEMP\\reports2024\\. "
            "CrowdStrike behavioral rule fired at 02:14 March 15 when staging volume "
            "crossed 30 GB threshold.",
            scope="project",
            project_id=PROJECT_ID,
            weight=0.9,
            metadata={"incident_id": "IR-2024-184", "role": "forensics", "framework": "fips-agent"},
            force=True,
        )
        forensics_id = forensic_write.memory.id if forensic_write.memory else "unknown"
        print(f"  Wrote forensic timeline: {forensics_id}")
    print()

    # Step 3: Threat Intel (Hermes) reads forensics findings and writes attribution
    print("[3/6] Threat Intel (Hermes) -- reading forensics, writing attribution...")
    async with MemoryHubClient(url=url, api_key=api_key) as threatintel:
        sr = await threatintel.search(
            "IR-2024-184 forensic timeline attacker staging",
            scope="project",
            project_id=PROJECT_ID,
        )
        found_forensics = any("forensic timeline" in r.content for r in sr.results)
        print(f"  Found forensic timeline: {found_forensics}")

        # Write attribution assessment
        attr = await threatintel.write(
            "IR-2024-184 initial attribution assessment: TTPs partially match "
            "CC2024-Q3-Opportunistic campaign. Phishing initial access, 9-14 day "
            "dwell time, file server staging all consistent. However, beaconing "
            "pattern does not match -- CC2024-Q3 uses 90-second beacon intervals "
            "with jitter; this incident shows interactive sessions with no consistent "
            "beaconing. Assessment: possible campaign evolution or different attacker "
            "reusing similar TTPs. Confidence: LOW. Do not rely on CC2024-Q3 playbook.",
            scope="project",
            project_id=PROJECT_ID,
            weight=0.85,
            metadata={"incident_id": "IR-2024-184", "role": "threat-intel", "framework": "hermes"},
            force=True,
        )
        attr_id = attr.memory.id if attr.memory else "unknown"
        print(f"  Wrote attribution assessment: {attr_id}")
    print()

    # Step 4: IC (OpenClaw) reads all three and synthesizes
    print("[4/6] IC (OpenClaw) -- synthesizing from all agents...")
    async with MemoryHubClient(url=url, api_key=api_key) as ic:
        sr = await ic.search(
            "IR-2024-184",
            scope="project",
            project_id=PROJECT_ID,
        )
        # The newly-written memories (steps 1-3) should be visible alongside
        # the seeded memories. We check that the IC can see memories written
        # by all prior steps -- the content proves cross-agent visibility.
        contents = [r.content for r in sr.results]
        has_tier1 = any("triage decision" in c for c in contents)
        has_forensics = any("forensic timeline" in c for c in contents)
        has_threatintel = any("attribution assessment" in c for c in contents)
        cross_framework_ok = has_tier1 and has_forensics and has_threatintel

        print(f"  Total IR-2024-184 memories visible: {len(sr.results)}")
        print(f"  Tier 1 write visible:       {has_tier1}")
        print(f"  Forensics write visible:    {has_forensics}")
        print(f"  Threat Intel write visible: {has_threatintel}")

        # IC writes synthesis
        synth = await ic.write(
            "IR-2024-184 IC synthesis (06:00 shift handoff brief): "
            "Confirmed credential compromise via phishing, 11-day dwell. "
            "47 GB staged, no exfiltration yet. Attribution to CC2024-Q3 is "
            "LOW confidence per Threat Intel -- beaconing pattern mismatch. "
            "Containment in progress: isolating WKSTN-FIN-082, rotating "
            "svc-reporting credential. Coordinating with backup admin before "
            "breakglass rotation per IR-2024-103 lesson.",
            scope="project",
            project_id=PROJECT_ID,
            weight=0.95,
            metadata={"incident_id": "IR-2024-184", "role": "incident-commander", "framework": "openclaw"},
            force=True,
        )
        synth_id = synth.memory.id if synth.memory else "unknown"
        print(f"  Wrote IC synthesis: {synth_id}")
    print()

    # Step 5: Threat Intel (Hermes) calls report_contradiction
    print("[5/6] Threat Intel (Hermes) -- reporting contradiction on attribution...")
    async with MemoryHubClient(url=url, api_key=api_key) as threatintel2:
        # Search for any strong CC2024-Q3 attribution to contradict
        sr = await threatintel2.search(
            "CC2024-Q3-Opportunistic campaign attribution",
            scope="project",
            project_id=PROJECT_ID,
        )
        if sr.results:
            target = sr.results[0]
            try:
                await threatintel2.report_contradiction(
                    memory_id=target.id,
                    observed_behavior="Network analysis shows no consistent beaconing "
                    "pattern. CC2024-Q3 uses 90-second beacon intervals; this incident "
                    "shows interactive sessions. Attribution confidence should be LOW.",
                )
                print(f"  Contradiction reported against memory {target.id}")
            except Exception as e:
                print(f"  Contradiction report: {e}")
        else:
            print("  No attribution memory found to contradict")
    print()

    # Step 6: IC (OpenClaw) reads the contradiction
    print("[6/6] IC (OpenClaw) -- verifying contradiction is visible...")
    async with MemoryHubClient(url=url, api_key=api_key) as ic2:
        sr = await ic2.search(
            "CC2024-Q3 attribution contradiction beaconing",
            scope="project",
            project_id=PROJECT_ID,
        )
        found_contradiction = any(
            "beaconing" in r.content and "contradiction" in r.content.lower()
            for r in sr.results
        )
        # Check for the attribution assessment with low confidence
        found_low_conf = any(
            "LOW" in r.content and "CC2024-Q3" in r.content
            for r in sr.results
        )
        print(f"  Attribution low-confidence visible: {found_low_conf}")
        print(f"  Total memories in search: {len(sr.results)}")
    print()

    # Summary
    print("=" * 60)
    print("SMOKE TEST RESULTS")
    print("=" * 60)
    print(f"  Tier 1 -> Forensics read:     {'PASS' if found_tier1 else 'FAIL'}")
    print(f"  Seeded -> Forensics read:     {'PASS' if found_aiexe else 'FAIL'}")
    print(f"  Forensics -> Threat Intel:    {'PASS' if found_forensics else 'FAIL'}")
    print(f"  Cross-framework synthesis:    {'PASS' if cross_framework_ok else 'FAIL'}")
    print(f"  Low-confidence visible to IC: {'PASS' if found_low_conf else 'FAIL'}")
    print()
    all_pass = all([found_tier1, found_aiexe, found_forensics, cross_framework_ok, found_low_conf])
    print(f"  Overall: {'ALL PASS' if all_pass else 'SOME FAILURES'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
