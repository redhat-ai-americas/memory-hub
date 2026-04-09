# Inviting New Contributors

This document is for the project maintainer (currently `@rdwj`). It is the checklist to run when onboarding a new developer — either a Red Hat colleague joining the effort, an external contributor invited to a specific piece of work, or a returning collaborator picking work back up after time away.

The goal is to make the invitation process mechanical enough that you do not have to remember what the steps are, but thorough enough that the new person lands in a working state with the context they need.

If you are the new contributor and somebody just pointed you at this document by mistake, you want [`CONTRIBUTING.md`](../CONTRIBUTING.md) instead.

## When to use this document

Use this checklist when any of the following is true:

- You are about to invite somebody to `redhat-ai-americas/memory-hub` for the first time
- You are re-inviting somebody after a long absence and their prior access has been pruned
- You are onboarding an external contributor to a specific sub-project or tracked issue
- You are bringing a new Red Hat colleague onto the team as a regular contributor

Do **not** use this for transient collaborators who only need to file an issue or comment on a PR — public repo visibility is enough for that.

## Before the invitation — prerequisites

Confirm all of the following are true before you send anybody an invite:

1. **Repo is public or the contributor is already in the `redhat-ai-americas` GitHub org.** If the repo is private and the contributor is not an org member, the invitation will silently fail to give them read access to the wiki, project board, and so on.
2. **Branch protection is healthy.** Run `gh api repos/redhat-ai-americas/memory-hub/branches/main/protection` and verify `required_pull_request_reviews.required_approving_review_count` is 1 and `required_pull_request_reviews.require_code_owner_reviews` is true. These were set in commit `b1ea397`.
3. **`CODEOWNERS` is current.** `.github/CODEOWNERS` should list `@rdwj` and whichever Red Hat colleagues have agreed to act as code owners. Adding a new contributor as a code owner is a separate step and requires their explicit agreement — do not do it at invite time.
4. **PR and issue templates exist.** Verify `.github/pull_request_template.md` and `.github/ISSUE_TEMPLATE/*.yml` are present (commit `3b4b1d8`). These are what set expectations on the contributor's first PR and first issue without you having to re-explain the conventions.
5. **Backlog has starter work.** Run `gh issue list --label "good first issue"` and confirm at least three open issues exist. If the backlog is empty, triage before sending invitations — an empty starter pile makes the invite feel performative.
6. **The cluster access policy doc is current.** [`docs/contributor-cluster-access.md`](contributor-cluster-access.md) needs to exist and the cluster route identifiers in it need to match the current sandbox rebuild. New contributors do not get cluster access at first, and the doc explains the policy.

If any of the above is missing, fix it before inviting.

## The invitation steps

### 1. Confirm the contributor is ready

Ask them — by message, email, or in person — the following four questions. Do not send the GitHub invite until you have answers:

1. *What is your GitHub username?* (Not their Red Hat username, not their email. The literal GitHub handle.)
2. *What are you interested in working on?* (Feature area, subsystem, bug, documentation — anything. This determines which starter issue you point them at.)
3. *Have you worked with this repo's stack before?* (Python + FastAPI + Pydantic + SQLAlchemy + alembic + FastMCP + OpenShift. Different answers change how much setup hand-holding you provide.)
4. *Will you need access to the demo OpenShift cluster for this work?* (Default answer is no — most contributions do not. If the answer is yes, they are on a slower path because cluster access is granted case by case.)

Capture their answers in a scratchpad. You will need them in step 4.

### 2. Add the contributor to the GitHub org (if applicable)

If the contributor is Red Hat and is not already a member of `redhat-ai-americas`:

1. Navigate to https://github.com/orgs/redhat-ai-americas/people
2. Click **Invite member**, enter their GitHub username or email
3. Choose **Member** as the role. Do not make them an owner.
4. Wait for them to accept the org invitation before proceeding

If the contributor is external to Red Hat and the repo is public, you can skip this step — external contributors can fork, PR, and comment without being org members. If the repo ever goes private again, external contributors need to be added as outside collaborators via the repo settings directly.

### 3. Grant repo-level access

The default access level for a new contributor is **read** through org membership. That is enough to fork, clone, open PRs, comment, and view everything in the repo.

If the contributor needs direct push access to feature branches (so they can push to `fix/...` branches in the main repo rather than forking), add them as a collaborator with **Write** role:

```bash
gh api --method PUT repos/redhat-ai-americas/memory-hub/collaborators/<github-username> \
  --field permission=push
```

Never grant **Maintain** or **Admin** at invite time. Maintain gets added later (after several successful PRs) only if the contributor is going to be a regular committer. Admin stays with `@rdwj`.

### 4. Send the welcome message

Compose a message with the following pieces, in this order:

1. **Welcome and context.** Two sentences: what MemoryHub is, why you invited them. Do not link the architecture doc here — that comes later.
2. **Link to `CONTRIBUTING.md`.** This is the single most important link. It has the repo layout, the per-subproject venv setup, the commit-message format, and the PR flow. Every other doc is optional; this one is not.
3. **Link to `docs/contributor-cluster-access.md`.** Call out specifically that new contributors default to no cluster access and that this is deliberate policy, not a slight.
4. **A specific starter issue.** Not "look at the good-first-issue label" — a specific issue number. Pick one that matches their stated interests from step 1, read the issue yourself to confirm it is still a good fit, and link it. Include one line of context on why you picked it.
5. **How to contact you.** Slack, email, whatever the fastest channel is. Set expectations: "I review PRs within a business day; ping me if I go quiet."
6. **What their first PR should look like.** One sentence: "Your first PR should close the starter issue above. Keep the diff focused on that one issue and follow the PR template."
7. **An offer to pair.** "If you'd like to pair on the first PR — environment setup through first commit — happy to do a 30-minute call."

Keep the whole message under 300 words. Longer welcomes get skimmed.

Example template:

> Hi <name>,
>
> Welcome to MemoryHub. You've been added to `redhat-ai-americas/memory-hub`. The short version of what we are: a Kubernetes-native agent memory component for OpenShift AI, with an MCP server, a typed Python SDK, a dashboard UI, and a standalone OAuth 2.1 service.
>
> Start here: [`CONTRIBUTING.md`](https://github.com/redhat-ai-americas/memory-hub/blob/main/CONTRIBUTING.md). It has the per-subproject venv setup, the commit-message format, and the PR flow. Everything else is optional.
>
> One thing to know up front: new contributors default to no OpenShift cluster access. The policy is in [`docs/contributor-cluster-access.md`](https://github.com/redhat-ai-americas/memory-hub/blob/main/docs/contributor-cluster-access.md). Almost nothing in the repo actually needs the cluster — local dev is enough.
>
> Your starter issue: [#<NNN>](https://github.com/redhat-ai-americas/memory-hub/issues/<NNN>). I picked it because it matches the <auth / curator / UI / storage> interest you mentioned, is tightly scoped, and has a clear acceptance criterion. Keep your first PR focused on closing just that issue.
>
> Ping me on Slack (`<your-handle>`) any time. I review PRs within a business day. Happy to pair on the first PR — setup through first commit — if a 30-minute call would help.
>
> Welcome aboard.

### 5. Update the project board

Assign the starter issue to the new contributor in GitHub Issues, but **do not** move it to "In Progress" on the project board. The contributor moves it themselves when they start — that's their signal that they are actively picking it up, and it is the first moment they interact with the project board conventions.

### 6. Log the invitation

Capture the invitation in this repo's history by writing a note to MemoryHub memory (or a local note file if MCP is down):

- Name and GitHub handle
- Invitation date
- Starter issue number
- Whether cluster access was granted or deferred
- Any special context (*"external contributor, will fork"* / *"Red Hat colleague, needs auth work"* / *"returning after 6-month absence, previously shipped #X"*)

This log is useful when the contributor's first PR lands and you want to add them to the retrospective, or when you need to reconstruct who got invited when.

### 7. Set a 7-day check-in reminder

Schedule yourself a reminder for 7 days after the invitation. At that point, check:

- Has the contributor cloned the repo? (`gh api repos/redhat-ai-americas/memory-hub/traffic/clones` shows clone counts but not per-user.)
- Has the contributor commented on or moved their starter issue?
- Has a draft PR appeared?

If the answer to all three is no, send a short follow-up: *"How's it going? Any blockers?"* Silence at day 7 is normal — people get busy. Silence at day 14 is worth a more direct check-in. Silence at day 30 means the invitation did not land and the starter issue should go back in the backlog unassigned.

## After the first PR lands

When the contributor's first PR is merged, do all of the following:

1. **Thank them in the PR.** A single-sentence "welcome, thanks for the PR" is sufficient. This is morale, not ceremony.
2. **Move the closed issue to Done on the project board.** The issue-close flow does not auto-sync the project status — you still need to run the manual move or use the `/issue-tracker done <N>` slash command.
3. **Point them at the next starter issue.** Do not wait for them to ask. Pick a second issue that builds on what they just did, and link it in the PR comment or in a follow-up message.
4. **If they want more responsibility, consider adding them as a code owner** for the subsystem they just touched. This is a commitment on their part (they will be pinged to review future PRs in that area), so ask before adding them to `.github/CODEOWNERS`.
5. **Write a short retrospective note** if anything about the onboarding was rougher than expected. Under `retrospectives/YYYY-MM-DD_onboarding-<handle>/RETRO.md` is fine. The goal is not to grade the contributor — it is to capture what to fix in this checklist for the next invitation.

## Revoking access

When a contributor leaves the project (finished their tour, moved to a different team, went inactive for 6+ months):

1. Remove them from the `redhat-ai-americas` org via https://github.com/orgs/redhat-ai-americas/people
2. If they were added as a direct collaborator on the repo, also remove them from `gh api repos/redhat-ai-americas/memory-hub/collaborators`
3. If they had a `memoryhub-auth` client credential, rotate it (see [`docs/contributor-cluster-access.md`](contributor-cluster-access.md#rotation)) and remove them from the `memoryhub-users` ConfigMap
4. If they were listed in `.github/CODEOWNERS`, remove them in a separate commit
5. If they had cluster-level role bindings, delete those: `oc delete rolebinding <name> -n <namespace>`
6. Do **not** delete their past commits, close their open PRs without explanation, or rewrite git history. Their contributions stay in the log under their authorship.

Revocation is a hygiene step, not a judgment. Keep it mechanical.

## What to do if the invite goes wrong

A few failure modes and their fixes:

- **Contributor never accepts the org invitation.** The invite expires after 7 days. Reissue it once. If they still do not accept, assume they are not joining and move on.
- **Contributor accepts but never opens a PR.** See the 7/14/30-day check-in schedule above. Do not nag beyond day 30.
- **Contributor opens a PR but it is massively out of scope** (e.g., a sweeping refactor instead of the specific starter issue). Close or convert to a draft with a kind explanation: *"This is much bigger than #NNN — can we split it? Let's start with the specific thing in #NNN and file follow-up issues for the rest."*
- **Contributor pushes directly to `main` by accident.** This should be blocked by branch protection, but if it somehow gets through (admin override, compromised account), revert the direct push, explain the protection policy, and point them at the PR flow.
- **Contributor's first PR is excellent but has AI attribution in the commits** (Co-authored-by, Signed-off-by: Claude Code). Comment on the PR asking them to amend with `Assisted-by:` instead (see [`CLAUDE.md`](../CLAUDE.md)). Do not merge with non-conforming trailers — future contributors will copy the pattern.
- **Contributor asks for cluster access before shipping any PRs.** Say no, and point them at `docs/contributor-cluster-access.md`. The policy exists precisely for this case.

## Related documents

- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — the doc you send new contributors to; local setup, PR flow, coding conventions
- [`docs/contributor-cluster-access.md`](contributor-cluster-access.md) — the cluster access policy and the GitHub IdP reference
- [`CLAUDE.md`](../CLAUDE.md) — agent-facing conventions that overlap with the human-facing `CONTRIBUTING.md`
- [`.github/CODEOWNERS`](../.github/CODEOWNERS) — who reviews what
- [`.github/pull_request_template.md`](../.github/pull_request_template.md) — what new contributors see when they open a PR
