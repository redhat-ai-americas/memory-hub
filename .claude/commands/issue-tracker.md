---
description: Use this skill for ALL issue operations. Never create issues manually without using the skill -- it enforces our conventions.
---

# Issue Tracker

You are managing issues for the MemoryHub project. This command enforces the project's issue conventions from CLAUDE.md:

- Every issue references a design document
- Every issue starts in Backlog
- Issues flow: Backlog → In Progress → Done

## Project Details

- **GitHub repo**: `rdwj/memory-hub`
- **GitHub Project**: MemoryHub (number 7, ID `PVT_kwHOBewreM4BTouh`)
- **Status field ID**: `PVTSSF_lAHOBewreM4BTouhzhA2YbQ`
- **Status options**:
  - Backlog: `a4665e16`
  - In Progress: `1dadea2f`
  - Done: `39420b68`

## Operations

Parse the user's request to determine which operation they want. The argument to this command is a free-text description of what they want to do.

### Create Issue

When the user wants to create a new issue:

1. **Require a design doc reference.** The issue body must reference a document in `docs/`. If the user hasn't mentioned one, check if a relevant design doc exists. If none exists, ask the user whether to create a skeleton design doc first or proceed without one (noting this breaks convention).

2. **Determine labels.** Discover available labels with `gh label list --repo rdwj/memory-hub`. Common ones:
   - Type labels: `type:feature`, `type:bug`, `type:design`
   - Subsystem labels: `subsystem:memory-tree`, `subsystem:curator`, `subsystem:storage`, `subsystem:governance`, `subsystem:mcp-server`, `subsystem:observability`, `subsystem:operator`, `subsystem:org-ingestion`
   - Always apply one `type:` label and one `subsystem:` label if applicable.

3. **Create the issue** using a heredoc for the body to handle multi-line content safely:
   ```bash
   gh issue create --title "<title>" --label "<label1>,<label2>" --body "$(cat <<'EOF'
   ## Summary
   <1-3 sentences describing the work>

   ## Design reference
   - `docs/<relevant-doc>.md`

   ## Scope
   <Details of what needs to be done>

   ## Dependencies
   <Other issues or prerequisites, if any>
   EOF
   )"
   ```
   - Title: concise, imperative mood (e.g., "Add memory browser panel to RHOAI dashboard")

4. **Add to project board and set status to Backlog.**

   Add the issue:
   ```bash
   gh project item-add 7 --owner rdwj --url <issue-url>
   ```

   Find the project item ID by matching on the issue number (more reliable than title matching):
   ```bash
   gh project item-list 7 --owner rdwj --format json | python3 -c "
   import json, sys
   data = json.load(sys.stdin)
   for item in data.get('items', []):
       url = item.get('content', {}).get('url', '')
       if url.endswith('/<issue-number>'):
           print(item['id'])
           break
   else:
       print('ERROR: item not found', file=sys.stderr)
       sys.exit(1)
   "
   ```

   Set the status:
   ```bash
   gh project item-edit --project-id PVT_kwHOBewreM4BTouh \
     --id <item-id> \
     --field-id PVTSSF_lAHOBewreM4BTouhzhA2YbQ \
     --single-select-option-id a4665e16
   ```

5. **Report** the issue URL and confirm it's in Backlog.

### Move Issue

When the user wants to change an issue's status (e.g., "move #19 to In Progress"):

1. Find the project item ID using the issue number lookup pattern above.
2. Set the status using the option IDs from Project Details.
3. If moving to **Done**, also close the GitHub issue:
   ```bash
   gh issue close <number>
   ```
4. Confirm the change.

### Close Issue

When the user wants to close an issue:

1. Close the GitHub issue:
   ```bash
   gh issue close <number>
   ```
2. Move the project board item to Done (if not already there).
3. Confirm both actions.

Note: Moving to Done and closing the issue should always happen together. A closed issue should be in Done; an issue in Done should be closed.

### View Issue

When the user wants to see a specific issue's details:

```bash
gh issue view <number>
```

### List Issues

When the user wants to see issues (e.g., "what's in backlog?", "show me all issues"):

1. List project items, optionally filtered by status:
   ```bash
   gh project item-list 7 --owner rdwj --format json
   ```
2. Format as a readable table with: number, title, status, labels.
3. If the user asked for a specific status (e.g., "what's in backlog?"), filter the output accordingly.

### Update Issue

When the user wants to modify an existing issue's title, body, or labels:

1. Use `gh issue edit <number>` with the appropriate flags.
2. Report what changed.

## Important Guidelines

- **Always add to the project board.** An issue not on the board is invisible to our workflow.
- **Always start in Backlog.** Never create an issue directly in "In Progress" unless the user explicitly asks.
- **Issue authorship.** Issues show rdwj as the submitter. Do NOT add AI attribution — no "Assisted-by" lines, no "Generated with Claude" footers. This is intentional per CLAUDE.md.
- **Design doc enforcement.** This is the key convention. Push back (politely) if there's no design doc, but don't block the user if they insist.
- **Subsystem labels.** If the issue clearly belongs to a subsystem, apply the label. If it spans multiple, pick the primary one or ask.
- **Done = Closed.** Moving to Done and closing the issue are a single logical operation. Always do both.
