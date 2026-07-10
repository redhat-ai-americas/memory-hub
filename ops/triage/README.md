# Triage Bot

A lightweight GitHub webhook receiver that uses Claude Code to triage incoming issues and PRs on `redhat-ai-americas/memory-hub`.

**What it does:**

- New issues from external contributors: suggests labels, checks for duplicates, flags spam, welcomes first-time contributors
- New PRs from external contributors: checks template completeness, commit format, PR size, sensitive file changes
- Skips internal authors (rdwj, bots) to avoid feedback loops with interactive Claude Code sessions

## Setup

### 1. Install dependencies

```bash
cd ops/triage
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
export TRIAGE_WEBHOOK_SECRET="your-secret-here"
```

Optional overrides:

| Variable | Default | Description |
|---|---|---|
| `TRIAGE_SKIP_AUTHORS` | `rdwj,dependabot[bot],github-actions[bot]` | Comma-separated authors to skip |
| `TRIAGE_RATE_LIMIT` | `10` | Max webhook events per minute |
| `TRIAGE_CLAUDE_TIMEOUT` | `120` | Claude invocation timeout (seconds) |
| `GH_TOKEN` | (from `gh auth`) | GitHub token for posting comments/labels |

### 3. Set up webhook forwarding (local dev)

Install [smee-client](https://github.com/probot/smee-client) for local webhook forwarding:

```bash
npm install -g smee-client
```

Create a channel at https://smee.io/new, then:

```bash
smee -u https://smee.io/YOUR_CHANNEL -t http://localhost:8787/webhook
```

### 4. Configure GitHub webhook

In repo Settings > Webhooks > Add webhook:

- **Payload URL**: Your smee.io URL (local) or server URL (production)
- **Content type**: `application/json`
- **Secret**: Same value as `TRIAGE_WEBHOOK_SECRET`
- **Events**: Select "Issues" and "Pull requests"

### 5. Run the server

```bash
uvicorn server:app --port 8787
```

## Testing

```bash
pip install -r requirements-dev.txt
pytest test_server.py -v
```

## EC2 migration

When moving from local to ec2:

1. Copy `ops/triage/` to the ec2 instance
2. Install `claude` CLI and `gh` CLI, authenticate both
3. Update the GitHub webhook URL from smee to the ec2 address
4. Run with systemd or similar process manager
5. Set `GH_TOKEN` for the bot account when ready

## Architecture

```
GitHub webhook -> FastAPI (signature check, author filter, rate limit)
  -> BackgroundTask: claude -p "triage prompt"
    -> Claude Code runs gh commands to comment + label
```

No database, no queue. Claude Code is the entire AI layer. If a triage fails, the issue/PR just waits for manual review.
