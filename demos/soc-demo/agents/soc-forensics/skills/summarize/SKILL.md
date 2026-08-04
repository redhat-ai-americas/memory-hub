---
name: summarize
description: Summarize documents and research findings into concise briefs
version: "1.0"
triggers:
  - summarize
  - brief
  - tldr
dependencies: []
parameters:
  max_length:
    type: string
    default: "300 words"
    description: Target length for the summary
  style:
    type: string
    default: executive
    description: "Summary style: executive, technical, or bullet-points"
---

# Summarize Skill

When activated, produce a concise summary of the provided content.

## Behavior

1. Read the full content before summarizing. Do not summarize incrementally.
2. Identify the key claims, findings, or decisions in the material.
3. Preserve the original meaning — do not inject opinions or analysis
   unless specifically asked.
4. Match the requested style:
   - **executive**: 2-3 paragraph narrative for decision-makers
   - **technical**: structured with headings, preserving technical detail
   - **bullet-points**: flat list of key points, one sentence each

## Output Format

Return the summary as Markdown. Begin with a one-sentence "bottom line"
before the detailed summary.

## Example

Given a 2000-word research report on container security, an executive
summary at 300 words would:

- Open with the single most important finding
- Cover the top 3-4 recommendations
- Note any critical risks or blockers
- Close with a recommended next step
