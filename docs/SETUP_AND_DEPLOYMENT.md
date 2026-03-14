# Mason: Setup & Deployment Guide

Mason is a multi-agent AI system for automated software delivery. It ingests Jira tickets, plans
implementation using Claude Opus (orchestrator), delegates coding to Claude Sonnet (workers), and
opens pull requests — all with Teams-based human approval gates.

---

## Architecture Overview

```
Teams / Jira Webhook
        │
        ▼
  Webhook Server (FastAPI :8000)
        │  enqueue task
        ▼
   SQS Task Queue
        │  dequeue
        ▼
  Worker Process (SQS poller)
        │
        ▼
  WorkflowPipeline
        │
        ▼
  Orchestrator Agent (Claude Opus)
  ├── plans implementation phases
  ├── reads Jira, Confluence, Figma via MCP
  └── spawns Worker Agents (Claude Sonnet × N)
            │
            ▼
      Worker Agents
      ├── clone repo, write code, run tests
      ├── commit + open Pull Request
      └── notify Teams → await approval
```

**Two deployment modes:**

| Mode | Infrastructure | Cost | Use When |
|------|---------------|------|----------|
| Lightsail (eval) | Single EC2-like instance + DynamoDB + SQS | ~$10/mo | Development, evaluation |
| Full AWS (production) | ECS Fargate + ALB + WAF + KMS + ECR | ~$90–130/mo | Production workloads |

---

## 1. Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.10+ (3.12 preferred) | `python --version` |
| [uv](https://github.com/astral-sh/uv) | latest | Package manager |
| AWS CLI | v2 | `aws --version` |
| Node.js | 18+ | Required for Teams MCP connector |
| Docker + Docker Compose | latest | Required for deployment |
| [OpenTofu](https://opentofu.org) | 1.6+ | Infrastructure provisioning |
| Git | any | Source control |

---

## 2. Repository Setup

```bash
# Clone
git clone <repo-url> mason
cd mason

# Create virtual environment
uv venv
source .venv/bin/activate       # Linux/macOS
# .venv\Scripts\activate        # Windows

# Install all dependencies (including dev)
uv pip install -e ".[dev]"

# Copy and fill in environment variables
cp .env.example .env
```

Edit `.env` — see the full reference in [Section 3](#3-environment-variables-reference).

---

## 3. Environment Variables Reference

### AWS

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AWS_REGION` | Yes | `us-east-1` | AWS region for all services |
| `AWS_PROFILE` | No | — | AWS CLI profile (local dev only) |

### Anthropic (Claude Agent SDK backend)

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes* | API key from console.anthropic.com. Required when `backend: claude-agent-sdk` |

*Not needed if using the `bedrock` backend with IAM credentials.

### MCP Tokens

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_PAT` | Yes | GitHub Personal Access Token — scopes: `repo`, `read:org` |
| `FIGMA_PAT` | No | Figma Personal Access Token (only needed for UI-heavy tasks) |
| `MS_APP_ID` | No | Azure AD App (Bot) ID for Teams integration |
| `MS_APP_PASSWORD` | No | Azure AD App secret for Teams integration |
| `MS_TENANT_ID` | No | Azure AD Tenant ID |
| `ATLASSIAN_SITE_URL` | Yes | e.g. `https://your-org.atlassian.net` |
| `ATLASSIAN_USER_EMAIL` | Yes | Atlassian account email |
| `ATLASSIAN_API_TOKEN` | Yes | Atlassian API token from id.atlassian.com |

### Mason Settings (`MASON_` prefix)

| Variable | Default | Description |
|----------|---------|-------------|
| `MASON_ORG` | `giftbee` | GitHub/Bitbucket organisation |
| `MASON_PROJECT` | `mason` | Project name (used in resource naming) |
| `MASON_WORKSPACE_ROOT` | — | Absolute path to local monorepo root |
| `MASON_TEAMS_NOTIFICATION_CHANNEL` | `mason-notifications` | Teams channel for status messages |
| `MASON_TEAMS_APPROVAL_CHANNEL` | `mason-approvals` | Teams channel for approval requests |
| `MASON_OPUS_MODEL_ID` | `us.anthropic.claude-opus-4-6-20250609-v1:0` | Bedrock model ID for orchestrator |
| `MASON_SONNET_MODEL_ID` | `us.anthropic.claude-sonnet-4-6-20250514-v1:0` | Bedrock model ID for workers |
| `MASON_TF_STATE_BUCKET` | `giftbee-tofu-state` | S3 bucket for OpenTofu remote state |
| `MASON_TF_LOCK_TABLE` | `giftbee-tofu-locks` | DynamoDB table for OpenTofu state lock |

### Worker Runtime

| Variable | Required | Description |
|----------|----------|-------------|
| `SQS_QUEUE_URL` | Yes | SQS queue URL — from `tofu output sqs_queue_url` after infra setup |

### Memory Subsystem (`MASON_MEMORY_` prefix)

| Variable | Default | Description |
|----------|---------|-------------|
| `MASON_MEMORY_AWS_REGION` | `us-east-1` | AWS region for DynamoDB |
| `MASON_MEMORY_DYNAMODB_ENDPOINT_URL` | — | Override for DynamoDB Local (e.g. `http://localhost:8000`) |
| `MASON_MEMORY_SESSION_TABLE` | `mason-session-memory` | Session memory table name |
| `MASON_MEMORY_EPISODIC_TABLE` | `mason-episodic-memory` | Episodic memory table name |
| `MASON_MEMORY_SEMANTIC_TABLE` | `mason-semantic-memory` | Semantic memory table name |
| `MASON_MEMORY_SESSION_TTL_SECONDS` | `86400` | Session memory item TTL (24 h) |

---

## 4. MCP Server Setup

MCP (Model Context Protocol) is how Mason's agents talk to external systems. Configuration lives
in two places:
- **`.mcp.json`** — transport-level config (used by Claude Code / agent SDK)
- **`config/mcp_servers.yaml`** — connection details used by `src/integrations/mcp_manager.py`

### 4a. Atlassian (Jira & Confluence)

1. Generate an API token at [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens)
2. Set in `.env`:
   ```
   ATLASSIAN_SITE_URL=https://your-org.atlassian.net
   ATLASSIAN_USER_EMAIL=you@example.com
   ATLASSIAN_API_TOKEN=<token>
   ```
3. Transport: SSE to `https://mcp.atlassian.com/v1/sse` (`.mcp.json`)

### 4b. GitHub

1. Create a PAT at [github.com/settings/tokens](https://github.com/settings/tokens) — classic token
   with `repo` and `read:org` scopes
2. Set in `.env`:
   ```
   GITHUB_PAT=ghp_xxxxxxxxxxxx
   ```
3. Transport: Docker image `ghcr.io/github/github-mcp-server` (`.mcp.json`)
   — Docker must be running

### 4c. Figma

1. Create a PAT at [figma.com](https://figma.com) → Account settings → Security
2. Set in `.env`:
   ```
   FIGMA_PAT=figd_xxxxxxxxxxxx
   ```
3. Transport: HTTP to `https://mcp.figma.com/mcp` (`.mcp.json`)

### 4d. Microsoft Teams

1. Register an Azure Bot in [portal.azure.com](https://portal.azure.com):
   - Create a new App Registration (or Multi-tenant Bot)
   - Note the `Application (client) ID` → `MS_APP_ID`
   - Create a client secret → `MS_APP_PASSWORD`
   - Note the `Directory (tenant) ID` → `MS_TENANT_ID`
2. Set in `.env`:
   ```
   MS_APP_ID=<app-id>
   MS_APP_PASSWORD=<secret>
   MS_TENANT_ID=<tenant-id>
   ```
3. Install the Teams MCP connector:
   ```bash
   npm install @mcp/teams-connector
   ```
4. Transport: stdio via `node ./node_modules/@mcp/teams-connector/dist/index.js` (`.mcp.json`)

### 4e. Playwright (Browser Automation)

No credentials needed. Playwright is launched on demand via `npx`.

```bash
# Optionally pre-install browsers
npx playwright install chromium
```

If browsers are installed to a non-default path, set:
```
PLAYWRIGHT_BROWSERS_PATH=/path/to/browsers
```

Transport: stdio via `npx @playwright/mcp@latest --headless` (`.mcp.json`)

Playwright tools are automatically added to worker agents when a frontend skill
(React, Next.js, Playwright) is detected for the task. See `config/agents.yaml` →
`claude_agent_sdk.allowed_tools.worker_frontend`.

---

## 5. Configuration Files

### `config/agents.yaml`

Controls LLM backend selection, model IDs, timeouts, and Claude Agent SDK settings.

Key fields:
```yaml
backend: claude-agent-sdk       # "claude-agent-sdk" | "bedrock"

orchestrator:
  model: claude-opus-4-6
  max_workers: 5
  timeout_minutes: 480

worker:
  model: claude-sonnet-4-6
  timeout_minutes: 30
  retry_count: 1

claude_agent_sdk:
  max_turns_orchestrator: 50
  max_turns_worker: 25
  permission_mode: acceptEdits   # "acceptEdits" (autonomous) | "prompt" (supervised)
  cwd: /workspace
```

### `config/limits.yaml`

Cost and safety limits:
```yaml
cost:
  daily_ceiling_usd: 50.0        # Hard stop at $50/day
  alert_threshold_pct: 80        # Alert at 80%

workers:
  max_concurrent: 5
  max_per_ticket: 3

approval_gates:
  always_require:
    - pre_merge
    - destructive_migration
```

### `config/repositories.yaml`

Defines the GiftBee repositories Mason can modify:
- `wallet-service` — PHP/Laravel backend (Bitbucket, branch: `dev`)
- `store-front` — Next.js customer portal (Bitbucket, branch: `main`)
- `admin-portal` — Next.js admin portal (Bitbucket, branch: `dev`)
- `pim` — PHP Pimcore product catalog (Bitbucket, branch: `dev`)
- `local-infra` — Docker Compose dev infrastructure (Bitbucket, branch: `dev`)

Each entry includes `local_path`, `test_cmd`, `e2e_test_cmd`, `depends_on_services`, etc.
Set `MASON_WORKSPACE_ROOT` so path interpolation works (`${MASON_WORKSPACE_ROOT}/wallet-service`).

### `config/skills.yaml`

Maps tech stacks to prompt files and file/keyword patterns used for skill detection:
- `react`, `nextjs`, `typescript`, `php`, `laravel`, `playwright`, `python`
- `design_patterns`, `app_architecture`, `infra_architecture`

Skill detection determines which system-prompt injections and tool sets are activated for a task.

### `config/mcp_servers.yaml`

Connection details for each MCP server used programmatically (separate from `.mcp.json`).
Environment variables are referenced here — do not hard-code tokens.

---

## 6. LLM Backend Configuration

Set `backend:` in `config/agents.yaml`. Two options:

### Claude Agent SDK (recommended for evaluation)

```yaml
backend: claude-agent-sdk
```

- Uses `ANTHROPIC_API_KEY` directly
- Agents operate autonomously with `Read`, `Write`, `Bash` tools
- No AWS dependency for LLM calls
- Faster iteration; no Bedrock quota requests needed

### AWS Bedrock

```yaml
backend: bedrock
```

- Uses IAM credentials — no API key needed
- Requires Bedrock model access enabled for your AWS account:
  1. Open [AWS Bedrock console](https://console.aws.amazon.com/bedrock) → Model access
  2. Enable `claude-opus-4-6` and `claude-sonnet-4-6` cross-region profiles
- Model IDs:
  - Orchestrator: `us.anthropic.claude-opus-4-6-20250609-v1:0`
  - Worker: `us.anthropic.claude-sonnet-4-6-20250514-v1:0`

---

## 7. Local Development

```bash
# Run tests
pytest

# Lint
ruff check src/ tests/

# Type check (strict)
mypy src/

# Manual trigger — stub mode (no LLM)
python -m src.handlers.manual_trigger --ticket GIFT-1234

# Manual trigger — Claude Agent SDK (real LLM)
python -m src.handlers.manual_trigger --ticket GIFT-1234 --backend claude-agent-sdk

# Manual trigger — AWS Bedrock
python -m src.handlers.manual_trigger --ticket GIFT-1234 --bedrock

# Run webhook server locally (port 8000)
uvicorn src.handlers.webhook_server:create_webhook_app --factory --port 8000

# Health check
curl http://localhost:8000/health
```

---

## 8. Deploy to AWS Lightsail (Evaluation)

Lightsail provides a simple, low-cost evaluation environment (~$10/mo). The `deploy-lightsail.sh`
script manages everything from provisioning to teardown.

### 8a. Create SSH Key

```bash
ssh-keygen -t ed25519 -f ~/.ssh/mason-lightsail.pem
chmod 600 ~/.ssh/mason-lightsail.pem
```

### 8b. Configure Terraform State Backend

The Lightsail infra uses an S3 remote state backend. Create the bucket and lock table first
(one-time, manual):

```bash
aws s3api create-bucket --bucket giftbee-tofu-state --region us-east-1
aws dynamodb create-table \
  --table-name giftbee-tofu-locks \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1
```

Set matching values in `.env`:
```
MASON_TF_STATE_BUCKET=giftbee-tofu-state
MASON_TF_LOCK_TABLE=giftbee-tofu-locks
```

### 8c. Provision Infrastructure

```bash
./scripts/deploy-lightsail.sh setup
```

This will:
1. Import or generate `~/.ssh/mason-lightsail.pem` in Lightsail
2. Run `tofu init` + `tofu plan` and prompt for confirmation
3. Create:
   - Lightsail instance (2 GB RAM, `$10/mo` bundle) with static IP
   - Firewall rules: SSH (22), HTTPS (443), Webhook (8000)
   - DynamoDB tables: `mason-session-memory`, `mason-episodic-memory`, `mason-semantic-memory`
   - SQS queue `mason-tasks` + DLQ `mason-tasks-dlq`
   - IAM role with DynamoDB + SQS + Bedrock permissions

After setup, note the outputs:
```bash
cd infra/lightsail && tofu output
```

### 8d. Configure `.env`

Copy `.env.example` → `.env` and fill in all required values. Then set `SQS_QUEUE_URL`:
```
SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/<ACCOUNT_ID>/mason-tasks
```

### 8e. Deploy Application

Wait ~2 minutes after `setup` for the instance cloud-init to finish, then:

```bash
./scripts/deploy-lightsail.sh deploy
```

This will:
1. rsync project files to `/opt/mason` on the instance (excluding `.venv/`, `.git/`, etc.)
2. Copy `.env` securely via `scp`
3. Run `docker compose -f docker-compose.prod.yml build` on the instance
4. Start containers with `docker compose up -d`

### 8f. Operations

| Command | Description |
|---------|-------------|
| `./scripts/deploy-lightsail.sh status` | Show container health + HTTP health check |
| `./scripts/deploy-lightsail.sh logs` | Tail container logs (last 100 lines, follow) |
| `./scripts/deploy-lightsail.sh ssh` | Open SSH session to the instance |
| `./scripts/deploy-lightsail.sh restart` | Restart all containers |
| `./scripts/deploy-lightsail.sh stop` | Stop all containers |
| `./scripts/deploy-lightsail.sh deploy` | Re-deploy (sync + rebuild + restart) |
| `./scripts/deploy-lightsail.sh destroy` | Tear down all infrastructure |

### 8g. Cost Breakdown

| Resource | Monthly Cost |
|----------|-------------|
| Lightsail instance (2 GB) | $10.00 |
| DynamoDB (pay-per-request) | ~$0.00 |
| SQS (first 1M req/mo free) | ~$0.00 |
| Anthropic API (claude-agent-sdk) | Variable |
| AWS Bedrock (if enabled) | Variable |
| **Total baseline** | **~$10/mo** |

---

## 9. Deploy to Full AWS (Production)

The full AWS stack uses ECS Fargate, ALB, WAF, KMS, ECR, CloudWatch, and CI/CD via OIDC.
This path is defined in `infra/tofu/` and targets ~$90–130/mo.

```bash
# Plan staging
./scripts/deploy.sh staging plan

# Apply staging
./scripts/deploy.sh staging apply

# Apply production
./scripts/deploy.sh production apply
```

Or directly with OpenTofu:
```bash
cd infra/tofu
tofu init
tofu plan -var-file=envs/staging/terraform.tfvars
tofu apply -var-file=envs/staging/terraform.tfvars
```

Components provisioned: VPC + subnets, ECS Fargate (webhook + worker services), ALB + WAF,
KMS keys, ECR repositories, CloudWatch log groups + alarms, CI/CD OIDC role.

---

## 10. CI/CD

### Lightsail (`.github/workflows/deploy-lightsail.yml`)

Manual trigger only. Uses SSH + rsync to sync code and restart containers.

**Required GitHub secrets:**
```
LIGHTSAIL_SSH_KEY      # Contents of ~/.ssh/mason-lightsail.pem
```

**Required GitHub variables:**
```
AWS_ROLE_ARN           # IAM role ARN for OIDC auth
LIGHTSAIL_IP           # Static IP from tofu output
```

### Full AWS (`.github/workflows/deploy.yml`)

Triggered on push to `main`. Builds Docker images, pushes to ECR, updates ECS services.

**Required GitHub variables:**
```
AWS_ROLE_ARN           # IAM role ARN for OIDC auth
TF_STATE_BUCKET        # giftbee-tofu-state
TF_LOCK_TABLE          # giftbee-tofu-locks
```

---

## 11. Memory Subsystem

Mason uses three DynamoDB tables to give agents persistent memory:

| Table | Purpose | TTL |
|-------|---------|-----|
| `mason-session-memory` | Active task state, conversation context | 24 h |
| `mason-episodic-memory` | Past task outcomes — how bugs were fixed, what worked | None |
| `mason-semantic-memory` | Permanent knowledge: golden rules, conventions, architecture | None |

Semantic memory is seeded from `CLAUDE.md` on first run. Namespaces:
`conventions`, `architecture`, `preferences`, `golden_rules`.

Tables are created automatically by OpenTofu (`infra/lightsail/main.tf` or
`infra/tofu/modules/memory/main.tf`). Table names are configurable via `MASON_MEMORY_*` env vars
to support multi-tenant or staging overrides.

---

## 12. Architecture Reference

```
Dockerfile.webhook  →  webhook server (FastAPI, port 8000)
                        - receives Teams messages + Jira webhooks
                        - receives approval callbacks
                        - enqueues tasks to SQS
                        - GET /health

Dockerfile.worker   →  worker process (SQS long-poll)
                        - dequeues tasks
                        - runs WorkflowPipeline
                        - orchestrator → workers → PR → approval

docker-compose.prod.yml
                    →  runs both containers on the Lightsail instance
```

**Workflow state machine** (`src/workflows/`):
1. `pipeline.py` — top-level orchestration loop
2. `code_implementation.py` — worker sub-pipeline (clone, implement, test, commit)
3. `pr_creation.py` — open PR, post summary to Teams
4. `review_loop.py` — watch for PR comments, re-run workers if changes requested

---

## 13. Troubleshooting

### AWS credentials not found
```bash
aws sts get-caller-identity   # verify credentials
aws configure                 # or set AWS_PROFILE in .env
```

### SQS_QUEUE_URL missing
```bash
cd infra/lightsail && tofu output sqs_queue_url
# Copy the value into .env
```

### DynamoDB table not found
The tables should exist after `setup`. To verify:
```bash
aws dynamodb list-tables --region us-east-1 | grep mason
```

If missing, re-run `./scripts/deploy-lightsail.sh setup`.

### MCP token expired
- GitHub PAT: regenerate at github.com/settings/tokens, update `GITHUB_PAT` in `.env`, redeploy
- Atlassian token: regenerate at id.atlassian.com, update `ATLASSIAN_API_TOKEN`
- After updating `.env`: `./scripts/deploy-lightsail.sh deploy`

### Containers not starting
```bash
./scripts/deploy-lightsail.sh ssh
cd /opt/mason
docker compose -f docker-compose.prod.yml logs
docker compose -f docker-compose.prod.yml ps
```

### Health check
```bash
curl http://<LIGHTSAIL_IP>:8000/health
# Should return {"status": "ok"}

# Or via the script:
./scripts/deploy-lightsail.sh status
```

### Checking memory config (default table names)
The default table names in `src/memory/config.py` are `mason-session-memory`, etc. If you see
references to `devai-*` tables anywhere, they are stale — override with `MASON_MEMORY_*` env vars
or update the defaults in `config.py`.
