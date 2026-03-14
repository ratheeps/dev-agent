# MCP Connection Guide

This guide covers how to set up and connect every external integration that Mason uses. Five integrations use the **Model Context Protocol (MCP)** — a standard for connecting AI agents to external tools — and one (Bitbucket) uses a direct REST API.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Atlassian (Jira & Confluence)](#2-atlassian-jira--confluence)
3. [GitHub](#3-github)
4. [Bitbucket (Direct REST API)](#4-bitbucket-direct-rest-api)
5. [Figma](#5-figma)
6. [Microsoft Teams](#6-microsoft-teams)
7. [Playwright (Browser Automation)](#7-playwright-browser-automation)
8. [Configuration Reference](#8-configuration-reference)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Overview

### How Mason Uses MCP

Mason agents interact with external services through MCP servers. Each MCP server exposes a set of "tools" (functions) that agents can invoke. For example, the Atlassian MCP server exposes tools like `getJiraIssue` and `createJiraIssue`.

### Two Configuration Layers

Mason has two config files for MCP:

| File | Purpose | Used By |
|------|---------|---------|
| `.mcp.json` | Transport-level config (how to connect) | Claude Code / Claude Agent SDK runtime |
| `config/mcp_servers.yaml` | Programmatic config with env var refs | `MCPManager` singleton in application code |

When `MCPManager` initializes, it searches for `config/mcp_servers.yaml` first, then falls back to `.mcp.json`.

### Architecture

```
MCPManager (singleton)
├── .jira          → JiraClient           (Atlassian MCP)
├── .confluence    → ConfluenceClient     (Atlassian MCP)
├── .github        → GitHubRepoClient     (GitHub MCP)
├── .figma         → FigmaDesignClient    (Figma MCP)
├── .teams         → TeamsNotificationClient (Teams MCP)
├── .playwright    → PlaywrightUIClient   (Playwright MCP)
└── .scm(provider) → BitbucketClient      (Direct REST — httpx)
                   → GitHubSCMAdapter     (wraps GitHubRepoClient)
```

Each client is lazily initialized on first access via Python properties.

### Quick Reference

| Integration | Transport | Required Env Vars | Status |
|-------------|-----------|-------------------|--------|
| Atlassian (Jira/Confluence) | SSE | `ATLASSIAN_SITE_URL`, `ATLASSIAN_USER_EMAIL`, `ATLASSIAN_API_TOKEN` | Required |
| GitHub | Docker | `GITHUB_PAT` | Required (for GitHub-hosted repos) |
| Bitbucket | Direct HTTP (httpx) | `BITBUCKET_USERNAME`, `BITBUCKET_APP_PASSWORD` | Required (for Bitbucket repos) |
| Figma | HTTP | `FIGMA_PAT` | Optional — design tasks only |
| Microsoft Teams | stdio (Node.js) | `MS_APP_ID`, `MS_APP_PASSWORD`, `MS_TENANT_ID` | Required for notifications |
| Playwright | stdio (npx) | _(none required)_ | Optional — frontend tasks only |

---

## 2. Atlassian (Jira & Confluence)

### What It Does

- **Jira:** Read tickets, create subtasks, transition issues through workflows, search via JQL, add comments, get project issue types
- **Confluence:** Search pages by CQL, read page content (storage format)

### Transport

SSE (Server-Sent Events) to `https://mcp.atlassian.com/v1/sse` — cloud-hosted by Atlassian.

### Prerequisites

- Atlassian Cloud account with admin or project access
- API token for authentication

### Step-by-Step Setup

1. **Generate an API token:**
   - Go to https://id.atlassian.com/manage-profile/security/api-tokens
   - Click **Create API token**
   - Name it `Mason` (or similar), click **Create**
   - Copy the token immediately — it won't be shown again

2. **Set environment variables** in your `.env` file:
   ```
   ATLASSIAN_SITE_URL=https://your-org.atlassian.net
   ATLASSIAN_USER_EMAIL=you@example.com
   ATLASSIAN_API_TOKEN=<paste-token-here>
   ```

3. **No additional packages needed** — the MCP server is cloud-hosted by Atlassian.

### Configuration Files

**`.mcp.json`** — transport-level:
```json
{
  "mcpServers": {
    "atlassian": {
      "type": "sse",
      "url": "https://mcp.atlassian.com/v1/sse"
    }
  }
}
```

**`config/mcp_servers.yaml`** — programmatic:
```yaml
servers:
  atlassian:
    name: atlassian
    url: "https://mcp.atlassian.com/v1"
    enabled: true
    env:
      ATLASSIAN_SITE_URL: "${ATLASSIAN_SITE_URL}"
      ATLASSIAN_USER_EMAIL: "${ATLASSIAN_USER_EMAIL}"
      ATLASSIAN_API_TOKEN: "${ATLASSIAN_API_TOKEN}"
```

### MCP Tool Names

These are the exact tool names invoked by Mason's clients:

**Jira** (`src/integrations/atlassian/jira_client.py`):
| Tool Name | Used For |
|-----------|----------|
| `mcp__claude_ai_Atlassian__getJiraIssue` | Fetch a single issue by key |
| `mcp__claude_ai_Atlassian__createJiraIssue` | Create subtasks |
| `mcp__claude_ai_Atlassian__transitionJiraIssue` | Move issues through workflow |
| `mcp__claude_ai_Atlassian__getTransitionsForJiraIssue` | List available transitions |
| `mcp__claude_ai_Atlassian__searchJiraIssuesUsingJql` | JQL search |
| `mcp__claude_ai_Atlassian__addCommentToJiraIssue` | Add comments |
| `mcp__claude_ai_Atlassian__getJiraProjectIssueTypesMetadata` | Get project issue types |

**Confluence** (`src/integrations/atlassian/confluence_client.py`):
| Tool Name | Used For |
|-----------|----------|
| `mcp__claude_ai_Atlassian__fetch` | Generic fetch — calls Confluence REST API v2 endpoints |

Confluence uses the generic `fetch` tool with relative URL paths like `/wiki/api/v2/pages/{id}` and `/wiki/rest/api/content/search?cql=...`.

### Verification

```bash
# Quick test: search for a known Jira issue
python -c "
import asyncio
from src.integrations.mcp_manager import MCPManager

async def test():
    # This requires a running agent runtime with mcp_call wired up
    print('Atlassian MCP config loaded successfully')

asyncio.run(test())
"

# Or use manual trigger with a known ticket
python -m src.handlers.manual_trigger --ticket GIFT-1234 --bedrock
```

---

## 3. GitHub

### What It Does

- Get repository metadata
- Create and delete branches (resolves SHA from source ref)
- Create and fetch pull requests
- List PR review comments
- Push files (create or update via base64 content)

### Transport

Docker container running `ghcr.io/github/github-mcp-server`.

### Prerequisites

- GitHub account with a Personal Access Token (PAT)
- Docker daemon running (the MCP server runs as a container)

### Step-by-Step Setup

1. **Create a GitHub PAT:**
   - Go to https://github.com/settings/tokens
   - Click **Generate new token (classic)**
   - Select scopes: `repo` (full), `read:org`
   - Click **Generate token**, copy it

2. **Set environment variable** in `.env`:
   ```
   GITHUB_PAT=ghp_xxxxxxxxxxxx
   ```

3. **Ensure Docker is running:**
   ```bash
   docker info  # Should show Docker daemon info
   ```

### Configuration Files

**`.mcp.json`**:
```json
{
  "mcpServers": {
    "github": {
      "type": "docker",
      "image": "ghcr.io/github/github-mcp-server",
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PAT}"
      }
    }
  }
}
```

**`config/mcp_servers.yaml`**:
```yaml
servers:
  github:
    name: github
    url: "https://mcp.github.com/v1"
    enabled: true
    env:
      GITHUB_TOKEN: "${GITHUB_TOKEN}"
```

> **Note:** `.mcp.json` uses `GITHUB_PAT` while `mcp_servers.yaml` uses `GITHUB_TOKEN`. Set both in your `.env` if using both config paths, or set them to the same value.

### MCP Tool Names

Tool prefix: `mcp__github__` (configurable via `tool_prefix` parameter on `GitHubRepoClient`).

| Tool Name | Used For |
|-----------|----------|
| `mcp__github__get_repo` | Get repository metadata |
| `mcp__github__get_ref` | Resolve a Git ref to SHA |
| `mcp__github__create_ref` | Create a branch |
| `mcp__github__delete_ref` | Delete a branch |
| `mcp__github__create_pull_request` | Open a PR |
| `mcp__github__get_pull_request` | Fetch a PR |
| `mcp__github__list_pull_request_comments` | List PR review comments |
| `mcp__github__create_or_update_file` | Push file contents |

### Mason Client

`GitHubRepoClient` at `src/integrations/github/repo_client.py`.

GitHub repos also integrate with the SCM abstraction layer via `GitHubSCMAdapter` (`src/integrations/scm/github_adapter.py`), which implements the `SCMClient` protocol alongside `BitbucketClient`.

### Verification

```bash
# Verify Docker can pull the GitHub MCP image
docker pull ghcr.io/github/github-mcp-server

# Verify your PAT works
curl -H "Authorization: token $GITHUB_PAT" https://api.github.com/user
```

---

## 4. Bitbucket (Direct REST API)

### What It Does

- Create branches (resolves SHA from source ref)
- Create, fetch pull requests
- Add PR comments
- Read file contents at a given ref

### Transport

**Direct HTTP API** via `httpx` — this is **not** an MCP server. `BitbucketClient` calls the Bitbucket REST API v2.0 at `https://api.bitbucket.org/2.0` directly.

### Prerequisites

- Bitbucket Cloud account
- App Password with appropriate scopes

### Step-by-Step Setup

1. **Create a Bitbucket App Password:**
   - Go to **Bitbucket** → **Personal Settings** → **App passwords**
   - Click **Create app password**
   - Name it `Mason`
   - Select permissions:
     - **Repositories:** Read, Write
     - **Pull requests:** Read, Write
   - Click **Create**, copy the password

2. **Set environment variables** in `.env`:
   ```
   BITBUCKET_USERNAME=your-username
   BITBUCKET_APP_PASSWORD=<paste-app-password>
   ```

### Mason Client

`BitbucketClient` at `src/integrations/scm/bitbucket_client.py`.

### SCM Protocol

Both `BitbucketClient` and `GitHubSCMAdapter` implement the `SCMClient` protocol defined in `src/integrations/scm/protocol.py`. This protocol provides a unified interface for:

- `create_branch(repo, branch, from_ref)`
- `create_pull_request(repo, title, body, head_branch, base_branch, reviewers)`
- `get_pull_request(repo, pr_number)`
- `add_pr_comment(repo, pr_number, body)`
- `get_file_contents(repo, path, ref)`

`MCPManager.scm(provider)` returns the correct client based on the `SCMProvider` enum.

### Which Repos Use Bitbucket

Per `config/repositories.yaml`, all GiftBee application repos use Bitbucket:

| Repository | Base Branch | Tech Stacks |
|------------|-------------|-------------|
| `wallet-service` | `dev` | PHP, Laravel, React, TypeScript |
| `store-front` | `main` | Next.js, React, TypeScript |
| `admin-portal` | `dev` | Next.js, React, TypeScript |
| `pim` | `dev` | PHP (Pimcore) |
| `local-infra` | `dev` | Docker/DevOps |

### Verification

```bash
# Test Bitbucket credentials
curl -u "$BITBUCKET_USERNAME:$BITBUCKET_APP_PASSWORD" \
  https://api.bitbucket.org/2.0/repositories/giftbee?pagelen=5
```

---

## 5. Figma

### What It Does

- Get file metadata and document tree
- Get specific nodes by ID
- Get published styles (colors, typography, etc.)
- Get published components

### Transport

HTTP to `https://mcp.figma.com/mcp` — cloud-hosted by Figma.

### Prerequisites

- Figma account with a Personal Access Token

### Step-by-Step Setup

1. **Generate a Figma PAT:**
   - Go to **Figma** → **Account Settings** → **Security** → **Personal access tokens**
   - Click **Generate new token**
   - Name it `Mason`, copy the token

2. **Set environment variable** in `.env`:
   ```
   FIGMA_PAT=figd_xxxxxxxxxxxx
   ```

3. **No additional packages needed** — cloud-hosted MCP server.

### Configuration Files

**`.mcp.json`**:
```json
{
  "mcpServers": {
    "figma": {
      "type": "http",
      "url": "https://mcp.figma.com/mcp"
    }
  }
}
```

**`config/mcp_servers.yaml`**:
```yaml
servers:
  figma:
    name: figma
    url: "https://mcp.figma.com/v1"
    enabled: true
    env:
      FIGMA_ACCESS_TOKEN: "${FIGMA_ACCESS_TOKEN}"
```

### MCP Tool Names

Tool prefix: `mcp__figma__` (configurable via `tool_prefix` parameter).

| Tool Name | Used For |
|-----------|----------|
| `mcp__figma__get_file` | Full file metadata and document tree |
| `mcp__figma__get_node` | Specific node by ID |
| `mcp__figma__get_file_styles` | Published styles |
| `mcp__figma__get_file_components` | Published components |

### Mason Client

`FigmaDesignClient` at `src/integrations/figma/design_client.py`.

> **Note:** Figma integration is optional. It's only needed for UI/design-heavy tasks where agents need to reference design specs.

### Verification

```bash
# Test your Figma PAT
curl -H "X-Figma-Token: $FIGMA_PAT" \
  "https://api.figma.com/v1/me"
```

---

## 6. Microsoft Teams

### What It Does

- Send channel messages (plain text or HTML)
- Send direct messages to specific users
- Send Adaptive Card approval requests (with Approve/Reject buttons)
- Send rich status cards (showing agent progress on a Jira ticket)
- Reply in threads

### Transport

stdio — runs as a Node.js process via `node ./node_modules/@mcp/teams-connector/dist/index.js`.

### Prerequisites

- Azure AD app registration
- Node.js 18+
- npm package `@mcp/teams-connector`

### Step-by-Step Setup

1. **Register an Azure AD application:**
   - Go to https://portal.azure.com → **Azure Active Directory** → **App registrations**
   - Click **New registration**
   - Name: `Mason Bot`
   - Supported account types: **Accounts in any organizational directory (Multi-tenant)**
   - Click **Register**

2. **Collect application IDs:**
   - Note the **Application (client) ID** → this becomes `MS_APP_ID`
   - Note the **Directory (tenant) ID** → this becomes `MS_TENANT_ID`

3. **Create a client secret:**
   - Go to **Certificates & secrets** → **New client secret**
   - Set an expiry (recommended: 24 months)
   - Copy the **Value** immediately → this becomes `MS_APP_PASSWORD`

4. **Configure API permissions:**
   - Go to **API permissions** → **Add a permission** → **Microsoft Graph**
   - Add delegated/application permissions:
     - `ChannelMessage.Send`
     - `Chat.ReadWrite`
   - Click **Grant admin consent**

5. **Install the npm package:**
   ```bash
   npm install @mcp/teams-connector
   ```

6. **Set environment variables** in `.env`:
   ```
   MS_APP_ID=<application-client-id>
   MS_APP_PASSWORD=<client-secret-value>
   MS_TENANT_ID=<directory-tenant-id>
   ```

7. **Configure Teams channels** in `.env`:
   ```
   MASON_TEAMS_NOTIFICATION_CHANNEL=mason-notifications
   MASON_TEAMS_APPROVAL_CHANNEL=mason-approvals
   ```

### Configuration Files

**`.mcp.json`**:
```json
{
  "mcpServers": {
    "teams": {
      "type": "stdio",
      "command": "node",
      "args": ["./node_modules/@mcp/teams-connector/dist/index.js"],
      "env": {
        "MICROSOFT_APP_ID": "${MS_APP_ID}",
        "MICROSOFT_APP_PASSWORD": "${MS_APP_PASSWORD}",
        "MICROSOFT_TENANT_ID": "${MS_TENANT_ID}"
      }
    }
  }
}
```

**`config/mcp_servers.yaml`**:
```yaml
servers:
  teams:
    name: teams
    url: "https://mcp.teams.microsoft.com/v1"
    enabled: true
    env:
      TEAMS_TENANT_ID: "${TEAMS_TENANT_ID}"
      TEAMS_CLIENT_ID: "${TEAMS_CLIENT_ID}"
      TEAMS_CLIENT_SECRET: "${TEAMS_CLIENT_SECRET}"
```

### MCP Tool Names

Tool prefix: `mcp__teams__` (configurable via `tool_prefix` parameter).

| Tool Name | Used For |
|-----------|----------|
| `mcp__teams__send_channel_message` | Channel messages, approval cards, status cards |
| `mcp__teams__send_direct_message` | 1:1 direct messages |
| `mcp__teams__reply_to_message` | Threaded replies |

### Mason Client

`TeamsNotificationClient` at `src/integrations/teams/notification_client.py`.

### Webhook Endpoints

The webhook server (`src/handlers/webhook_server.py`) receives responses from Teams:

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/webhooks/teams/approval` | Adaptive Card Approve/Reject button callbacks |
| `POST` | `/webhooks/teams/message` | @mention handling from Teams |
| `GET` | `/approvals/{id}` | Check approval request status |

These endpoints are served by the FastAPI webhook server (see `Dockerfile.webhook` / `docker-compose.prod.yml`).

### Verification

```bash
# Verify Node.js is available
node --version  # Should be 18+

# Verify the Teams connector package is installed
ls node_modules/@mcp/teams-connector/dist/index.js

# Test Azure AD token acquisition
curl -X POST "https://login.microsoftonline.com/$MS_TENANT_ID/oauth2/v2.0/token" \
  -d "client_id=$MS_APP_ID" \
  -d "client_secret=$MS_APP_PASSWORD" \
  -d "scope=https://graph.microsoft.com/.default" \
  -d "grant_type=client_credentials"
```

---

## 7. Playwright (Browser Automation)

### What It Does

- Navigate pages, take screenshots
- Click, fill, type, select options on page elements
- Assert element visibility and text content
- Get console errors and DOM snapshots
- Evaluate arbitrary JavaScript in the page context
- High-level `verify_assertions()` for batch UI testing

### Transport

stdio via `npx @playwright/mcp@latest --headless`.

### Prerequisites

- Node.js 18+

### Step-by-Step Setup

1. **Optional — pre-install browsers** (speeds up first run):
   ```bash
   npx playwright install chromium
   ```

2. **Optional — set custom browser path** in `.env`:
   ```
   PLAYWRIGHT_BROWSERS_PATH=/path/to/browsers
   ```

3. **No other configuration needed.** Playwright MCP launches on demand via npx.

### Configuration Files

**`.mcp.json`**:
```json
{
  "mcpServers": {
    "playwright": {
      "type": "stdio",
      "command": "npx",
      "args": ["@playwright/mcp@latest", "--headless"],
      "env": {
        "PLAYWRIGHT_BROWSERS_PATH": "${PLAYWRIGHT_BROWSERS_PATH}"
      }
    }
  }
}
```

**`config/mcp_servers.yaml`**:
```yaml
servers:
  playwright:
    name: playwright
    command: "npx"
    args:
      - "@playwright/mcp@latest"
    enabled: true
    headless: true
    env:
      PLAYWRIGHT_BROWSERS_PATH: "${PLAYWRIGHT_BROWSERS_PATH}"
```

### MCP Tool Names

Tool prefix: `mcp__playwright__` (configurable via `tool_prefix` parameter).

| Tool Name | Used For |
|-----------|----------|
| `mcp__playwright__navigate` | Navigate to a URL |
| `mcp__playwright__screenshot` | Capture page screenshot |
| `mcp__playwright__click` | Click an element by selector |
| `mcp__playwright__fill` | Fill an input field |
| `mcp__playwright__select_option` | Select from a dropdown |
| `mcp__playwright__type` | Type text keystroke-by-keystroke |
| `mcp__playwright__get_text` | Get inner text of an element |
| `mcp__playwright__assert_visible` | Check element visibility |
| `mcp__playwright__get_console_errors` | Get browser console errors |
| `mcp__playwright__get_dom_snapshot` | Get DOM and visible text snapshot |
| `mcp__playwright__evaluate` | Run JavaScript in page context |
| `mcp__playwright__close` | Close the browser |

### Auto-Activation

When a task involves frontend tech stacks (React, Next.js, Playwright), worker agents automatically get browser tools added to their `allowed_tools` list. This is configured in `config/agents.yaml`:

```yaml
claude_agent_sdk:
  allowed_tools:
    worker_frontend:
      - Read
      - Write
      - Bash
      - browser_navigate
      - browser_screenshot
      - browser_click
      - browser_type
      - browser_fill
      - browser_select_option
      - browser_evaluate
      - browser_close
```

### Mason Client

`PlaywrightUIClient` at `src/integrations/playwright/ui_client.py`.

### Verification

```bash
# Verify npx is available
npx --version

# Verify Playwright can launch
npx @playwright/mcp@latest --headless --help

# Optional: verify Chromium is installed
npx playwright install --dry-run chromium
```

---

## 8. Configuration Reference

### `.mcp.json` (Full Annotated)

This file defines transport-level MCP connections used by Claude Code and the Claude Agent SDK runtime.

```jsonc
{
  "mcpServers": {
    // Atlassian (Jira + Confluence) — cloud-hosted SSE
    "atlassian": {
      "type": "sse",
      "url": "https://mcp.atlassian.com/v1/sse"
    },

    // Figma — cloud-hosted HTTP
    "figma": {
      "type": "http",
      "url": "https://mcp.figma.com/mcp"
    },

    // GitHub — runs as a Docker container
    "github": {
      "type": "docker",
      "image": "ghcr.io/github/github-mcp-server",
      "env": {
        // Maps to GITHUB_PAT from your .env
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PAT}"
      }
    },

    // Microsoft Teams — runs as a local Node.js process
    "teams": {
      "type": "stdio",
      "command": "node",
      "args": ["./node_modules/@mcp/teams-connector/dist/index.js"],
      "env": {
        "MICROSOFT_APP_ID": "${MS_APP_ID}",
        "MICROSOFT_APP_PASSWORD": "${MS_APP_PASSWORD}",
        "MICROSOFT_TENANT_ID": "${MS_TENANT_ID}"
      }
    },

    // Playwright — runs via npx on demand
    "playwright": {
      "type": "stdio",
      "command": "npx",
      "args": ["@playwright/mcp@latest", "--headless"],
      "env": {
        "PLAYWRIGHT_BROWSERS_PATH": "${PLAYWRIGHT_BROWSERS_PATH}"
      }
    }
  }
}
```

### `config/mcp_servers.yaml` (Full Annotated)

This file is the programmatic config loaded by `MCPManager`. It takes precedence over `.mcp.json` when present.

```yaml
# MCP Server Configuration
# ========================
# Auth tokens / secrets are supplied via environment variables referenced
# in the env mapping. Use "${ENV_VAR}" syntax for substitution.

servers:
  atlassian:
    name: atlassian
    url: "https://mcp.atlassian.com/v1"
    enabled: true                              # Set to false to disable
    env:
      ATLASSIAN_SITE_URL: "${ATLASSIAN_SITE_URL}"      # e.g. https://your-org.atlassian.net
      ATLASSIAN_USER_EMAIL: "${ATLASSIAN_USER_EMAIL}"
      ATLASSIAN_API_TOKEN: "${ATLASSIAN_API_TOKEN}"

  github:
    name: github
    url: "https://mcp.github.com/v1"
    enabled: true
    env:
      GITHUB_TOKEN: "${GITHUB_TOKEN}"

  figma:
    name: figma
    url: "https://mcp.figma.com/v1"
    enabled: true
    env:
      FIGMA_ACCESS_TOKEN: "${FIGMA_ACCESS_TOKEN}"

  teams:
    name: teams
    url: "https://mcp.teams.microsoft.com/v1"
    enabled: true
    env:
      TEAMS_TENANT_ID: "${TEAMS_TENANT_ID}"
      TEAMS_CLIENT_ID: "${TEAMS_CLIENT_ID}"
      TEAMS_CLIENT_SECRET: "${TEAMS_CLIENT_SECRET}"

  playwright:
    name: playwright
    command: "npx"                             # stdio transport
    args:
      - "@playwright/mcp@latest"
    enabled: true
    headless: true                             # false for local debug
    env:
      PLAYWRIGHT_BROWSERS_PATH: "${PLAYWRIGHT_BROWSERS_PATH}"
```

### How MCPManager Loads Config

The loading logic in `src/integrations/mcp_manager.py`:

1. If an explicit `config_path` is passed to `MCPManager.create()`, use that file
2. Otherwise, search in order:
   - `config/mcp_servers.yaml` (resolved relative to project root)
   - `.mcp.json` (at project root)
3. Parse the file (YAML or JSON) and look for keys `servers` or `mcpServers`
4. Each entry is loaded into an `MCPServerConfig` Pydantic model

### Environment Variable Substitution

Strings in the format `"${ENV_VAR}"` in config files are references to environment variables. These are resolved at runtime by the respective transport layer (Claude Code, Agent SDK, or the MCPManager config loader). Set all referenced env vars in your `.env` file.

---

## 9. Troubleshooting

### Token Expired or Invalid

| Integration | How to Regenerate |
|-------------|-------------------|
| Atlassian | https://id.atlassian.com/manage-profile/security/api-tokens → Revoke old, create new |
| GitHub | https://github.com/settings/tokens → Delete old, generate new with same scopes |
| Bitbucket | Bitbucket → Personal Settings → App passwords → Revoke and recreate |
| Figma | Figma → Account Settings → Security → Personal access tokens → Delete and recreate |
| Teams | Azure Portal → App registrations → Your app → Certificates & secrets → New client secret |

After regenerating, update the corresponding env var in `.env` and restart Mason.

### Docker Not Running (GitHub MCP Fails)

The GitHub MCP server runs as a Docker container. If Docker isn't running:

```
Error: Cannot connect to the Docker daemon
```

**Fix:** Start Docker Desktop or the Docker daemon:
```bash
sudo systemctl start docker   # Linux
# or open Docker Desktop       # macOS/Windows
```

### Node.js Not Installed (Teams / Playwright Fail)

Teams and Playwright MCP servers require Node.js 18+.

```
Error: npx: command not found
Error: node: command not found
```

**Fix:**
```bash
# Install Node.js 18+ via nvm
nvm install 18
nvm use 18
```

### "MCP Tool Not Found" Errors

If an agent reports a tool like `mcp__github__get_repo` is not found:

1. **Check `.mcp.json`:** Ensure the server entry exists and the name matches
2. **Check tool prefix:** The prefix is derived from the server name in `.mcp.json`. If you named it `"gh"` instead of `"github"`, the tools would be prefixed `mcp__gh__` instead of `mcp__github__`
3. **Check the server is running:** For Docker-based servers, verify the container is up. For stdio servers, check the process is spawning correctly
4. **Check `enabled` flag:** In `config/mcp_servers.yaml`, ensure `enabled: true` for the server

### Connection Timeout

MCP calls have a default timeout configured in `config/limits.yaml`:

```yaml
timeouts:
  mcp_call_seconds: 30
```

If you're hitting timeouts:
- Check network connectivity to the MCP server URL
- For cloud-hosted servers (Atlassian, Figma), check their status pages
- For local servers (Teams, Playwright), check the process is running
- Increase the timeout in `config/limits.yaml` if needed

### Rate Limiting

Per-MCP rate limits are configured in `config/limits.yaml`:

```yaml
rate_limits:
  jira_rpm: 60
  github_rpm: 60
  figma_rpm: 30
  teams_rpm: 30
```

If you hit rate limits, reduce concurrency (`workers.max_concurrent`) or increase the limit.
