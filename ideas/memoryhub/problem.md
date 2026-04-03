# The Problem Space

Agents today are amnesiacs. Every new conversation, every new agent deployment, every new user onboarding — the agent starts cold. There's no institutional knowledge, no transfer learning, no organizational memory. And the few memory solutions that exist are siloed, ungoverned, and invisible to the enterprise.

## Agents forget

Even with memory features in tools like Claude Code, memories are local, siloed, and non-transferable. If you tell an agent "never commit without scanning for secrets," that knowledge lives and dies with that single agent instance. There's no way for that preference to propagate to other agents, other users, or become organizational policy. Switch tools, switch machines, onboard a new team member — all that accumulated knowledge evaporates.

## No organizational learning

When hundreds of agents across an enterprise learn the same lessons independently, that's massive waste. If 50 engineers all teach their agents the same thing about how the company handles deployments, nobody benefits from that collective learning. There's no mechanism for pattern detection, memory promotion, or institutional knowledge building. Each agent is an island.

## Enterprise blind spots

Right now, there's no way to audit what an agent "knew" when it took an action. Was a data leak the user's intent or the agent's mistake? What memories influenced a decision? Did an agent accidentally store an API key in its memory and leak it to a hosted API? These questions are unanswerable today. For regulated industries, this is a showstopper. The EU AI Act enforcement starts August 2026, and organizations will need to demonstrate transparency in how their AI systems make decisions.

## Memory doesn't scale

As agents accumulate memories, injection into prompts becomes wasteful. You either inject everything (token waste, context pollution) or inject nothing from long-term storage (amnesia). There's no intelligent retrieval that surfaces only what's relevant, at the right level of detail, at the right time. The "just stuff it in the system prompt" approach has a ceiling, and we're hitting it.

## No transfer learning

Stand up a new agent? It starts from zero. Onboard a new employee? Their agent knows nothing about how the organization works. There's no bootstrapping from organizational knowledge, role-based defaults, or collective experience. Every agent goes through the same painful ramp-up that the humans they serve went through — except unlike humans, agents don't even have hallway conversations to accelerate it.
