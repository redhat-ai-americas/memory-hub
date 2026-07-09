from config import REPO, SPECIAL_LABELS, SUBSYSTEM_LABELS, TYPE_LABELS

VALID_LABELS = TYPE_LABELS + SUBSYSTEM_LABELS + SPECIAL_LABELS


def build_issue_prompt(payload: dict) -> str:
    number = payload["issue"]["number"]
    title = payload["issue"]["title"]
    author = payload["issue"]["user"]["login"]
    body = payload["issue"].get("body") or ""
    search_terms = " ".join(title.split()[:5])

    return f"""
Triage GitHub issue #{number} from @{author}.

**Title**: {title}

**Body**:
{body or "(empty)"}

**Your tasks**:

1. **Suggest 1-2 labels** from this list:
   {', '.join(VALID_LABELS)}

   Apply labels via:
   gh issue edit {number} --repo {REPO} --add-label "label1,label2"

2. **Check for duplicates**:
   gh issue list --repo {REPO} --search "{search_terms}" --state open --limit 5 --json number,title

   If you find a likely duplicate, mention it in your comment (do NOT close the issue).

3. **Check body quality**:
   - If body is empty, very short, or looks like spam, post a polite comment asking for detail.
   - If this is a feature request without a design doc reference, add the `needs-design` label.

4. **Post a single triage summary comment** prefixed with:
   > **Automated triage** -- a maintainer will follow up.

   Be welcoming and professional. Summarize what you did (labels applied, duplicates found, etc.).

**Rules**:
- Do NOT close, assign, or merge anything.
- If uncertain about a label, skip it.
- Keep the comment concise (2-4 sentences).
- This is an external contributor -- be helpful, not critical.
""".strip()


def build_pr_prompt(payload: dict) -> str:
    pr = payload["pull_request"]
    number = pr["number"]
    title = pr["title"]
    author = pr["user"]["login"]
    body = pr.get("body") or ""
    additions = pr["additions"]
    deletions = pr["deletions"]
    changed_files = pr["changed_files"]

    return f"""
Triage GitHub pull request #{number} from @{author}.

**Title**: {title}

**Body**:
{body or "(empty)"}

**Size**: +{additions}/-{deletions} across {changed_files} file(s)

**Your tasks**:

1. **Check PR template completeness**:
   - Does body include: summary, linked issue, design doc reference, type checkbox, subsystem checkbox, test plan?
   - If any section is missing or incomplete, note it in your comment.

2. **Check commit messages**:
   gh pr view {number} --repo {REPO} --json commits --jq '.commits[].messageHeadline'

   Verify format: `subsystem: Imperative description`
   If any commit doesn't match, mention it.

3. **Flag large PRs**:
   If additions + deletions > 500, mention this. Suggest breaking into smaller PRs if feasible.

4. **Flag sensitive file changes**:
   gh pr diff {number} --repo {REPO} --name-only

   Check for: memory-hub-mcp/, scripts/deploy-full.sh, scripts/uninstall-full.sh,
   .github/workflows/, sdk/, memoryhub-cli/
   If any are touched, mention "This PR modifies sensitive infrastructure files -- maintainer review required."

5. **Apply type: and subsystem: labels**:
   Extract from title/body or first commit message. Use:
   gh issue edit {number} --repo {REPO} --add-label "label1,label2"

   Valid labels:
   {', '.join(VALID_LABELS)}

6. **Post a single structured comment** prefixed with:
   > **Automated triage** -- a maintainer will follow up.

   Summarize: template completeness, commit format, labels applied, any flags.

**Rules**:
- Do NOT approve, request changes, merge, close, or assign.
- Be welcoming -- this is an external contributor.
- If the PR looks good, say so. Don't manufacture problems.
- Keep the comment concise (3-5 sentences).
""".strip()
