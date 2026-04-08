# Skill: issue-tracker

## Description

Manages GitHub issue lifecycle for the MemoryHub project. Enforces conventions: every issue references a design document, starts in Backlog, and follows the Backlog -> In Progress -> Done flow.

## Commands

- `/issue-tracker create` -- Create a new issue (prompts for details)
- `/issue-tracker start <issue-number>` -- Move issue to In Progress
- `/issue-tracker done <issue-number>` -- Move issue to Done (after confirmation)
- `/issue-tracker list` -- Show current board state
- `/issue-tracker backlog` -- Show backlog items

---

## Configuration

```
PROJECT_NUMBER=1
PROJECT_ID=PVT_kwDODErzuc4BUFze
STATUS_FIELD_ID=PVTSSF_lADODErzuc4BUFzezhBQT0U
BACKLOG_OPTION_ID=5af61e02
IN_PROGRESS_OPTION_ID=97ae4b78
DONE_OPTION_ID=61db5447
REPO=redhat-ai-americas/memory-hub
OWNER=redhat-ai-americas
```

---

## Labels

### Subsystem labels

- `subsystem:memory-tree`
- `subsystem:storage`
- `subsystem:curator`
- `subsystem:governance`
- `subsystem:mcp-server`
- `subsystem:operator`
- `subsystem:observability`
- `subsystem:org-ingestion`
- `subsystem:auth`

### Type labels

- `type:feature`
- `type:bug`
- `type:design`
- `type:infra`

---

## Issue Creation (`/issue-tracker create`)

Every issue MUST satisfy these requirements:

1. **Reference a design document and section.** For example: `docs/memory-tree.md#versioning`. If no design doc exists for the work, create or update one first.
2. **Be added to the Backlog column** of the MemoryHub project board on creation.
3. **Use a concise conventional title.** Format: `subsystem: Description in imperative mood`. Example: `memory-tree: Implement versioning with isCurrent flag`.
4. **Include required body sections** (see template below).
5. **Apply exactly one subsystem label and one type label.**

### Workflow

1. Ask the user for:
   - Subsystem (one of the subsystem labels above)
   - Type (feature, bug, design, or infra)
   - Title (suggest one based on the description, let user confirm)
   - Description of what needs to be done
   - Design document reference (file path and section anchor)
   - Acceptance criteria (optional but encouraged)

2. Create the issue:

```bash
gh issue create \
  --repo "$REPO" \
  --title "subsystem: Title here" \
  --label "subsystem:xxx,type:yyy" \
  --body "$(cat <<'EOF'
## Description

<clear description of what needs to be done>

## Design Reference

- Document: `docs/xxx.md`
- Section: [Section Name](docs/xxx.md#section-anchor)

## Acceptance Criteria

- [ ] Criterion 1
- [ ] Criterion 2
EOF
)"
```

3. Capture the issue number from the output, then add it to the project Backlog:

```bash
# Get the issue node ID
ISSUE_NODE_ID=$(gh issue view <NUMBER> --repo "$REPO" --json id --jq '.id')

# Add to project
ITEM_ID=$(gh project item-add PROJECT_NUMBER \
  --owner "$OWNER" \
  --url "https://github.com/$REPO/issues/<NUMBER>" \
  --format json | jq -r '.id')

# Set status to Backlog
gh project item-edit \
  --project-id "$PROJECT_ID" \
  --id "$ITEM_ID" \
  --field-id "$STATUS_FIELD_ID" \
  --single-select-option-id "$BACKLOG_OPTION_ID"
```

4. Report the created issue URL to the user.

---

## Start Work (`/issue-tracker start <issue-number>`)

Move an issue from Backlog to In Progress.

```bash
# Find the project item ID for this issue
ITEM_ID=$(gh project item-list PROJECT_NUMBER \
  --owner "$OWNER" \
  --format json | jq -r '.items[] | select(.content.number == <NUMBER>) | .id')

# Update status to In Progress
gh project item-edit \
  --project-id "$PROJECT_ID" \
  --id "$ITEM_ID" \
  --field-id "$STATUS_FIELD_ID" \
  --single-select-option-id "$IN_PROGRESS_OPTION_ID"
```

Also assign the issue if not already assigned:

```bash
gh issue edit <NUMBER> --repo "$REPO" --add-assignee "@me"
```

---

## Complete Work (`/issue-tracker done <issue-number>`)

**Always confirm with the user before moving to Done.** Ask: "Confirm moving issue #N to Done?"

Only after confirmation:

```bash
# Find the project item ID
ITEM_ID=$(gh project item-list PROJECT_NUMBER \
  --owner "$OWNER" \
  --format json | jq -r '.items[] | select(.content.number == <NUMBER>) | .id')

# Update status to Done
gh project item-edit \
  --project-id "$PROJECT_ID" \
  --id "$ITEM_ID" \
  --field-id "$STATUS_FIELD_ID" \
  --single-select-option-id "$DONE_OPTION_ID"

# Close the issue
gh issue close <NUMBER> --repo "$REPO"
```

---

## List Board (`/issue-tracker list`)

Show issues grouped by status column.

```bash
gh project item-list PROJECT_NUMBER \
  --owner "$OWNER" \
  --format json | jq '
    .items
    | group_by(.status)
    | map({status: .[0].status, issues: [.[] | {number: .content.number, title: .content.title}]})
  '
```

Present the output in a readable table grouped by column (Backlog, In Progress, Done).

---

## Show Backlog (`/issue-tracker backlog`)

Show only Backlog items.

```bash
gh project item-list PROJECT_NUMBER \
  --owner "$OWNER" \
  --format json | jq '
    [.items[] | select(.status == "Backlog") | {number: .content.number, title: .content.title}]
  '
```

Present as a numbered list with issue numbers and titles.

---

## Rules

- **Never create an issue without a design document reference.** If the user cannot provide one, help them identify or create the appropriate design doc first.
- **Never skip the Backlog step.** Every issue starts in Backlog, even if work begins immediately (move to In Progress as a separate step).
- **Never move to Done without user confirmation.**
- **Always apply both a subsystem label and a type label.** If unsure which subsystem, ask the user.
- **Follow the user's CLAUDE.md rules for issue attribution.** Issues show the human author (rdwj) as submitter. No AI attribution on issues.
