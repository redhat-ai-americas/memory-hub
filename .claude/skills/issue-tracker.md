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

### Do not use `gh project item-list` to find a single item

It defaults to 30 items and the board returns oldest-first, so the default
window holds only the oldest issues. A lookup for a newly created issue
reports "not found" even though the item is on the board. Raising `--limit`
past the board size fixes the truncation but pages the whole board on every
lookup, which trips GitHub's secondary rate limit during a run of several
issue operations.

Use whichever of these fits:

- **Just added the item?** `gh project item-add --format json --jq '.id'`
  returns its ID. No lookup needed.
- **Item already on the board?** Use the GraphQL query in
  [Find an item ID](#find-an-item-id). One request, cannot truncate.
- **Need the whole board** (list, backlog)? `item-list` with an explicit
  `--limit` above `totalCount`. Do not call it in a loop.

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

1. **Reference a design document and section.** For example: `docs/design/memory-tree.md#versioning`. If no design doc exists for the work, create or update one first.
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

## Find an item ID

For an issue already on the board. One request, and it cannot truncate.

```bash
item_id() {
  local resp id
  resp=$(gh api graphql -f query='
  query($owner:String!, $repo:String!, $num:Int!) {
    repository(owner:$owner, name:$repo) {
      issue(number:$num) {
        projectItems(first:10) {
          nodes { id project { number } }
        }
      }
    }
  }' -f owner="$OWNER" -f repo=memory-hub -F num="$1") || return 1

  if jq -e '.errors' >/dev/null 2>&1 <<<"$resp"; then
    echo "GraphQL error for #$1: $(jq -r '.errors[0].message' <<<"$resp")" >&2
    return 1
  fi

  id=$(jq -r ".data.repository.issue.projectItems.nodes[]
              | select(.project.number == $PROJECT_NUMBER) | .id" <<<"$resp")
  case "$id" in
    PVTI_*) echo "$id" ;;
    "")     echo "#$1 is not on board $PROJECT_NUMBER" >&2; return 1 ;;
    *)      echo "unexpected item id for #$1: $id" >&2; return 1 ;;
  esac
}
```

The explicit error check matters. With `--jq`, `gh` prints the GraphQL
error body to stdout and still exits 0, so a rate-limited query returns a
JSON error blob that a bare non-empty test would accept as an item ID and
pass to `item-edit`.

A `return 1` with "not on board" means exactly that. Add it with
`gh project item-add` before setting a status.

---

## Start Work (`/issue-tracker start <issue-number>`)

Move an issue from Backlog to In Progress.

```bash
ITEM_ID=$(item_id <NUMBER>) || exit 1

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
ITEM_ID=$(item_id <NUMBER>) || exit 1

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
  --limit 1000 \
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
  --limit 1000 \
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
- **Follow the user's CLAUDE.md rules for issue attribution.** Issues show the human author as submitter. No AI attribution on issues.
