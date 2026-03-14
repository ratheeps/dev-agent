# mason

**Multi-agent AI system for automated software delivery**

## Overview

This project is an autonomous AI engineering team that can take requirements, implement code, and manage the pull request lifecycle. 

### Core Components

1. **Multi-Agent Orchestration**
   * **Lead Architect (Claude 4.6 Opus):** Ingests project context and breaks down Jira tickets into phased implementation plans.
   * **Execution Team (Claude 4.6 Sonnet):** Multiple Sonnet agents run in parallel to execute code implementation tasks efficiently and at lower cost.

2. **Infrastructure & Memory (AWS)**
   * **Hosting:** Runs on **Amazon Bedrock AgentCore Runtime**, a serverless, pay-per-execution-time environment.
   * **Persistent Memory:** Uses Bedrock AgentCore Memory backed by DynamoDB for short-term memory (active tasks), episodic memory (past bugs), and long-term semantic memory (coding preferences).

3. **Integrations (via Model Context Protocol - MCP)**
   * **Jira & Confluence:** For reading requirements and generating epics/sub-tasks.
   * **Figma:** To ingest design components, spacing, and colors.
   * **GitHub / Bitbucket:** To clone repositories, read diffs, commit code, and open PRs.

4. **Automated Workflows & Chat**
   * **PR Loops:** Agents can automatically read human feedback on Pull Requests, rewrite code, fix tests, and push new commits.
   * **Human-in-the-Loop:** Integrates with Slack or Microsoft Teams via MCP to ping a human engineer for approval on design choices or merging PRs.

---

## Planned Enhancements & Roadmap

To improve the quality, efficiency, and cost-effectiveness of this multi-agent system, we plan to implement the following architectural and operational enhancements:

### 1. Leverage LLM Prompt Caching
Caching static context (like system prompts and architectural guidelines) to reduce input token costs by up to 90% and significantly decrease time-to-first-token (TTFT).

### 2. Introduce a "Router" Agent
Implementing a fast, cheap model (like Claude 3.5 Haiku) to triage incoming webhooks/tickets, assigning simple tasks directly to Worker agents and saving complex architectural breakdowns for the Lead Architect.

### 3. Agentic Sandboxing & Local Verification
Providing Worker agents with a secure execution sandbox (e.g., Docker or E2B) to run linting, type-checking, and tests autonomously *before* submitting Pull Requests.

### 4. Upgrade Memory to a Vector Database
Integrating a Vector Database (like Qdrant or Pinecone) to replace or augment DynamoDB, enabling agents to dynamically retrieve the most relevant past PRs, bug fixes, and architectural rules based on semantic search.

### 5. Abstract Syntax Tree (AST) & Codebase Mapping Tools
Creating MCP tools to allow the agent to query the codebase structurally (e.g., via Tree-sitter), reducing token consumption by only reading the specific chunks of code needed for modifications.

### 6. Implement a "Critic" Phase
Adding an automated code review step using a separate agent to evaluate the generated code diff against the original requirement, catching logic gaps prior to human review.

### 7. Circuit Breakers for Token Limits
Utilizing circuit breakers to monitor token usage and retries per task, preventing infinite loops and saving API budgets by pinging a human when stuck.
