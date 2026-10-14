---
description: Use this skill for ALL issue operations. Never create issues manually without using the skill -- it enforces our conventions.
---

# Issue Tracker

You are managing issues for the MemoryHub project. This command enforces the project's issue conventions from CLAUDE.md:

- Every issue references a design document
- Every issue starts in Backlog
- Issues flow: Backlog → In Progress → Done

## Project Details

- **GitHub repo**: `redhat-ai-americas/memory-hub`
- **GitHub Project**: MemoryHub (number 1, ID `PVT_kwDODErzuc4BUFze`), owned by the `redhat-ai-americas` org
- **Status field ID**: `PVTSSF_lADODErzuc4BUFzezhBQT0U`
- **Status options**:
  - Backlog: `5af61e02`
  - In Progress: `97ae4b78`
  - Done: `61db5447`

## Operations

Parse the user's request to determine which operation they want. The argument to this command is a free-text description of what they want to do.

### Create Issue

When the user wants to create a new issue:

1. **Require a design doc reference.** The issue body must reference a document in `docs/`. If the user hasn't mentioned one, check if a relevant design doc exists. If none exists, ask the user whether to create a skeleton design doc first or proceed without one (noting this breaks convention).

2. **Determine labels.** Discover available labels with `gh label list --repo redhat-ai-americas/memory-hub`. Common ones:
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

   Add the issue. `--format json` returns the new item's ID, so capture it here
   rather than searching for it afterwards:
   ```bash
   ITEM_ID=$(gh project item-add 1 --owner redhat-ai-americas \
     --url <issue-url> --format json --jq '.id')
   ```

   Set the status:
   ```bash
   gh project item-edit --project-id PVT_kwDODErzuc4BUFze \
     --id "$ITEM_ID" \
     --field-id PVTSSF_lADODErzuc4BUFzezhBQT0U \
     --single-select-option-id 5af61e02
   ```

5. **Report** the issue URL and confirm it's in Backlog.

### Finding the item ID of an issue already on the board

Needed by Move and Close. Query the issue directly rather than listing the
board and searching it:

```bash
RESP=$(gh api graphql -f query='
query($owner:String!, $repo:String!, $num:Int!) {
  repository(owner:$owner, name:$repo) {
    issue(number:$num) {
      projectItems(first:10) {
        nodes { id project { number } }
      }
    }
  }
}' -f owner=redhat-ai-americas -f repo=memory-hub -F num=<issue-number>)

jq -e '.errors' >/dev/null 2>&1 <<<"$RESP" \
  && { jq -r '"GraphQL error: " + .errors[0].message' <<<"$RESP" >&2; exit 1; }

ITEM_ID=$(jq -r '.data.repository.issue.projectItems.nodes[]
                 | select(.project.number == 1) | .id' <<<"$RESP")
case "$ITEM_ID" in
  PVTI_*) ;;
  "")     echo "issue is not on the board; add it first" >&2; exit 1 ;;
  *)      echo "unexpected item id: $ITEM_ID" >&2; exit 1 ;;
esac
```

Check the errors explicitly. With `--jq`, `gh` prints the GraphQL error
body to stdout and still exits 0, so a rate-limited query yields a JSON
error blob that a bare non-empty test would pass to `item-edit` as if it
were an item ID.

Do not use `gh project item-list` for this. It defaults to 30 items and
returns them oldest-first, so a recently created issue is never in the
default page. Raising `--limit` past the board size works but pages the
entire board on every lookup, which trips GitHub's secondary rate limit
during a run of several issue operations. The query above is one request
and cannot truncate.

### Move Issue

When the user wants to change an issue's status (e.g., "move #19 to In Progress"):

1. Find the project item ID with the GraphQL query above.
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

1. List project items, optionally filtered by status. This is the one case that
   genuinely needs the whole board, so `--limit` is required here; the default of
   30 would silently show a fraction of it:
   ```bash
   gh project item-list 1 --owner redhat-ai-americas --limit 1000 --format json
   ```
   Check `totalCount` against the number of items returned and raise `--limit` if
   they differ. Avoid running this in a loop, since paging the full board
   repeatedly trips GitHub's secondary rate limit.
2. Format as a readable table with: number, title, status, labels.
3. If the user asked for a specific status (e.g., "what's in backlog?"), filter the output accordingly.

### Update Issue

When the user wants to modify an existing issue's title, body, or labels:

1. Use `gh issue edit <number>` with the appropriate flags.
2. Report what changed.

## Important Guidelines

- **Always add to the project board.** An issue not on the board is invisible to our workflow.
- **Always start in Backlog.** Never create an issue directly in "In Progress" unless the user explicitly asks.
- **Issue authorship.** Issues show the human author (rdwj) as the submitter. Do NOT add AI attribution — no "Assisted-by" lines, no "Generated with Claude" footers. This is intentional per CLAUDE.md.
- **Design doc enforcement.** This is the key convention. Push back (politely) if there's no design doc, but don't block the user if they insist.
- **Subsystem labels.** If the issue clearly belongs to a subsystem, apply the label. If it spans multiple, pick the primary one or ask.
- **Done = Closed.** Moving to Done and closing the issue are a single logical operation. Always do both.
