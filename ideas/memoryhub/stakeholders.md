# Stakeholders

## Primary users

The most direct users are AI agents running on OpenShift AI. They consume and produce memories via MCP. MemoryHub is infrastructure they interact with on every turn — reading relevant memories, writing new ones, searching for context. The agent experience needs to be fast, reliable, and simple. If the MCP interface is clunky or slow, agents will work around it rather than through it.

Developers and data scientists using AI agents are the humans who benefit most immediately. Their agents remember preferences, project context, organizational standards, and accumulated knowledge. The difference between an agent that starts cold every time and one that knows your work style, your team's conventions, and your organization's policies is the difference between a tool and a colleague.

New employees and new agent deployments are a special case worth calling out. They benefit disproportionately from organizational memory bootstrapping. Instead of spending weeks teaching an agent how your team works, the agent inherits that knowledge from day one.

## Secondary stakeholders

Platform administrators manage memory tiers, governance policies, and cluster resources via CRDs. They care about operational simplicity, resource utilization, and policy enforcement. If MemoryHub is operationally expensive or hard to configure, they'll push back on adoption.

Security and compliance teams use forensics, audit trails, and secrets scanning. They need to be able to answer questions like "what did this agent know when it took that action?" and "are any agent memories leaking credentials?" These teams are often the gatekeepers for enterprise adoption — if they can't audit it, it doesn't ship.

Organization leadership benefits from collective learning and policy enforcement in a more abstract sense. When organizational policies are enforced through agent memory rather than just documentation, compliance improves. When agents share knowledge, productivity increases across the board.

## Key relationship

The RHOAI engineering team is the most important external stakeholder. The user meets with them regularly and would pitch MemoryHub once it's demonstrably working. They're the gatekeepers for upstream contribution. Their buy-in determines whether this becomes part of OpenShift AI or remains a standalone component. Everything we build should be done with the assumption that they'll eventually review the code, the architecture, and the operational model.
